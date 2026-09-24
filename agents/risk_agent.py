"""Deterministic refund risk assessment agent."""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from config import Config


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Assess refund risk and determine if human approval is required.

    Args:
        execution: Execution record with refund_amount field
        context: Execution context (unused, but present for agent interface consistency)

    Returns:
        {
            "status": "SUCCESS" (always - never fails, just reports requires_approval flag),
            "result": {
                "requires_approval": bool,
                "amount": Decimal or None,
                "effective_limit": Decimal,
                "reason": str
            }
        }

    Logic:
    - Deterministic assessment: always returns SUCCESS with requires_approval flag set
    - If amount is missing, invalid, zero, or negative → requires_approval=true (fail closed)
    - If amount <= effective_limit → requires_approval=false (no approval needed)
    - If amount > effective_limit → requires_approval=true (approval required)
    - effective_limit = min(skill_limit, Config.AUTO_APPROVAL_LIMIT) if skill has a limit
    - The approval_gate step checks the requires_approval flag and returns PAUSE if needed

    This agent is purely deterministic and makes no external calls.
    """
    result = {
        "requires_approval": False,
        "amount": None,
        "effective_limit": Config.AUTO_APPROVAL_LIMIT,
        "reason": "",
    }

    # Extract refund amount from execution
    amount = execution.get("refund_amount")

    # Fail closed: amount must be a valid positive Decimal
    if amount is None:
        result["requires_approval"] = True
        result["reason"] = "refund_amount is missing"
        return {"status": "SUCCESS", "result": result}

    # Convert to Decimal if it's a number type
    try:
        if isinstance(amount, str):
            amount = Decimal(amount)
        elif isinstance(amount, (int, float)):
            amount = Decimal(str(amount))
        elif not isinstance(amount, Decimal):
            # Invalid type
            result["requires_approval"] = True
            result["reason"] = f"refund_amount has invalid type: {type(amount).__name__}"
            return {"status": "SUCCESS", "result": result}
    except (ValueError, TypeError, ArithmeticError):
        result["requires_approval"] = True
        result["reason"] = f"refund_amount cannot be converted to Decimal: {amount}"
        return {"status": "SUCCESS", "result": result}

    # Fail closed: amount must be positive
    if amount <= Decimal("0"):
        result["requires_approval"] = True
        result["amount"] = amount
        result["reason"] = f"refund_amount must be positive, got {amount}"
        return {"status": "SUCCESS", "result": result}

    result["amount"] = amount

    # Calculate effective limit (skill may have a stricter limit, but cannot increase the global limit)
    effective_limit = Config.AUTO_APPROVAL_LIMIT

    # Check context for a GhostSkill-defined approval limit
    if context and "skill_approval_limit" in context:
        skill_limit = context.get("skill_approval_limit")
        if skill_limit is not None:
            try:
                if isinstance(skill_limit, str):
                    skill_limit = Decimal(skill_limit)
                elif isinstance(skill_limit, (int, float)):
                    skill_limit = Decimal(str(skill_limit))

                if isinstance(skill_limit, Decimal):
                    # Effective limit is the stricter of the two
                    effective_limit = min(skill_limit, Config.AUTO_APPROVAL_LIMIT)
            except (ValueError, TypeError, InvalidOperation):
                # Ignore invalid skill limit, use global default
                pass

    result["effective_limit"] = effective_limit

    # Determine if approval is required
    if amount > effective_limit:
        result["requires_approval"] = True
        result["reason"] = f"refund_amount {amount} exceeds effective limit {effective_limit}"
        return {"status": "SUCCESS", "result": result}

    result["requires_approval"] = False
    result["reason"] = f"refund_amount {amount} is within effective limit {effective_limit}"
    return {"status": "SUCCESS", "result": result}
