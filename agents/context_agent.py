"""Context agent: extracts structured context from ticket using Freshdesk + Claude."""

import logging
from typing import Any, Dict, Optional

from services.claude_service import extract_ticket_context
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    extract_invoice_id,
    extract_refund_amount,
    get_ticket,
)

logger = logging.getLogger(__name__)


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Extract structured context from a support ticket.

    1. Attempts to fetch ticket from Freshdesk (if configured)
    2. Uses Claude to interpret ticket text
    3. Falls back to deterministic extraction if unavailable

    Returns:
        - status: "SUCCESS" (always succeeds, even with fallback)
        - result: extracted TicketContext as dict with source tracking
    """
    try:
        # Step 1: Try to fetch from Freshdesk
        ticket_id = execution.get("ticket_id")
        freshdesk_ticket = None
        ticket_text = execution.get("ticket_text", "Support ticket request")
        source = "fallback"

        if ticket_id:
            try:
                freshdesk_ticket = get_ticket(ticket_id)
                # Combine subject and description for Claude
                ticket_text = f"Subject: {freshdesk_ticket.subject}\n\n{freshdesk_ticket.description_text}"
                source = "freshdesk"

                logger.info(f"Fetched ticket {ticket_id} from Freshdesk", extra={
                    "ticket_id": ticket_id,
                    "source": source
                })

            except FreshDeskUnavailableError:
                logger.info(f"Freshdesk not configured, using fallback for ticket {ticket_id}")
                source = "fallback"
            except FreshDeskError as e:
                logger.warning(f"Freshdesk fetch failed for ticket {ticket_id}: {e}, using fallback")
                source = "fallback_error"

        # Step 2: Extract structured context using Claude
        ticket_context = extract_ticket_context(ticket_text)

        # Step 3: Enrich with Freshdesk data if available
        context_dict = ticket_context.model_dump()
        if freshdesk_ticket:
            # Add Freshdesk-extracted amounts
            refund_amount = extract_refund_amount(freshdesk_ticket)
            invoice_id = extract_invoice_id(freshdesk_ticket)

            if refund_amount is not None:
                context_dict["refund_amount_mentioned"] = refund_amount
            if invoice_id is not None:
                context_dict["invoice_id"] = invoice_id

            # Add requester info if available
            if freshdesk_ticket.requester_name:
                context_dict["customer_name"] = freshdesk_ticket.requester_name

        logger.info(
            f"Context extracted: category={ticket_context.issue_category}, "
            f"confidence={ticket_context.confidence_score}, source={source}"
        )

        return {
            "status": "SUCCESS",
            "result": {
                "reason": "Context extracted from ticket",
                "context": context_dict,
                "confidence": ticket_context.confidence_score,
                "source": source
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
                "source": "fallback_error",
                "error": str(e)
            }
        }
