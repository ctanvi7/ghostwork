"""Freshdesk MCP (Model Context Protocol) runtime adapter.

Implements the REAL MCP wire protocol: JSON-RPC 2.0 over HTTP, using the
"tools/call" method against a Streamable-HTTP MCP server. This is
independent of Claude Code — the Flask process makes its own HTTP calls.

Wire protocol (verified against the live Freshdesk MCP server):
  1. POST {MCP_FRESHDESK_URL} with a JSON-RPC "tools/call" request for the
     "start_conversation" tool. Response is a JSON-RPC envelope whose
     result.content[0].text is itself a JSON string containing
     {"conversation_id": "..."}.
  2. Every subsequent tools/call must include that conversation_id in its
     arguments.
  3. Tool results are always double-encoded: the outer JSON-RPC envelope,
     then result.content[0].text is a JSON string with the real payload
     (e.g. {"status": "OK", "data": {...}}).

MCP is the primary Freshdesk transport. REST remains the fallback.
"""

import json
import logging
from typing import Optional

import requests

from config import Config
from schemas.freshdesk_responses import FreshDeskTicket
from services.freshdesk_service import FreshDeskError, FreshDeskUnavailableError

logger = logging.getLogger(__name__)

# Timeouts (seconds)
CONNECT_TIMEOUT = 3
READ_TIMEOUT = 10

# MCP session is per-process; the server issues one conversation_id that
# must be reused for every subsequent tools/call.
_conversation_id: Optional[str] = None


class FreshDeskMCPError(FreshDeskError):
    """Raised when an MCP Freshdesk operation fails."""

    pass


class FreshDeskMCPUnavailableError(FreshDeskUnavailableError):
    """Raised when MCP Freshdesk runtime configuration is missing."""

    pass


class FreshDeskMCPSessionError(FreshDeskMCPError):
    """The server rejected the conversation_id (expired or unknown session)."""

    pass


# Conversations come back oldest first, so a newly added note is on the last page.
CONVERSATIONS_PER_PAGE = 100  # server maximum
MAX_CONVERSATION_PAGES = 10


def _is_session_error(text: str) -> bool:
    """True if an MCP error message says the conversation/session is not valid."""
    text = (text or "").lower()
    if "conversation_id" in text:
        return True
    return ("conversation" in text or "session" in text) and any(
        word in text for word in ("expired", "invalid", "unknown")
    )


def reset_session() -> None:
    """Clear the cached MCP conversation_id (used by tests)."""
    global _conversation_id
    _conversation_id = None


def is_configured() -> bool:
    """True if the runtime env has what this adapter needs to call MCP."""
    return bool(Config.MCP_FRESHDESK_URL and Config.MCP_FRESHDESK_AUTH_TOKEN)


def _check_configured() -> None:
    if not is_configured():
        logger.warning(
            "MCP Freshdesk not configured (missing MCP_FRESHDESK_URL or MCP_FRESHDESK_AUTH_TOKEN)"
        )
        raise FreshDeskMCPUnavailableError("MCP Freshdesk not configured")


