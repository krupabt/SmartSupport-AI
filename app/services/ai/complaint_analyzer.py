import re
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.extensions import db
from app.models.ticket import Ticket, TicketPriority, TicketCategory
from app.models.ai_analysis import AIAnalysis, AIAnalysisStatus
from app.services.ai.schemas import AIAnalysisResult, ALLOWED_CATEGORIES, ALLOWED_SENTIMENTS, ALLOWED_PRIORITIES
from app.services.ai.prompts import COMPLAINT_ANALYSIS_SYSTEM_PROMPT, build_analysis_user_prompt
from app.services.ai.llm_service import LLMService

logger = logging.getLogger(__name__)


class ComplaintAnalyzer:
    """Service to orchestrate AI analysis and database synchronization for customer complaints."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    def parse_llm_json(self, raw_text: str) -> dict:
        """Robustly extract and parse JSON from raw LLM output text."""
        cleaned = raw_text.strip()

        # Remove markdown code block wrappers if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        # Direct JSON parse attempt
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Regex search for outermost JSON object { ... }
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as je:
                raise ValueError(f"Extracted string is not valid JSON: {str(je)}")

        raise ValueError("No valid JSON structure found in LLM response.")

    def normalize_taxonomy(self, data: dict) -> dict:
        """Normalize casing to match schema."""
        raw_cat = str(data.get("category", "")).strip()
        raw_sent = str(data.get("sentiment", "")).strip()
        raw_prio = str(data.get("priority", "")).strip()

        # Match category case-insensitively
        for allowed_cat in ALLOWED_CATEGORIES:
            if raw_cat.lower() == allowed_cat.lower():
                data["category"] = allowed_cat
                break

        # Match sentiment case-insensitively
        for allowed_sent in ALLOWED_SENTIMENTS:
            if raw_sent.lower() == allowed_sent.lower():
                data["sentiment"] = allowed_sent
                break

        # Match priority case-insensitively
        for allowed_prio in ALLOWED_PRIORITIES:
            if raw_prio.lower() == allowed_prio.lower():
                data["priority"] = allowed_prio
                break

        return data

    def analyze_complaint(
        self,
        subject: str,
        description: str,
        product_service: str = "",
        reference_id: str = "",
    ) -> AIAnalysisResult:
        """Send complaint to LLM and validate structured output."""
        prompt = build_analysis_user_prompt(
            subject=subject,
            description=description,
            product_service=product_service,
            reference_id=reference_id,
        )

        logger.info(f"Starting AI analysis for subject: '{subject[:40]}...'")
        raw_output = self.llm_service.generate(prompt, system_prompt=COMPLAINT_ANALYSIS_SYSTEM_PROMPT)

        # Parse JSON
        parsed_data = self.parse_llm_json(raw_output)
        parsed_data = self.normalize_taxonomy(parsed_data)

        # Construct result container
        result = AIAnalysisResult(
            category=parsed_data.get("category"),
            sentiment=parsed_data.get("sentiment"),
            priority=parsed_data.get("priority"),
            confidence=float(parsed_data.get("confidence", 0.0)),
            reason=parsed_data.get("reason", "").strip(),
            model_name=self.llm_service.provider.model_name,
            provider=self.llm_service.provider.provider_name,
            raw_response=raw_output,
        )

        is_valid, err_msg = result.validate()
        if not is_valid:
            logger.error(f"AI response validation failed: {err_msg}")
            raise ValueError(f"AI Output Validation Error: {err_msg}")

        logger.info(f"AI analysis completed: Category='{result.category}', Priority='{result.priority}', Sentiment='{result.sentiment}'")
        return result

    def analyze_and_store(self, ticket: Ticket) -> AIAnalysis:
        """Run analysis on a ticket and synchronize DB models with full fault tolerance."""
        # Find or create AIAnalysis entity
        analysis = AIAnalysis.query.filter_by(ticket_id=ticket.id).first()
        if not analysis:
            analysis = AIAnalysis(ticket_id=ticket.id)
            db.session.add(analysis)

        # Check if LLM provider is configured
        if not self.llm_service.is_available():
            logger.warning(f"AI service unconfigured for Ticket {ticket.ticket_number}. Marking as UNAVAILABLE.")
            analysis.status = AIAnalysisStatus.UNAVAILABLE
            analysis.reason = "AI analysis is currently unavailable because the AI service is not configured with an API key."
            analysis.provider = self.llm_service.provider.provider_name
            analysis.model_name = self.llm_service.provider.model_name
            db.session.commit()
            return analysis

        analysis.status = AIAnalysisStatus.PENDING
        db.session.commit()

        try:
            result = self.analyze_complaint(
                subject=ticket.subject,
                description=ticket.description,
                product_service=ticket.product_service,
                reference_id=ticket.reference_id,
            )

            # Update AIAnalysis record
            analysis.category = result.category
            analysis.sentiment = result.sentiment
            analysis.priority = result.priority
            analysis.confidence = result.confidence
            analysis.reason = result.reason
            analysis.model_name = result.model_name
            analysis.provider = result.provider
            analysis.raw_response = result.raw_response
            analysis.status = AIAnalysisStatus.COMPLETED

            # Synchronize Ticket metadata
            ticket.category = result.category
            ticket.sentiment = result.sentiment
            # Map priority (e.g. 'High' -> 'HIGH')
            prio_upper = result.priority.upper()
            if prio_upper in TicketPriority.ALL:
                ticket.priority = prio_upper

            ticket.updated_at = datetime.now(timezone.utc)
            db.session.commit()
            return analysis

        except Exception as e:
            logger.error(f"AI analysis failed for Ticket {ticket.ticket_number}: {str(e)}", exc_info=True)
            db.session.rollback()
            analysis.status = AIAnalysisStatus.FAILED
            analysis.reason = f"AI analysis could not be completed: {str(e)}"
            analysis.provider = self.llm_service.provider.provider_name
            analysis.model_name = self.llm_service.provider.model_name
            db.session.commit()
            return analysis
