"""Freshdesk REST API v2 response schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FreshDeskTicket(BaseModel):
    """Normalized Freshdesk ticket for internal use."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ticket_id": 2048,
                "subject": "Refund request for INV-88421",
                "description_text": "Customer requests refund...",
                "requester_name": "Aditi Rao",
                "status": "open",
                "priority": 2,
                "custom_fields": {
                    "cf_refund_amount": 32000.0,
                    "cf_invoice_id": "INV-88421"
                }
            }
        }
    )

    ticket_id: int = Field(..., description="Freshdesk ticket ID")
    subject: str = Field(..., description="Ticket subject")
    description_text: str = Field(..., description="Full ticket description")
    requester_id: Optional[int] = Field(None, description="Freshdesk requester ID")
    requester_name: Optional[str] = Field(None, description="Requester full name")
    status: Optional[str] = Field(None, description="Ticket status")
    priority: Optional[int] = Field(None, description="Priority level (1-4)")
    created_at: Optional[datetime] = Field(None, description="Ticket creation time")
    custom_fields: dict = Field(default_factory=dict, description="Custom field values")
    raw_response: Optional[dict] = Field(
        None, description="Raw Freshdesk API response for debugging"
    )
