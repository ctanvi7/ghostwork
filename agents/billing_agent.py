"""Billing agent: stub that returns success."""

from typing import Any, Dict, Optional


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stub billing agent."""
    return {
        "status": "SUCCESS",
        "result": {
            "reason": "Billing check passed"
        }
    }
