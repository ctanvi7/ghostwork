"""Freshdesk integration service with MCP (primary) and REST (fallback) support."""

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

# Track which provider was used for diagnostics
_last_provider_used = None


def get_last_provider_used() -> Optional[str]:
    """Return which provider was last used (mcp or rest)."""
    return _last_provider_used


class FreshDeskUnavailableError(Exception):
    """Raised when Freshdesk is not configured or unavailable."""
    pass


class FreshDeskError(Exception):
    """Raised when Freshdesk API returns an error."""
    pass


def _use_mcp_provider() -> bool:
    """True if MCP is the selected provider AND has its runtime config."""
    if Config.FRESHDESK_PROVIDER != "mcp":
        return False
    return bool(Config.MCP_FRESHDESK_URL and Config.MCP_FRESHDESK_AUTH_TOKEN)


def _is_any_provider_configured() -> bool:
    """True if EITHER MCP or REST has the runtime config it needs."""
    mcp_ok = bool(Config.MCP_FRESHDESK_URL and Config.MCP_FRESHDESK_AUTH_TOKEN)
    rest_ok = bool(Config.FRESHDESK_DOMAIN and Config.FRESHDESK_API_KEY)
    return mcp_ok or rest_ok


def _set_provider(name: str) -> None:
    global _last_provider_used
    _last_provider_used = name


def _dispatch(operation: str, mcp_call, rest_call, allow_rest_fallback: Optional[bool]):
    """Run one Freshdesk operation on the selected provider.

    provider=mcp: use MCP. REST is used only if MCP is unconfigured or fails AND
    fallback is allowed (explicit argument, else FRESHDESK_ALLOW_REST_FALLBACK).
    Otherwise the MCP error propagates, so REST can never silently mask it.
    provider=rest: use REST.
    """
    fallback = Config.FRESHDESK_ALLOW_REST_FALLBACK if allow_rest_fallback is None else allow_rest_fallback

    if Config.FRESHDESK_PROVIDER == "mcp":
        if _use_mcp_provider():
            _set_provider("mcp")
            try:
                return mcp_call()
            except (FreshDeskError, FreshDeskUnavailableError) as e:
                if not fallback:
                    raise
                logger.warning(f"MCP {operation} failed, falling back to REST: {e}")
        elif not fallback:
            raise FreshDeskUnavailableError("Freshdesk MCP selected but not configured")

    _set_provider("rest")
    return rest_call()


def _mcp_verify_note(
    ticket_id: int, expected_note_id: Optional[int] = None,
    execution_reference: Optional[str] = None
) -> dict:
    """Independently read back ticket conversations via MCP and look for the note."""
    from services import freshdesk_mcp_adapter

    conversations = freshdesk_mcp_adapter.fetch_ticket_conversations(ticket_id)

    if expected_note_id:
        for conv in conversations:
            if str(conv.get("id")) == str(expected_note_id):
                logger.info(f"Verified note {expected_note_id} on ticket {ticket_id} via MCP")
                return {
                    "verified": True,
                    "matched_note_id": expected_note_id,
                    "ticket_id": ticket_id,
                    "reason": f"Note {expected_note_id} found",
                    "status": "verified"
                }

    if execution_reference:
        for conv in conversations:
            body = f"{conv.get('body') or ''} {conv.get('body_text') or ''}".lower()
            if execution_reference.lower() in body:
                matched_note_id = conv.get("id")
                logger.info(f"Verified execution reference on ticket {ticket_id} via MCP")
                return {
                    "verified": True,
                    "matched_note_id": matched_note_id,
                    "ticket_id": ticket_id,
                    "reason": f"Execution reference found in note {matched_note_id}",
                    "status": "verified"
                }

    return {
        "verified": False,
        "matched_note_id": None,
        "ticket_id": ticket_id,
        "expected_note_id": expected_note_id,
        "reason": f"Note not found (expected: {expected_note_id}, ref: {execution_reference})",
        "status": "verification_failed"
    }


