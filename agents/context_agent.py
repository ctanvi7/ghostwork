"""Context agent: extracts structured context from ticket using Claude."""

import logging
from typing import Any, Dict, Optional

from services.claude_service import extract_ticket_context

logger = logging.getLogger(__name__)


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extract structured context from a support ticket.

    Uses Claude to interpret ticket text and extract relevant information.
    Falls back to deterministic extraction if Claude is unavailable.

    Returns:
        - status: "SUCCESS" (always succeeds, even with fallback)
        - result: extracted TicketContext as dict
    """
    try:
        # Get ticket text from execution context
        # This would normally come from Freshdesk, but we use placeholder for now
        ticket_text = execution.get("ticket_text") or "Support ticket request"

        # Extract structured context using Claude (with graceful fallback)
        ticket_context = extract_ticket_context(ticket_text)

        logger.info(
            f"Context extracted: category={ticket_context.issue_category}, "
            f"confidence={ticket_context.confidence_score}"
        )

        return {
            "status": "SUCCESS",
            "result": {
                "reason": "Context extracted",
                "context": ticket_context.model_dump(),
                "confidence": ticket_context.confidence_score
            }
        }

    except Exception as e:
        logger.error(f"Context extraction failed: {e}")
        # Return success with minimal context to allow workflow to continue
        return {
            "status": "SUCCESS",
            "result": {
                "reason": "Context extraction failed, workflow continues",
                "context": {
                    "issue_category": "support",
                    "issue_summary": "Support request",
                    "confidence_score": 0.0
                },
                "error": str(e)
            }
        }
