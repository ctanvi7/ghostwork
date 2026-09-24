"""Freshdesk REST API v2 integration service."""

import logging
import re
from datetime import datetime
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth

from config import Config
from schemas.freshdesk_responses import FreshDeskTicket

logger = logging.getLogger(__name__)

# Timeouts (seconds)
CONNECT_TIMEOUT = 3
READ_TIMEOUT = 10


class FreshDeskUnavailableError(Exception):
    """Raised when Freshdesk is not configured or unavailable."""
    pass


class FreshDeskError(Exception):
    """Raised when Freshdesk API returns an error."""
    pass


def get_ticket(ticket_id: int) -> Optional[FreshDeskTicket]:
    """
    Fetch a ticket from Freshdesk REST API v2.

    Args:
        ticket_id: Freshdesk ticket ID

    Returns:
        FreshDeskTicket if successful and configured, None if not configured

    Raises:
        FreshDeskUnavailableError: If Freshdesk not configured
        FreshDeskError: If API call fails
    """
    # Check configuration
    if not Config.FRESHDESK_DOMAIN or not Config.FRESHDESK_API_KEY:
        logger.warning("Freshdesk not configured (missing FRESHDESK_DOMAIN or FRESHDESK_API_KEY)")
        raise FreshDeskUnavailableError("Freshdesk credentials not configured")

    url = f"https://{Config.FRESHDESK_DOMAIN}.freshdesk.com/api/v2/tickets/{ticket_id}"

    try:
        logger.info(f"Fetching ticket {ticket_id} from Freshdesk", extra={
            "freshdesk_domain": Config.FRESHDESK_DOMAIN,
            "ticket_id": ticket_id
        })

        response = requests.get(
            url,
            auth=HTTPBasicAuth(Config.FRESHDESK_API_KEY, "X"),
            headers={"Content-Type": "application/json"},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )

        # Check for authentication/authorization errors
        if response.status_code == 401:
            logger.error("Freshdesk authentication failed (401)")
            raise FreshDeskError("Authentication failed: invalid API key or domain")

        if response.status_code == 403:
            logger.error("Freshdesk authorization failed (403)")
            raise FreshDeskError("Authorization failed: insufficient permissions")

        # Check for not found
        if response.status_code == 404:
            logger.warning(f"Ticket {ticket_id} not found on Freshdesk (404)")
            raise FreshDeskError(f"Ticket {ticket_id} not found")

        # Check for server errors
        if response.status_code >= 500:
            logger.error(f"Freshdesk server error ({response.status_code})")
            raise FreshDeskError(f"Freshdesk server error: {response.status_code}")

        # Check for other errors
        if not response.ok:
            logger.error(f"Freshdesk API error ({response.status_code}): {response.text[:200]}")
            raise FreshDeskError(f"API error: {response.status_code}")

        # Parse response
        data = response.json()
        logger.info(f"Successfully fetched ticket {ticket_id} from Freshdesk")

        return _normalize_ticket(data)

    except requests.Timeout as e:
        logger.error(f"Freshdesk API timeout for ticket {ticket_id}")
        raise FreshDeskError("Freshdesk API timeout (network too slow)") from e
    except requests.ConnectionError as e:
        logger.error(f"Freshdesk connection error for ticket {ticket_id}")
        raise FreshDeskError("Freshdesk connection error (network unavailable)") from e
    except requests.RequestException as e:
        logger.error(f"Freshdesk request failed: {str(e)[:100]}")
        raise FreshDeskError(f"Request failed: {str(e)[:100]}") from e


def _normalize_ticket(raw_response: dict) -> FreshDeskTicket:
    """
    Normalize Freshdesk API response to internal ticket structure.

    Args:
        raw_response: Raw JSON from Freshdesk API

    Returns:
        FreshDeskTicket with extracted fields
    """
    # Extract basic fields
    ticket_id = raw_response.get("id")
    subject = raw_response.get("subject", "")
    description_text = raw_response.get("description", "")
    requester_id = raw_response.get("requester_id")
    status = raw_response.get("status_name")  # "Open", "Pending", etc.
    priority = raw_response.get("priority")  # 1=Low, 2=Medium, 3=High, 4=Urgent

    # Extract requester name from responder object if available
    requester_name = None
    if raw_response.get("requester"):
        requester_name = raw_response["requester"].get("name")

    # Parse timestamp
    created_at = None
    created_at_str = raw_response.get("created_at")
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    # Extract custom fields
    custom_fields = raw_response.get("custom_fields", {})
    if isinstance(custom_fields, dict):
        # Normalize custom field names (remove cf_ prefix for internal use)
        normalized_custom = {}
        for key, value in custom_fields.items():
            normalized_custom[key] = value
        custom_fields = normalized_custom

    return FreshDeskTicket(
        ticket_id=ticket_id,
        subject=subject,
        description_text=description_text,
        requester_id=requester_id,
        requester_name=requester_name,
        status=status,
        priority=priority,
        created_at=created_at,
        custom_fields=custom_fields,
        raw_response=raw_response
    )


def extract_refund_amount(ticket: FreshDeskTicket) -> Optional[float]:
    """
    Extract refund amount from Freshdesk ticket.

    Tries custom field first, then falls back to regex on description.

    Args:
        ticket: Freshdesk ticket

    Returns:
        Refund amount as float, or None if not found
    """
    # Try custom field first
    cf_refund_amount = ticket.custom_fields.get("cf_refund_amount")
    if cf_refund_amount is not None:
        try:
            return float(cf_refund_amount)
        except (ValueError, TypeError):
            pass

    # Fallback: regex on description and subject
    text = f"{ticket.subject} {ticket.description_text}".lower()

    # Look for patterns like ₹32000 or 32000
    amount_matches = re.findall(r'[\₹]?\s*(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)', text)
    if amount_matches:
        try:
            amounts = [float(m.replace(",", "")) for m in amount_matches]
            return max(amounts) if amounts else None
        except ValueError:
            pass

    return None


def extract_invoice_id(ticket: FreshDeskTicket) -> Optional[str]:
    """
    Extract invoice ID from Freshdesk ticket.

    Tries custom field first, then falls back to regex on description.

    Args:
        ticket: Freshdesk ticket

    Returns:
        Invoice ID as string, or None if not found
    """
    # Try custom field first
    cf_invoice_id = ticket.custom_fields.get("cf_invoice_id")
    if cf_invoice_id:
        return str(cf_invoice_id)

    # Fallback: regex on description and subject
    text = f"{ticket.subject} {ticket.description_text}"

    # Look for patterns like INV-88421 or invoice 88421
    invoice_matches = re.findall(r'INV[_-]?(\d{3,})', text, re.IGNORECASE)
    if invoice_matches:
        return f"INV-{invoice_matches[0]}"

    return None