def get_ticket(ticket_id: int, allow_rest_fallback: Optional[bool] = None) -> Optional[FreshDeskTicket]:
    """
    Fetch a ticket from Freshdesk (MCP primary, REST fallback only if allowed).

    Args:
        ticket_id: Freshdesk ticket ID
        allow_rest_fallback: None uses Config.FRESHDESK_ALLOW_REST_FALLBACK.
            False forces MCP errors to propagate instead of trying REST.

    Raises:
        FreshDeskUnavailableError: If Freshdesk is not configured
        FreshDeskError: If the API call fails
    """
    if not _is_any_provider_configured():
        logger.warning("Freshdesk not configured (no MCP or REST credentials present)")
        raise FreshDeskUnavailableError("Freshdesk credentials not configured")

    from services import freshdesk_mcp_adapter

    return _dispatch(
        "get_ticket",
        lambda: freshdesk_mcp_adapter.fetch_ticket(ticket_id),
        lambda: _get_ticket_rest(ticket_id),
        allow_rest_fallback,
    )


# Freshdesk statuses: 2=Open, 3=Pending, 4=Resolved, 5=Closed.
# Discovery only acts on unresolved work, so resolved/closed tickets are filtered
# out by Freshdesk itself (in the query), not after download.
UNRESOLVED_TICKETS_QUERY = "status:2 OR status:3"


def list_unresolved_tickets(allow_rest_fallback: Optional[bool] = None) -> list:
    """
    List Open and Pending tickets as raw Freshdesk dicts (MCP primary, REST fallback only if allowed).

    Raises:
        FreshDeskUnavailableError: If Freshdesk is not configured
        FreshDeskError: If the API call fails
    """
    if not _is_any_provider_configured():
        raise FreshDeskUnavailableError("Freshdesk credentials not configured")

    from services import freshdesk_mcp_adapter

    return _dispatch(
        "list_unresolved_tickets",
        lambda: freshdesk_mcp_adapter.search_tickets(UNRESOLVED_TICKETS_QUERY),
        lambda: _search_tickets_rest(UNRESOLVED_TICKETS_QUERY),
        allow_rest_fallback,
    )


def _search_tickets_rest(query: str, max_pages: int = 10) -> list:
    """Search tickets via Freshdesk REST API v2 (30 per page, at most 10 pages)."""
    url = f"https://{Config.freshdesk_rest_host()}/api/v2/search/tickets"
    tickets = []
    for page in range(1, max_pages + 1):
        try:
            response = requests.get(
                url,
                auth=HTTPBasicAuth(Config.FRESHDESK_API_KEY, "X"),
                headers={"Content-Type": "application/json"},
                # The REST search API requires the query wrapped in double quotes.
                params={"query": f'"{query}"', "page": page},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
            )
        except requests.RequestException as e:
            logger.error(f"Freshdesk ticket search failed: {str(e)[:100]}")
            raise FreshDeskError(f"Request failed: {str(e)[:100]}") from e

        if response.status_code in (401, 403):
            raise FreshDeskError(f"Freshdesk rejected credentials ({response.status_code})")
        if not response.ok:
            raise FreshDeskError(f"API error: {response.status_code}")

        data = response.json()
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise FreshDeskError("Freshdesk returned tickets in an unrecognized format")

        tickets.extend(results)
        if len(results) < 30:
            break
    return tickets


def _get_ticket_rest(ticket_id: int) -> Optional[FreshDeskTicket]:
    """Fetch a ticket from Freshdesk REST API v2."""
    url = f"https://{Config.freshdesk_rest_host()}/api/v2/tickets/{ticket_id}"

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
    cf_refund_amount = ticket.custom_fields.get(Config.FRESHDESK_REFUND_AMOUNT_FIELD)
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


