from typing import List
from app.services.rag.schemas import RetrievedChunk

RAG_RESOLUTION_SYSTEM_PROMPT = """You are an enterprise customer-support resolution assistant.

Your task is to provide an accurate, helpful resolution to the customer's complaint ONLY using the supplied Knowledge Base Context.

STRICT GROUNDING & ANTI-HALLUCINATION RULES:
1. Answer the customer's issue using ONLY facts, policies, and instructions found explicitly in the provided context.
2. NEVER invent company policies, refund amounts, processing timelines, warranty periods, or guarantees not stated in the context.
3. If the provided context does NOT contain enough information or if the issue requires manual staff intervention (e.g. account review, fraud investigation, policy exception), you MUST:
   - State clearly that the available documentation does not contain sufficient details to resolve the request.
   - Recommend escalation to the support team.
   - Set "needs_escalation": true in the output.
4. If the context explicitly answers the issue, provide clear, step-by-step guidance and set "needs_escalation": false.
5. In "source_chunk_ids", list the numeric indices of the specific context sources you used to construct the answer.

Required JSON Output Schema:
{
    "answer": "<Helpful, professional customer response grounded strictly in the provided context>",
    "confidence": <Estimated confidence score float between 0.00 and 1.00>,
    "needs_escalation": <true if context is insufficient or manual action required, false otherwise>,
    "reason": "<A concise 1-2 sentence explanation of why this answer was given and how sources were applied>",
    "source_chunk_ids": [<List of integer source numbers used, e.g. [1, 2]>]
}

Output ONLY the raw JSON object. Do not wrap in markdown backticks (like ```json) or add commentary."""


def build_rag_user_prompt(
    subject: str,
    description: str,
    product_service: str,
    reference_id: str,
    chunks: List[RetrievedChunk],
) -> str:
    """Format the customer complaint alongside retrieved knowledge chunks for the LLM."""
    context_sections = []
    for i, c in enumerate(chunks, 1):
        page_info = f" (Page {c.page_number})" if c.page_number else ""
        header = f"--- SOURCE [{i}]: {c.document_title}{page_info} | Category: {c.category} ---"
        context_sections.append(f"{header}\n{c.content}\n")

    context_text = "\n".join(context_sections) if context_sections else "NO KNOWLEDGE BASE CONTEXT AVAILABLE."

    prompt = f"""=== KNOWLEDGE BASE CONTEXT ===
{context_text}
=== END CONTEXT ===

=== CUSTOMER COMPLAINT ===
Subject: {subject}
Product / Service: {product_service or 'Not specified'}
Reference ID: {reference_id or 'None'}
Description:
{description}
=== END COMPLAINT ===

Please generate the structured resolution following all grounding and escalation rules."""

    return prompt
