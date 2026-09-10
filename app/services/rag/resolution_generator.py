import re
import json
import logging
from typing import List, Optional

from app.services.ai.llm_service import LLMService
from app.services.rag.schemas import RetrievedChunk, RAGResolutionResult, RAGSourceResult
from app.services.rag.prompts import RAG_RESOLUTION_SYSTEM_PROMPT, build_rag_user_prompt

logger = logging.getLogger(__name__)


class ResolutionGenerator:
    """Generates strictly grounded customer resolution responses via the LLM provider."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()

    def parse_llm_json(self, raw_text: str) -> dict:
        """Extract and parse structured JSON from LLM response."""
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as je:
                raise ValueError(f"Extracted JSON string is invalid: {str(je)}")

        raise ValueError("No valid JSON structure found in LLM response.")

    def generate_resolution(
        self,
        subject: str,
        description: str,
        product_service: str = "",
        reference_id: str = "",
        chunks: List[RetrievedChunk] = None,
    ) -> RAGResolutionResult:
        """Execute grounded generation using retrieved knowledge chunks."""
        chunks = chunks or []

        # 1. Check if knowledge context is empty
        if not chunks:
            logger.info("No relevant knowledge base chunks found. Returning NO_RELEVANT_CONTEXT.")
            return RAGResolutionResult(
                answer="AI could not find enough verified information in the current knowledge base to provide a reliable resolution. Your ticket has been routed to our support team for review.",
                confidence=0.0,
                needs_escalation=True,
                reason="No relevant knowledge-base documents matched the complaint query above the similarity threshold.",
                sources=[],
                status="NO_RELEVANT_CONTEXT",
                model_name=self.llm_service.provider.model_name,
                provider=self.llm_service.provider.provider_name,
                retrieval_count=0,
            )

        # 2. Check if LLM provider is available
        if not self.llm_service.is_available():
            logger.warning("LLM service is unconfigured. Returning UNAVAILABLE status.")
            # Build citations for retrieved chunks even if generation is unconfigured
            sources = [
                RAGSourceResult(
                    document_id=c.document_id,
                    chunk_id=c.chunk_id,
                    source_title=c.document_title,
                    filename=c.filename,
                    similarity_score=c.similarity_score,
                    excerpt=c.content[:200] + "...",
                    page_number=c.page_number,
                )
                for c in chunks[:3]
            ]
            return RAGResolutionResult(
                answer="AI resolution is currently unavailable because the AI service is not configured with an API key. Support staff can review the retrieved policy documents directly.",
                confidence=0.0,
                needs_escalation=True,
                reason="AI service API key is unconfigured in .env.",
                sources=sources,
                status="UNAVAILABLE",
                model_name=self.llm_service.provider.model_name,
                provider=self.llm_service.provider.provider_name,
                retrieval_count=len(chunks),
            )

        prompt = build_rag_user_prompt(
            subject=subject,
            description=description,
            product_service=product_service,
            reference_id=reference_id,
            chunks=chunks,
        )

        try:
            raw_output = self.llm_service.generate(
                prompt=prompt,
                system_prompt=RAG_RESOLUTION_SYSTEM_PROMPT,
            )

            data = self.parse_llm_json(raw_output)

            answer = str(data.get("answer", "")).strip()
            confidence = float(data.get("confidence", 0.85))
            confidence = max(0.0, min(1.0, confidence))
            needs_escalation = bool(data.get("needs_escalation", False))
            reason = str(data.get("reason", "Resolved using retrieved company policies.")).strip()

            # Map source chunk citations
            used_source_ids = data.get("source_chunk_ids", [])
            sources = []
            
            if isinstance(used_source_ids, list) and used_source_ids:
                for idx in used_source_ids:
                    if isinstance(idx, int) and 1 <= idx <= len(chunks):
                        c = chunks[idx - 1]
                        sources.append(
                            RAGSourceResult(
                                document_id=c.document_id,
                                chunk_id=c.chunk_id,
                                source_title=c.document_title,
                                filename=c.filename,
                                similarity_score=c.similarity_score,
                                excerpt=c.content[:250] + ("..." if len(c.content) > 250 else ""),
                                page_number=c.page_number,
                            )
                        )

            # If model didn't specify indices or failed, use all top retrieved chunks
            if not sources:
                for c in chunks[:3]:
                    sources.append(
                        RAGSourceResult(
                            document_id=c.document_id,
                            chunk_id=c.chunk_id,
                            source_title=c.document_title,
                            filename=c.filename,
                            similarity_score=c.similarity_score,
                            excerpt=c.content[:250] + ("..." if len(c.content) > 250 else ""),
                            page_number=c.page_number,
                        )
                    )

            result = RAGResolutionResult(
                answer=answer,
                confidence=confidence,
                needs_escalation=needs_escalation,
                reason=reason,
                sources=sources,
                status="COMPLETED",
                model_name=self.llm_service.provider.model_name,
                provider=self.llm_service.provider.provider_name,
                retrieval_count=len(chunks),
            )

            is_valid, val_err = result.validate()
            if not is_valid:
                raise ValueError(f"RAG result schema validation failed: {val_err}")

            logger.info(f"Grounded RAG resolution completed successfully with {len(sources)} citations.")
            return result

        except Exception as e:
            logger.error(f"Error during RAG generation: {str(e)}", exc_info=True)
            return RAGResolutionResult(
                answer="An error occurred while generating the AI resolution. The support team has been notified.",
                confidence=0.0,
                needs_escalation=True,
                reason=f"RAG generation failure: {str(e)}",
                sources=[],
                status="FAILED",
                model_name=self.llm_service.provider.model_name,
                provider=self.llm_service.provider.provider_name,
                retrieval_count=len(chunks),
            )