def add_note(ticket_id: int, body: str, allow_rest_fallback: Optional[bool] = None) -> dict:
    """
    Add a note to a Freshdesk ticket (MCP primary, REST fallback only if allowed).

    Args:
        ticket_id: Freshdesk ticket ID
        body: Note content (text)

    Returns:
        Dict with keys: status ("success" or "error"), note_id (if success), error_message

    Raises:
        FreshDeskUnavailableError: If Freshdesk not configured
        FreshDeskError: If API call fails
    """
    # Check configuration (either provider satisfies this gate)
    if not _is_any_provider_configured():
        logger.warning("Freshdesk not configured for write-back")
        raise FreshDeskUnavailableError("Freshdesk credentials not configured")

    from services import freshdesk_mcp_adapter

    return _dispatch(
        "add_note",
        lambda: freshdesk_mcp_adapter.add_ticket_note(ticket_id, body),
        lambda: _add_note_rest(ticket_id, body),
        allow_rest_fallback,
    )


def get_agent_contact(agent_id: int, allow_rest_fallback: Optional[bool] = None) -> dict:
    """
    Return {"agent_id", "name", "mobile", "phone", "active"} for a Freshdesk agent.

    Raises:
        FreshDeskUnavailableError: If Freshdesk not configured
        FreshDeskError: If API call fails
    """
    if not _is_any_provider_configured():
        raise FreshDeskUnavailableError("Freshdesk credentials not configured")

    from services import freshdesk_mcp_adapter

    agent = _dispatch(
        "get_agent_contact",
        lambda: freshdesk_mcp_adapter.fetch_agent(agent_id),
        lambda: _get_agent_rest(agent_id),
        allow_rest_fallback,
    )
    contact = agent.get("contact") or {}
    return {
        "agent_id": agent.get("id"),
        "name": contact.get("name"),
        "mobile": contact.get("mobile"),
        "phone": contact.get("phone"),
        "active": contact.get("active", True),
    }


def _get_agent_rest(agent_id: int) -> dict:
    """Fetch a Freshdesk agent using REST API v2."""
    url = f"https://{Config.freshdesk_rest_host()}/api/v2/agents/{agent_id}"
    try:
        response = requests.get(
            url,
            auth=HTTPBasicAuth(Config.FRESHDESK_API_KEY, "X"),
            headers={"Content-Type": "application/json"},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )
    except requests.RequestException as e:
        logger.error(f"Freshdesk agent request failed: {str(e)[:100]}")
        raise FreshDeskError(f"Request failed: {str(e)[:100]}") from e

    if response.status_code in (401, 403):
        raise FreshDeskError(f"Freshdesk rejected credentials ({response.status_code})")
    if response.status_code == 404:
        raise FreshDeskError(f"Agent {agent_id} not found")
    if not response.ok:
        raise FreshDeskError(f"API error: {response.status_code}")

    data = response.json()
    if not isinstance(data, dict):
        raise FreshDeskError("Freshdesk returned agent in an unrecognized format")
    return data


def update_ticket_status(ticket_id: int, status: int, allow_rest_fallback: Optional[bool] = None) -> dict:
    """
    Set a ticket's status (MCP primary, REST fallback only if allowed). 5 = Closed.

    Raises:
        FreshDeskUnavailableError: If Freshdesk not configured
        FreshDeskError: If API call fails
    """
    if not _is_any_provider_configured():
        raise FreshDeskUnavailableError("Freshdesk credentials not configured")

    from services import freshdesk_mcp_adapter

    return _dispatch(
        "update_ticket_status",
        lambda: freshdesk_mcp_adapter.update_ticket_status(ticket_id, status),
        lambda: _update_ticket_status_rest(ticket_id, status),
        allow_rest_fallback,
    )


def _update_ticket_status_rest(ticket_id: int, status: int) -> dict:
    """Set a ticket's status using REST API v2 (PUT /tickets/{id})."""
    url = f"https://{Config.freshdesk_rest_host()}/api/v2/tickets/{ticket_id}"
    try:
        response = requests.put(
            url,
            auth=HTTPBasicAuth(Config.FRESHDESK_API_KEY, "X"),
            headers={"Content-Type": "application/json"},
            json={"status": status},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )
    except requests.RequestException as e:
        logger.error(f"Freshdesk status update failed for ticket {ticket_id}: {str(e)[:100]}")
        raise FreshDeskError(f"Request failed: {str(e)[:100]}") from e

    if response.status_code in (401, 403):
        raise FreshDeskError(f"Freshdesk rejected credentials ({response.status_code})")
    if response.status_code == 404:
        raise FreshDeskError(f"Ticket {ticket_id} not found")
    if not response.ok:
        # 400 usually means a field Freshdesk requires on closure is empty.
        logger.error(f"Freshdesk status update error ({response.status_code}): {response.text[:200]}")
        raise FreshDeskError(f"API error {response.status_code}: {response.text[:120]}")

    return {"status": "success", "ticket_id": ticket_id}


