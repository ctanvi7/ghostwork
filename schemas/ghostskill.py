"""Pydantic schemas for GhostSkill declarative specifications."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TriggerSpec(BaseModel):
    """Workflow trigger specification."""

    type: str = Field(..., description="Trigger type (e.g., 'refund_request', 'ticket_opened')")
    description: str = Field("", description="Human-readable trigger description")


class SkillInput(BaseModel):
    """Input parameter for skill execution."""

    name: str = Field(..., description="Input parameter name (e.g., 'refund_amount')")
    type: str = Field(..., description="Input type (number, string, id)")
    required: bool = Field(True, description="Whether this input is required")


class SkillStep(BaseModel):
    """A single step in skill execution."""

    order: int = Field(..., description="Step order (1-indexed)")
    name: str = Field(..., description="Step name (e.g., 'risk_assessment')")
    agent: Optional[str] = Field(None, description="Agent to execute (None if unmapped)")
    action: str = Field("", description="Human-readable action description")
    automation: str = Field("automatic", description="'automatic' or 'human_required'")
    status: str = Field("MAPPED", description="'MAPPED' or 'NEEDS_CONFIGURATION'")


class AutonomyBoundary(BaseModel):
    """Policy boundary for autonomous execution."""

    type: str = Field("amount_threshold", description="Boundary type")
    threshold: float = Field(..., description="Threshold amount")
    currency: str = Field("INR", description="Currency code")
    on_exceed: str = Field("require_human_approval", description="Action on threshold exceed")


class ApprovalPolicy(BaseModel):
    """Approval requirements."""

    required_when_exceeded: bool = Field(True, description="Require approval when threshold exceeded")
    channel: str = Field("web", description="Approval channel (web, voice, etc.)")


class VerificationSpec(BaseModel):
    """Verification requirements."""

    required: bool = Field(True, description="Whether verification is required")
    method: str = Field("reread_and_compare", description="Verification method")


class PrivacySpec(BaseModel):
    """Privacy specification."""

    metadata_only: bool = Field(True, description="Only track metadata, not PII")


class GhostSkill(BaseModel):
    """Declarative GhostSkill specification."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "skill_id": "abc123def456",
                "name": "Refund Verification",
                "version": "1.0",
                "description": "Automates refund verification workflows from Freshdesk tickets",
                "source_workflow_id": "hash_abc123",
                "ghost_score": 87.0,
                "trigger": {"type": "refund_request", "description": "Refund request in Freshdesk"},
                "inputs": [
                    {"name": "refund_amount", "type": "number", "required": True},
                    {"name": "ticket_id", "type": "id", "required": True},
                ],
                "steps": [
                    {"order": 1, "name": "context_agent", "agent": "context_agent", "status": "MAPPED"},
                    {"order": 2, "name": "billing_agent", "agent": "billing_agent", "status": "MAPPED"},
                    {"order": 3, "name": "policy_agent", "agent": "policy_agent", "status": "MAPPED"},
                    {"order": 4, "name": "risk_agent", "agent": "risk_agent", "status": "MAPPED"},
                    {"order": 5, "name": "approval_gate", "agent": "approval_gate", "status": "MAPPED"},
                    {"order": 6, "name": "communication_agent", "agent": "communication_agent", "status": "MAPPED"},
                    {"order": 7, "name": "verification_agent", "agent": "verification_agent", "status": "MAPPED"},
                ],
                "autonomy_boundary": {"type": "amount_threshold", "threshold": 25000, "currency": "INR", "on_exceed": "require_human_approval"},
                "approval_policy": {"required_when_exceeded": True, "channel": "web"},
                "verification": {"required": True, "method": "reread_and_compare"},
                "privacy": {"metadata_only": True},
                "generated_at": "2026-09-25T12:00:00+00:00",
                "status": "READY",
            }
        }
    )

    skill_id: str = Field(..., description="Unique skill identifier (UUID)")
    name: str = Field(..., description="Skill name (e.g., 'Refund Verification')")
    version: str = Field("1.0", description="Skill version")
    description: str = Field("", description="Human-readable skill description")
    source_workflow_id: str = Field(..., description="Discovered workflow ID this skill came from")
    ghost_score: float = Field(..., description="GhostScore from discovery")

    trigger: TriggerSpec = Field(..., description="Trigger specification")
    inputs: list[SkillInput] = Field(default_factory=list, description="Input parameters")
    steps: list[SkillStep] = Field(..., description="Execution steps (must not be empty)")

    autonomy_boundary: AutonomyBoundary = Field(..., description="Threshold policy")
    approval_policy: ApprovalPolicy = Field(..., description="Approval requirements")
    verification: VerificationSpec = Field(..., description="Verification requirements")
    privacy: PrivacySpec = Field(default_factory=PrivacySpec, description="Privacy settings")

    generated_at: str = Field(..., description="Timestamp when skill was generated (ISO 8601)")
    status: str = Field(..., description="'READY' or 'NEEDS_CONFIGURATION'")
