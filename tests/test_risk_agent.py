"""Tests for the Risk Agent."""

from decimal import Decimal

from agents.risk_agent import run
from config import Config


class TestRiskAgent:
    """Test risk assessment logic."""

    def test_amount_below_limit_no_approval(self):
        """₹10,000 is below ₹25,000 limit → no approval required."""
        result = run({"refund_amount": Decimal("10000")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is False
        assert result["result"]["amount"] == Decimal("10000")
        assert result["result"]["effective_limit"] == Decimal("25000")

    def test_amount_at_limit_no_approval(self):
        """₹25,000 equals limit → no approval required (boundary case)."""
        result = run({"refund_amount": Decimal("25000")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is False
        assert result["result"]["amount"] == Decimal("25000")

    def test_amount_just_above_limit_requires_approval(self):
        """₹25,001 exceeds limit → approval required."""
        result = run({"refund_amount": Decimal("25001")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert result["result"]["amount"] == Decimal("25001")

    def test_amount_well_above_limit_requires_approval(self):
        """₹32,000 exceeds limit → approval required (demo amount)."""
        result = run({"refund_amount": Decimal("32000")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert result["result"]["amount"] == Decimal("32000")

    def test_missing_amount_fail_closed(self):
        """Missing amount → fail closed, requires approval."""
        result = run({})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert result["result"]["amount"] is None

    def test_none_amount_fail_closed(self):
        """None amount → fail closed."""
        result = run({"refund_amount": None})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True

    def test_zero_amount_fail_closed(self):
        """Zero amount → fail closed, requires approval."""
        result = run({"refund_amount": Decimal("0")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert "must be positive" in result["result"]["reason"]

    def test_negative_amount_fail_closed(self):
        """Negative amount → fail closed."""
        result = run({"refund_amount": Decimal("-1000")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert "must be positive" in result["result"]["reason"]

    def test_integer_amount_converted_to_decimal(self):
        """Integer amounts are converted to Decimal."""
        result = run({"refund_amount": 10000})
        assert result["status"] == "SUCCESS"
        assert isinstance(result["result"]["amount"], Decimal)
        assert result["result"]["amount"] == Decimal("10000")

    def test_string_amount_converted_to_decimal(self):
        """String amounts are converted to Decimal."""
        result = run({"refund_amount": "10000"})
        assert result["status"] == "SUCCESS"
        assert isinstance(result["result"]["amount"], Decimal)
        assert result["result"]["amount"] == Decimal("10000")

    def test_float_amount_converted_to_decimal(self):
        """Float amounts are converted to Decimal."""
        result = run({"refund_amount": 10000.50})
        assert result["status"] == "SUCCESS"
        assert isinstance(result["result"]["amount"], Decimal)
        assert result["result"]["amount"] == Decimal("10000.5")

    def test_invalid_string_amount_fail_closed(self):
        """Invalid string amount → fail closed."""
        result = run({"refund_amount": "not_a_number"})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True

    def test_skill_limit_stricter_than_global(self):
        """Skill limit ₹20,000 < ₹25,000 → effective limit is ₹20,000."""
        context = {"skill_approval_limit": Decimal("20000")}
        result = run({"refund_amount": Decimal("22000")}, context=context)
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert result["result"]["effective_limit"] == Decimal("20000")
        assert result["result"]["amount"] == Decimal("22000")

    def test_skill_limit_looser_than_global_ignored(self):
        """Skill limit ₹50,000 > ₹25,000 → effective limit remains ₹25,000."""
        context = {"skill_approval_limit": Decimal("50000")}
        result = run({"refund_amount": Decimal("32000")}, context=context)
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert result["result"]["effective_limit"] == Decimal("25000")
        # Amount still requires approval because global limit is stricter

    def test_skill_limit_equal_to_global(self):
        """Skill limit ₹25,000 = global limit → effective limit is ₹25,000."""
        context = {"skill_approval_limit": Decimal("25000")}
        result = run({"refund_amount": Decimal("20000")}, context=context)
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is False
        assert result["result"]["effective_limit"] == Decimal("25000")

    def test_config_auto_approval_limit_is_used(self):
        """Config.AUTO_APPROVAL_LIMIT is the global limit."""
        result = run({"refund_amount": Config.AUTO_APPROVAL_LIMIT})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is False

        result_just_over = run({"refund_amount": Config.AUTO_APPROVAL_LIMIT + Decimal("1")})
        assert result_just_over["status"] == "SUCCESS"
        assert result_just_over["result"]["requires_approval"] is True

    def test_skill_limit_as_string_converted(self):
        """Skill limit as string is converted to Decimal."""
        context = {"skill_approval_limit": "15000"}
        result = run({"refund_amount": Decimal("20000")}, context=context)
        assert result["status"] == "SUCCESS"
        assert result["result"]["effective_limit"] == Decimal("15000")

    def test_skill_limit_as_integer_converted(self):
        """Skill limit as integer is converted to Decimal."""
        context = {"skill_approval_limit": 15000}
        result = run({"refund_amount": Decimal("20000")}, context=context)
        assert result["status"] == "SUCCESS"
        assert result["result"]["effective_limit"] == Decimal("15000")

    def test_invalid_skill_limit_ignored(self):
        """Invalid skill limit is ignored, global limit used."""
        context = {"skill_approval_limit": "invalid"}
        result = run({"refund_amount": Decimal("30000")}, context=context)
        assert result["status"] == "SUCCESS"
        assert result["result"]["effective_limit"] == Decimal("25000")

    def test_no_context_uses_global_limit(self):
        """No context → uses global limit."""
        result = run({"refund_amount": Decimal("30000")}, context=None)
        assert result["status"] == "SUCCESS"
        assert result["result"]["effective_limit"] == Decimal("25000")

    def test_large_amount_requires_approval(self):
        """Large amounts clearly require approval."""
        result = run({"refund_amount": Decimal("100000")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True

    def test_decimal_precision_preserved(self):
        """Decimal precision is preserved."""
        result = run({"refund_amount": Decimal("25000.99")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is True
        assert result["result"]["amount"] == Decimal("25000.99")

    def test_very_small_amount_no_approval(self):
        """Very small amounts don't require approval."""
        result = run({"refund_amount": Decimal("0.01")})
        assert result["status"] == "SUCCESS"
        assert result["result"]["requires_approval"] is False

    def test_reason_field_populated_on_success(self):
        """Reason field is populated on success."""
        result = run({"refund_amount": Decimal("10000")})
        assert "reason" in result["result"]
        assert len(result["result"]["reason"]) > 0
        assert "within" in result["result"]["reason"]

    def test_reason_field_populated_on_approval_required(self):
        """Reason field is populated when approval is required."""
        result = run({"refund_amount": Decimal("32000")})
        assert "reason" in result["result"]
        assert len(result["result"]["reason"]) > 0
        assert "exceeds" in result["result"]["reason"]