def _add_note_rest(ticket_id: int, body: str) -> dict:
    """Add a note to a Freshdesk ticket using REST API."""
    url = f"https://{Config.freshdesk_rest_host()}/api/v2/tickets/{ticket_id}/notes"

    try:
        logger.info(f"Adding note to ticket {ticket_id}", extra={
            "freshdesk_domain": Config.FRESHDESK_DOMAIN,
            "ticket_id": ticket_id
        })

        response = requests.post(
            url,
            auth=HTTPBasicAuth(Config.FRESHDESK_API_KEY, "X"),
            headers={"Content-Type": "application/json"},
            json={"body": body},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )

        # Check for authentication/authorization errors
        if response.status_code == 401:
            logger.error("Freshdesk authentication failed (401) on note creation")
            raise FreshDeskError("Authentication failed: invalid API key or domain")

        if response.status_code == 403:
            logger.error("Freshdesk authorization failed (403) on note creation")
            raise FreshDeskError("Authorization failed: insufficient permissions")

        # Check for not found
        if response.status_code == 404:
            logger.warning(f"Ticket {ticket_id} not found on Freshdesk (404)")
            raise FreshDeskError(f"Ticket {ticket_id} not found")

        # Check for server errors
        if response.status_code >= 500:
            logger.error(f"Freshdesk server error ({response.status_code}) on note creation")
            raise FreshDeskError(f"Freshdesk server error: {response.status_code}")

        # Check for other errors
        if not response.ok:
            logger.error(f"Freshdesk API error ({response.status_code}) on note creation: {response.text[:200]}")
            raise FreshDeskError(f"API error: {response.status_code}")

        # Parse response
        data = response.json()
        note_id = data.get("id")
        logger.info(f"Successfully added note {note_id} to ticket {ticket_id}")

        return {
            "status": "success",
            "note_id": note_id,
            "ticket_id": ticket_id
        }

    except requests.Timeout as e:
        logger.error(f"Freshdesk API timeout for ticket {ticket_id}")
        raise FreshDeskError("Freshdesk API timeout (network too slow)") from e
    except requests.ConnectionError as e:
        logger.error(f"Freshdesk connection error for ticket {ticket_id}")
        raise FreshDeskError("Freshdesk connection error (network unavailable)") from e
    except requests.RequestException as e:
        logger.error(f"Freshdesk request failed: {str(e)[:100]}")
        raise FreshDeskError(f"Request failed: {str(e)[:100]}") from e


def verify_note_exists(ticket_id: int, expected_note_id: Optional[int] = None,
                       execution_reference: Optional[str] = None,
                       allow_rest_fallback: Optional[bool] = None) -> dict:
    """
    Verify that a note exists on a Freshdesk ticket (MCP primary, REST fallback only if allowed).

    Fetches ticket conversations and checks if the expected note is present.
    Matches by note_id if provided, otherwise searches for execution reference.

    Args:
        ticket_id: Freshdesk ticket ID
        expected_note_id: Note ID to verify (preferred match)
        execution_reference: Execution marker to search for (fallback match)

    Returns:
        Dict with keys: verified (bool), matched_note_id (if found), reason, status

    Raises:
        FreshDeskUnavailableError: If Freshdesk not configured
        FreshDeskError: If API call fails
    """
    # Check configuration (either provider satisfies this gate)
    if not _is_any_provider_configured():
        logger.warning("Freshdesk not configured for verification")
        raise FreshDeskUnavailableError("Freshdesk credentials not configured")

    return _dispatch(
        "verify_note_exists",
        lambda: _mcp_verify_note(ticket_id, expected_note_id, execution_reference),
        lambda: _verify_note_exists_rest(ticket_id, expected_note_id, execution_reference),
        allow_rest_fallback,
    )


