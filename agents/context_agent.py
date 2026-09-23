"""Context agent: stub that returns success."""

from typing import Any, Dict, Optional


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stub context agent."""
    return {
        "status": "SUCCESS",
        "result": {
            "reason": "Context extracted"
        }
    }