def _rpc_call(method: str, params: dict, request_id: int = 1) -> dict:
    """Send one JSON-RPC 2.0 request to the MCP server and return the parsed envelope."""
    _check_configured()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        # The value stored in MCP_FRESHDESK_AUTH_TOKEN is sent verbatim as the
        # Authorization header (it already includes any required prefix,
        # matching exactly what the MCP server issued).
        "Authorization": Config.MCP_FRESHDESK_AUTH_TOKEN,
    }
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}

    try:
        response = requests.post(
            Config.MCP_FRESHDESK_URL,
            json=payload,
            headers=headers,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.Timeout as e:
        raise FreshDeskMCPError("MCP API timeout (network too slow)") from e
    except requests.ConnectionError as e:
        raise FreshDeskMCPError("MCP connection error (network unavailable)") from e
    except requests.RequestException as e:
        raise FreshDeskMCPError(f"MCP request failed: {str(e)[:100]}") from e

    if response.status_code == 401:
        raise FreshDeskMCPError("MCP authentication failed: invalid token")
    if response.status_code == 403:
        raise FreshDeskMCPError("MCP authorization failed")
    if response.status_code >= 500:
        raise FreshDeskMCPError(f"MCP server error: {response.status_code}")
    if not response.ok:
        raise FreshDeskMCPError(f"MCP call failed: {response.status_code}")

    try:
        envelope = response.json()
    except json.JSONDecodeError as e:
        raise FreshDeskMCPError("MCP returned invalid JSON envelope") from e

    if "error" in envelope:
        if _is_session_error(str(envelope["error"])):
            raise FreshDeskMCPSessionError(f"MCP session rejected: {envelope['error']}")
        raise FreshDeskMCPError(f"MCP JSON-RPC error: {envelope['error']}")

    return envelope


def _call_tool(tool_name: str, arguments: dict) -> dict:
    """
    Call an MCP tool via tools/call and unwrap the double-encoded result.

    Returns the inner payload dict (e.g. {"status": "OK", "data": {...}}).
    """
    envelope = _rpc_call("tools/call", {"name": tool_name, "arguments": arguments})

    result = envelope.get("result", {})
    if result.get("isError"):
        content = result.get("content", [{}])
        message = content[0].get("text", "Unknown MCP tool error") if content else "Unknown MCP tool error"
        # The server wraps upstream Freshdesk errors as JSON, e.g. {"status_code": 404, ...}
        try:
            status_code = json.loads(message).get("status_code")
        except (json.JSONDecodeError, AttributeError):
            status_code = None
        if status_code == 404:
            raise FreshDeskMCPError(f"Not found in Freshdesk (tool '{tool_name}', HTTP 404)")
        if status_code in (401, 403):
            raise FreshDeskMCPError(f"Freshdesk rejected MCP credentials (HTTP {status_code})")
        if _is_session_error(message):
            raise FreshDeskMCPSessionError(f"MCP session rejected: {message[:200]}")
        raise FreshDeskMCPError(f"MCP tool '{tool_name}' error: {message[:200]}")

    content = result.get("content", [])
    if not content or "text" not in content[0]:
        raise FreshDeskMCPError(f"MCP tool '{tool_name}' returned no content")

    try:
        inner = json.loads(content[0]["text"])
    except json.JSONDecodeError as e:
        raise FreshDeskMCPError(f"MCP tool '{tool_name}' returned malformed inner JSON") from e

    return inner


def _get_conversation_id() -> str:
    """Get the cached MCP conversation_id, starting a session if needed."""
    global _conversation_id
    if _conversation_id:
        return _conversation_id

    inner = _call_tool(
        "start_conversation",
        {"_reasoning": "GhostWork Flask runtime initializing Freshdesk MCP session"},
    )
    conversation_id = inner.get("conversation_id")
    if not conversation_id:
        raise FreshDeskMCPError("MCP start_conversation did not return a conversation_id")

    _conversation_id = conversation_id
    logger.info("Started MCP conversation session")
    return _conversation_id


def _call_with_session(tool_name: str, arguments: dict) -> dict:
    """Call a tool, auto-injecting the session conversation_id.

    The conversation_id is cached for the whole process. If the server says it
    has expired, start one new conversation and retry once. That is safe even
    for writes: the server rejected the call before doing anything.
    """
    args = dict(arguments)
    for attempt in (1, 2):
        args["conversation_id"] = _get_conversation_id()
        try:
            inner = _call_tool(tool_name, args)
            if inner.get("status") not in ("OK", None) and _is_session_error(str(inner.get("message"))):
                raise FreshDeskMCPSessionError(f"MCP session rejected: {str(inner.get('message'))[:200]}")
            return inner
        except FreshDeskMCPSessionError:
            if attempt == 2:
                raise
            logger.info("MCP conversation expired; starting a new one")
            reset_session()


def fetch_ticket(ticket_id: int) -> Optional[FreshDeskTicket]:
    """
    Fetch a ticket using the real Freshdesk MCP runtime transport.

    Raises:
        FreshDeskMCPUnavailableError: If MCP not configured
        FreshDeskMCPError: If MCP call fails
    """
    _check_configured()

    logger.info(f"Fetching ticket {ticket_id} from Freshdesk MCP", extra={"ticket_id": ticket_id})

    try:
        inner = _call_with_session(
            "fetchTicket",
            {"id": ticket_id, "_reasoning": f"GhostWork context agent fetching ticket {ticket_id}"},
        )
    except FreshDeskMCPError as e:
        if "HTTP 404" in str(e):
            raise FreshDeskMCPError(
                f"Ticket {ticket_id} not found in Freshdesk (set FRESHDESK_DEMO_TICKET_ID to a real ticket)"
            ) from e
        raise

    if inner.get("error") or inner.get("status") not in ("OK", None):
        message = inner.get("message", "Unknown error")
        if "not found" in message.lower():
            raise FreshDeskMCPError(f"Ticket {ticket_id} not found")
        raise FreshDeskMCPError(f"MCP error: {message}")

    ticket_data = inner.get("data")
    if not ticket_data:
        raise FreshDeskMCPError("MCP returned empty ticket data")

    logger.info(f"Successfully fetched ticket {ticket_id} via MCP", extra={"ticket_id": ticket_id})
    ticket = _normalize_mcp_ticket(ticket_data)
    if not ticket.requester_name and ticket.requester_id:
        ticket.requester_name = _fetch_contact_name(ticket.requester_id)
    return ticket


def _fetch_contact_name(contact_id: int) -> Optional[str]:
    """Best-effort requester name lookup; the MCP ticket payload only has requester_id."""
    try:
        inner = _call_with_session(
            "fetchContact",
            {"id": contact_id, "_reasoning": "GhostWork context agent reading requester name"},
        )
    except FreshDeskError as e:
        logger.warning(f"MCP contact lookup failed for requester {contact_id}: {e}")
        return None
    data = inner.get("data")
    name = data.get("name") if isinstance(data, dict) else None
    return name if isinstance(name, str) and name.strip() else None


def search_tickets(query: str, max_pages: int = 10) -> list:
    """
    Search tickets via MCP with a Freshdesk filter query (e.g. "status:2 OR status:3").

    Freshdesk returns 30 results per page and allows at most 10 pages.

    Raises:
        FreshDeskMCPUnavailableError: If MCP not configured
        FreshDeskMCPError: If MCP call fails
    """
    _check_configured()

    tickets = []
    for page in range(1, max_pages + 1):
        inner = _call_with_session(
            "fetchSearchTickets",
            {"query": query, "page": page,
             "_reasoning": "GhostWork discovery reading unresolved ticket metadata"},
        )
        if inner.get("error"):
            raise FreshDeskMCPError(f"MCP error: {inner.get('message', 'Unknown error')}")

        # Live server returns {"data": {"results": [...], "total": N}}; accept bare too.
        data = inner.get("data", inner)
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise FreshDeskMCPError("MCP returned tickets in an unrecognized format")

        tickets.extend(results)
        if len(results) < 30:
            break
    return tickets


def fetch_ticket_conversations(ticket_id: int) -> list:
    """
    Fetch conversations (notes) for a ticket via MCP.

    Raises:
        FreshDeskMCPUnavailableError: If MCP not configured
        FreshDeskMCPError: If MCP call fails
    """
    _check_configured()

    logger.info(f"Fetching conversations for ticket {ticket_id} via MCP", extra={"ticket_id": ticket_id})

    conversations = []
    cursor = None
    for _ in range(MAX_CONVERSATION_PAGES):
        arguments = {
            "id": ticket_id,
            "per_page": CONVERSATIONS_PER_PAGE,
            "_reasoning": f"GhostWork verification agent reading ticket {ticket_id} conversations",
        }
        if cursor:
            arguments["cursor"] = cursor
        inner = _call_with_session("fetchTicketConversations", arguments)

        if inner.get("error"):
            raise FreshDeskMCPError(f"MCP error: {inner.get('message', 'Unknown error')}")

        # Live server returns {"results": [...], "nextCursor": "..."} at the top
        # level; accept a "data" wrapper too so a format change can't silently
        # empty the list.
        data = inner.get("data")
        if "results" in inner:
            page = inner["results"]
        elif isinstance(data, dict):
            page = data.get("results", [])
        elif isinstance(data, list):
            page = data
        else:
            raise FreshDeskMCPError("MCP returned conversations in an unrecognized format")
        if not isinstance(page, list):
            raise FreshDeskMCPError("MCP returned malformed conversations")
        conversations.extend(page)

        cursor = inner.get("nextCursor") or (data.get("nextCursor") if isinstance(data, dict) else None)
        if not cursor or not page:
            break
    logger.info(
        f"Fetched {len(conversations)} conversations for ticket {ticket_id}",
        extra={"ticket_id": ticket_id, "count": len(conversations)},
    )
    return conversations


def add_ticket_note(ticket_id: int, note_body: str) -> dict:
    """
    Add a note to a ticket via MCP (write operation).

    Raises:
        FreshDeskMCPUnavailableError: If MCP not configured
        FreshDeskMCPError: If MCP call fails
    """
    _check_configured()

    logger.info(f"Adding note to ticket {ticket_id} via MCP", extra={"ticket_id": ticket_id})

    inner = _call_with_session(
        "createTicketNote",
        {
            "id": ticket_id,
            "body": note_body,
            "_reasoning": f"GhostWork communication agent adding approved note to ticket {ticket_id}",
        },
    )

    if inner.get("error"):
        raise FreshDeskMCPError(f"MCP error: {inner.get('message', 'Unknown error')}")

    note_data = inner.get("data") if isinstance(inner.get("data"), dict) else inner
    note_id = note_data.get("id")
    if not note_id:
        raise FreshDeskMCPError("MCP returned no note ID")

    logger.info(
        f"Successfully added note {note_id} to ticket {ticket_id} via MCP",
        extra={"ticket_id": ticket_id, "note_id": note_id},
    )
    return {"status": "success", "note_id": note_id, "ticket_id": ticket_id}


def fetch_agent(agent_id: int) -> dict:
    """
    Fetch a Freshdesk agent via MCP. The name and phone numbers live under "contact".

    Raises:
        FreshDeskMCPUnavailableError: If MCP not configured
        FreshDeskMCPError: If MCP call fails
    """
    _check_configured()

    inner = _call_with_session(
        "fetchAgent",
        {"id": agent_id, "_reasoning": "GhostWork looking up the assigned agent to call for approval"},
    )
    if inner.get("error"):
        raise FreshDeskMCPError(f"MCP error: {inner.get('message', 'Unknown error')}")

    agent = inner.get("data", inner)
    if not isinstance(agent, dict) or not agent.get("id"):
        raise FreshDeskMCPError("MCP returned no agent data")
    return agent


def update_ticket_status(ticket_id: int, status: int) -> dict:
    """
    Set a ticket's status via MCP (write operation), e.g. 5 = Closed.

    Raises:
        FreshDeskMCPUnavailableError: If MCP not configured
        FreshDeskMCPError: If MCP call fails (e.g. fields required on closure are missing)
    """
    _check_configured()

    logger.info(f"Setting ticket {ticket_id} status to {status} via MCP", extra={"ticket_id": ticket_id})

    inner = _call_with_session(
        "updateTicket",
        {
            "id": ticket_id,
            "status": status,
            "_reasoning": "GhostWork closure agent closing a ticket after verified automation",
        },
    )

    if inner.get("error"):
        raise FreshDeskMCPError(f"MCP error: {inner.get('message', 'Unknown error')}")

    return {"status": "success", "ticket_id": ticket_id}


def _normalize_mcp_ticket(mcp_ticket: dict) -> FreshDeskTicket:
    """Normalize an MCP ticket payload to the FreshDeskTicket schema."""
    from datetime import datetime

    ticket_id = mcp_ticket.get("id")
    subject = mcp_ticket.get("subject", "")
    description_text = mcp_ticket.get("description_text", "")
    requester_id = mcp_ticket.get("requester_id")
    status = mcp_ticket.get("status_name")
    priority = mcp_ticket.get("priority")

    requester_name = None
    if mcp_ticket.get("requester"):
        requester_name = mcp_ticket["requester"].get("name")

    created_at = None
    created_at_str = mcp_ticket.get("created_at")
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass

    custom_fields = mcp_ticket.get("custom_fields", {})
    if not isinstance(custom_fields, dict):
        custom_fields = {}

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
        raw_response=mcp_ticket,
    )
