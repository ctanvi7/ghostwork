"""Execution state machine with allowed transitions."""

from typing import Dict, Set

from app import InvalidStateError
from services.supabase_service import get_service

# Define allowed state transitions
ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "PENDING": {"RUNNING", "FAILED"},
    "RUNNING": {"WAITING_FOR_APPROVAL", "COMPLETED", "FAILED"},
    "WAITING_FOR_APPROVAL": {"APPROVED", "REJECTED"},
    "APPROVED": {"RUNNING"},
    "REJECTED": set(),
    "COMPLETED": set(),
    "FAILED": set(),
}

# Terminal states (no further transitions allowed)
TERMINAL_STATES = {"REJECTED", "COMPLETED", "FAILED"}


def validate_transition(from_status: str, to_status: str) -> bool:
    """Check if transition from -> to is allowed."""
    if from_status not in ALLOWED_TRANSITIONS:
        return False
    return to_status in ALLOWED_TRANSITIONS[from_status]


def transition(
    execution_id: int,
    from_status: str,
    to_status: str,
    **extra_fields,
) -> int:
    """
    Attempt a conditional state transition (compare-and-set).

    Returns: count of rows updated (0 means CAS failed, 1 means success).
    Raises: InvalidStateError if transition is not allowed.
    """
    # Validate the transition is allowed
    if not validate_transition(from_status, to_status):
        raise InvalidStateError(
            f"Cannot transition from {from_status} to {to_status}"
        )

    # Use service to perform atomic CAS update
    service = get_service()
    count = service.transition_execution(
        execution_id, from_status, to_status, **extra_fields
    )

    if count == 0:
        # CAS failed: either execution doesn't exist or current status != from_status
        raise InvalidStateError(
            f"Failed to transition execution {execution_id} from {from_status}: "
            "current status does not match (possible concurrent update)"
        )

    return count


def is_terminal(status: str) -> bool:
    """Check if status is terminal (no more transitions allowed)."""
    return status in TERMINAL_STATES