def _verify_note_exists_rest(ticket_id: int, expected_note_id: Optional[int] = None,
                              execution_reference: Optional[str] = None) -> dict:
    """Verify note exists using REST API."""
    # Fetch ticket with conversations
    url = f"https://{Config.freshdesk_rest_host()}/api/v2/tickets/{ticket_id}?include=conversations"

    try:
        logger.info(f"Verifying note on ticket {ticket_id}", extra={
            "ticket_id": ticket_id,
            "expected_note_id": expected_note_id
        })

        response = requests.get(
            url,
            auth=HTTPBasicAuth(Config.FRESHDESK_API_KEY, "X"),
            headers={"Content-Type": "application/json"},
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
        )

        # Check for authentication/authorization errors
        if response.status_code == 401:
            logger.error("Freshdesk authentication failed (401) on verification")
            raise FreshDeskError("Authentication failed: invalid API key or domain")

        if response.status_code == 403:
            logger.error("Freshdesk authorization failed (403) on verification")
            raise FreshDeskError("Authorization failed: insufficient permissions")

        # Check for not found
        if response.status_code == 404:
            logger.warning(f"Ticket {ticket_id} not found on Freshdesk (404)")
            raise FreshDeskError(f"Ticket {ticket_id} not found")

        # Check for server errors
        if response.status_code >= 500:
            logger.error(f"Freshdesk server error ({response.status_code}) on verification")
            raise FreshDeskError(f"Freshdesk server error: {response.status_code}")

        # Check for other errors
        if not response.ok:
            logger.error(f"Freshdesk API error ({response.status_code}) on verification: {response.text[:200]}")
            raise FreshDeskError(f"API error: {response.status_code}")

        # Parse response
        data = response.json()
        conversations = data.get("conversations", [])

        # Check if expected note exists
        matched_note_id = None

        # First, try to match by note_id if provided
        if expected_note_id:
            for conv in conversations:
                if conv.get("id") == expected_note_id:
                    matched_note_id = expected_note_id
                    logger.info(f"Verified note {expected_note_id} on ticket {ticket_id}")
                    return {
                        "verified": True,
                        "matched_note_id": matched_note_id,
                        "ticket_id": ticket_id,
                        "reason": f"Note {expected_note_id} found",
                        "status": "verified"
                    }

        # Second, try to match by execution reference in body
        if execution_reference:
            for conv in conversations:
                body = (conv.get("body") or "").lower()
                if execution_reference.lower() in body:
                    matched_note_id = conv.get("id")
                    logger.info(f"Verified execution reference on ticket {ticket_id}, note {matched_note_id}")
                    return {
                        "verified": True,
                        "matched_note_id": matched_note_id,
                        "ticket_id": ticket_id,
                        "reason": f"Execution reference found in note {matched_note_id}",
                        "status": "verified"
                    }

        # No match found
        logger.warning(f"Verification failed: no matching note on ticket {ticket_id}")
        return {
            "verified": False,
            "matched_note_id": None,
            "ticket_id": ticket_id,
            "expected_note_id": expected_note_id,
            "reason": f"Note not found (expected: {expected_note_id}, ref: {execution_reference})",
            "status": "verification_failed"
        }

    except requests.Timeout as e:
        logger.error(f"Freshdesk API timeout during verification for ticket {ticket_id}")
        raise FreshDeskError("Freshdesk API timeout (network too slow)") from e
    except requests.ConnectionError as e:
        logger.error(f"Freshdesk connection error during verification for ticket {ticket_id}")
        raise FreshDeskError("Freshdesk connection error (network unavailable)") from e
    except requests.RequestException as e:
        logger.error(f"Freshdesk verification request failed: {str(e)[:100]}")
        raise FreshDeskError(f"Request failed: {str(e)[:100]}") from e
