"""Pydantic schemas for Claude structured responses."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TicketContext(BaseModel):
    """Structured context extracted from a support ticket by Claude."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "customer_name": "Aditi Rao",
                "issue_category": "refund",
                "issue_summary": "Customer requests refund for ticket INV-88421 due to unsatisfactory service.",
                "refund_amount_mentioned": 32000.0,
                "relevant_facts": [
                    "Invoice INV-88421",
                    "Service not meeting expectations",
                    "Customer provided ticket number 2048"
                ],
                "confidence_score": 0.95,
                "missing_information": [
                    "Exact reason for dissatisfaction",
                    "Previous service interactions"
                ]
            }
        }
    )

    customer_name: Optional[str] = Field(None, description="Customer name if mentioned")
    issue_category: str = Field(..., description="Category of the issue (refund, support, billing, etc.)")
    issue_summary: str = Field(..., description="Concise 1-2 sentence summary of the issue")
    refund_amount_mentioned: Optional[float] = Field(None, description="Refund amount if explicitly mentioned in text")
    relevant_facts: list[str] = Field(default_factory=list, description="Key facts/context for decision-making")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Confidence in extraction (0.0-1.0)")
    missing_information: list[str] = Field(default_factory=list, description="Information that would help but is missing")
