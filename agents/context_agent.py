"""Context agent: extracts structured context from ticket using Freshdesk + Claude."""

import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from config import Config
from services.claude_service import extract_ticket_context
from services.freshdesk_service import (
    FreshDeskError,
    FreshDeskUnavailableError,
    extract_invoice_id,
    extract_refund_amount,
    get_last_provider_used,
    get_ticket,
)

logger = logging.getLogger(__name__)


def _deterministic_refund_amount(freshdesk_ticket) -> Optional[Decimal]:
    """Refund amount from the structured Freshdesk custom field only (never regex/LLM)."""
    value = (freshdesk_ticket.custom_fields or {}).get(Config.FRESHDESK_REFUND_AMOUNT_FIELD)
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _apply_refund_amount(execution: Dict[str, Any], freshdesk_ticket) -> str:
    """Fill a missing execution refund_amount from Freshdesk; return where the amount came from."""
    if execution.get("refund_amount") is not None:
        return "request"
    amount = _deterministic_refund_amount(freshdesk_ticket)
    if amount is None:
        return "missing"
    execution["refund_amount"] = float(amount)
    if execution.get("id"):
        from services.supabase_service import get_service
        get_service().update_execution(execution["id"], refund_amount=float(amount))
    return "freshdesk_custom_field"


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
        provider = None
        freshdesk_error = None

        if ticket_id:
            try:
                freshdesk_ticket = get_ticket(ticket_id)
                # Combine subject and description for Claude
                ticket_text = f"Subject: {freshdesk_ticket.subject}\n\n{freshdesk_ticket.description_text}"
                source = "freshdesk"
                provider = get_last_provider_used()

                logger.info(f"Fetched ticket {ticket_id} from Freshdesk", extra={
                    "ticket_id": ticket_id,
                    "source": source,
                    "provider": provider,
                })

            except FreshDeskUnavailableError:
                logger.info(f"Freshdesk not configured, using fallback for ticket {ticket_id}")
                source = "fallback"
            except FreshDeskError as e:
                logger.warning(f"Freshdesk fetch failed for ticket {ticket_id}: {e}, using fallback")
                source = "fallback_error"
                freshdesk_error = str(e)[:120]

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

        result = {
            "reason": "Context extracted from ticket",
            "context": context_dict,
            "confidence": ticket_context.confidence_score,
            "source": source,
        }

        if freshdesk_ticket:
            result["reason"] = f"Context extracted from Freshdesk ticket #{freshdesk_ticket.ticket_id}"
            result["provider"] = provider
            result["refund_amount_source"] = _apply_refund_amount(execution, freshdesk_ticket)
            # Only non-personal ticket metadata, so the UI can prove the real source.
            result["ticket"] = {
                "ticket_id": freshdesk_ticket.ticket_id,
                "subject": freshdesk_ticket.subject,
                "priority": freshdesk_ticket.priority,
                "status": (freshdesk_ticket.raw_response or {}).get("status"),
                "url": Config.freshdesk_ticket_url(freshdesk_ticket.ticket_id),
            }
        elif freshdesk_error:
            result["freshdesk_error"] = freshdesk_error

        return {"status": "SUCCESS", "result": result}

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
