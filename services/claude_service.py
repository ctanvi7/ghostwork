"""Claude API service for structured ticket context extraction."""

import json
import logging

from config import Config
from schemas.claude_responses import TicketContext

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

logger = logging.getLogger(__name__)


def make_client():
    """Anthropic client with a bounded timeout, so a slow API cannot hang a request."""
    return Anthropic(
        api_key=Config.ANTHROPIC_API_KEY,
        timeout=Config.CLAUDE_TIMEOUT_SECONDS,
        max_retries=Config.CLAUDE_MAX_RETRIES,
    )


def extract_ticket_context(ticket_text: str) -> TicketContext:
    """
    Extract structured context from a support ticket using Claude.

    Args:
        ticket_text: The raw ticket text to analyze

    Returns:
        TicketContext with extracted information, or a fallback default response
    """
    # Check if Claude is configured
    if not Config.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not configured, returning fallback context")
        return _fallback_context(ticket_text)

    try:
        if Anthropic is None:
            raise ImportError("Anthropic SDK not installed")

        client = make_client()

        # System prompt for structured extraction
        system_prompt = """You are an expert support ticket analyst. Extract structured information from support tickets.
Return valid JSON only, no markdown or extra text. The JSON must match this schema exactly:
{
  "customer_name": "string or null",
  "issue_category": "string (refund, support, billing, complaint, other)",
  "issue_summary": "string (1-2 sentences)",
  "refund_amount_mentioned": "number or null",
  "relevant_facts": ["string"],
  "confidence_score": "number 0.0-1.0",
  "missing_information": ["string"]
}"""

        user_prompt = f"""Analyze this support ticket and extract structured context:

{ticket_text}"""

        # Call Claude with structured output
        # Room for adaptive thinking (on by default for current models) plus the JSON.
        response = client.messages.create(
            model=Config.CLAUDE_MODEL,
            max_tokens=4000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )

        # A refused or truncated answer is not usable JSON: fall back.
        if getattr(response, "stop_reason", None) in ("refusal", "max_tokens"):
            raise ValueError(f"Claude stopped early ({response.stop_reason})")

        # Parse the response (skip thinking blocks, extract text)
        response_text = None
        for block in response.content:
            if hasattr(block, 'text'):
                response_text = block.text.strip()
                break

        if response_text is None:
            raise ValueError("No text content in Claude response")

        # Remove markdown code blocks if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        # Parse JSON and validate with Pydantic
        response_json = json.loads(response_text)
        context = TicketContext(**response_json)

        logger.info(f"Successfully extracted context with confidence {context.confidence_score}")
        return context

    except ImportError:
        logger.warning("Anthropic SDK not available, returning fallback context")
        return _fallback_context(ticket_text)
    except ValueError as e:
        logger.warning(f"Failed to parse Claude response as JSON: {e}, using fallback")
        return _fallback_context(ticket_text)
    except json.JSONDecodeError as e:
        logger.warning(f"Claude returned invalid JSON: {e}, using fallback")
        return _fallback_context(ticket_text)
    except Exception as e:
        logger.error(f"Claude API call failed: {e}, using fallback")
        return _fallback_context(ticket_text)


def _fallback_context(ticket_text: str) -> TicketContext:
    """
    Return a fallback context when Claude is unavailable or fails.

    This ensures deterministic behavior and workflow continuity.
    """
    # Simple heuristic: if "refund" is mentioned, it's a refund issue
    issue_category = "refund" if "refund" in ticket_text.lower() else "support"

    # Try to find amount patterns like "₹X" or "X rupees"
    refund_amount = None
    import re
    # Look for patterns like ₹32000 or 32000
    amount_matches = re.findall(r'[\₹]?\s*(\d{1,6}(?:,\d{3})*(?:\.\d{2})?)', ticket_text)
    if amount_matches:
        try:
            # Take the first/largest amount found
            amounts = [float(m.replace(",", "")) for m in amount_matches]
            refund_amount = max(amounts) if amounts else None
        except ValueError:
            pass

    return TicketContext(
        customer_name=None,
        issue_category=issue_category,
        issue_summary=ticket_text[:100].strip() if ticket_text else "Support request",
        refund_amount_mentioned=refund_amount,
        relevant_facts=[],
        confidence_score=0.3,  # Low confidence to indicate fallback
        missing_information=[
            "Full ticket content not processed",
            "Claude not available"
        ]
    )
