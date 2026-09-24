"""GhostScore calculation: transparent deterministic workflow automation suitability score."""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def calculate_ghostscore(
    frequency: int,
    step_count: int,
    average_duration_seconds: float,
    automation_percentage: float = 0,
    step_signatures: List[str] = None,
    max_frequency: int = 37
) -> Dict[str, Any]:
    """
    Calculate GhostScore (0-100) representing automation suitability.

    Components:
    - frequency (25%): how often the workflow repeats
    - repeatability (25%): consistency of sequence structure
    - manual_effort (20%): estimated time spent (duration)
    - automation_potential (20%): % of steps that are automatable
    - risk_penalty (10%): risk adjustment for critical workflows

    All components are normalized to 0-100 and transparent in the breakdown.

    Args:
        frequency: Number of times this workflow was observed
        step_count: Number of steps in the workflow
        average_duration_seconds: Average time to complete (seconds)
        automation_percentage: % of steps that are automatable (0-100)
        step_signatures: List of step signatures for analysis
        max_frequency: Maximum observed frequency (for normalization)

    Returns:
        {
            "score": int (0-100),
            "breakdown": {
                "frequency": int,
                "repeatability": int,
                "manual_effort": int,
                "automation_potential": int,
                "risk_penalty": int,
            }
        }
    """
    step_signatures = step_signatures or []

    # Component 1: Frequency (25%)
    # Normalize to 0-100 based on max observed frequency
    frequency_score = min(100, int((frequency / max(max_frequency, 1)) * 100))

    # Component 2: Repeatability (25%)
    # Based on number of distinct steps and consistency
    # Fewer steps with exact repetition = more repeatable
    repeatability_score = _calculate_repeatability(step_signatures, step_count)

    # Component 3: Manual Effort (20%)
    # Based on average duration
    # Longer duration = higher potential value from automation
    effort_score = _calculate_effort_score(average_duration_seconds)

    # Component 4: Automation Potential (20%)
    # % of steps that are tool-based and automatable
    automation_score = int(automation_percentage)

    # Component 5: Risk Penalty (10%)
    # Discount for workflows with inherent risk (e.g., financial approval)
    risk_score = _calculate_risk_penalty(step_signatures)

    # Weighted calculation
    total_score = (
        (frequency_score * 0.25) +
        (repeatability_score * 0.25) +
        (effort_score * 0.20) +
        (automation_score * 0.20) +
        (risk_score * 0.10)
    )

    # Clamp to 0-100
    total_score = min(100, max(0, int(total_score)))

    breakdown = {
        "frequency": frequency_score,
        "repeatability": repeatability_score,
        "manual_effort": effort_score,
        "automation_potential": automation_score,
        "risk_penalty": risk_score,
    }

    return {
        "score": total_score,
        "breakdown": breakdown
    }


def _calculate_repeatability(step_signatures: List[str], step_count: int) -> int:
    """
    Calculate repeatability score based on sequence consistency.

    More consistent sequences (exact same steps in order) = higher score.
    Fewer distinct patterns = higher score (simpler to automate).
    """
    if not step_signatures or step_count == 0:
        return 0

    # In a single discovered workflow, all sessions have the same signature,
    # so we reward:
    # 1. Having more steps (more complex workflows are less likely to recur)
    # 2. Structured patterns (tool-action pairs)

    # Extract tools from signatures
    tools = [s.split(":")[0] for s in step_signatures]
    distinct_tools = len(set(tools))

    # Score: fewer distinct tools relative to total steps = more structure
    structure_score = max(0, 100 - (distinct_tools * 10))

    # Reward longer, consistent workflows (5+ steps)
    if step_count >= 5:
        structure_score = min(100, structure_score + 15)

    return max(0, min(100, int(structure_score)))


def _calculate_effort_score(average_duration_seconds: float) -> int:
    """
    Calculate manual effort score based on average duration.

    Higher duration = more manual effort = higher value from automation.
    Normalized: 0s = 0, 900s (15min) = 100.
    """
    if average_duration_seconds <= 0:
        return 0

    # Target: 15 minutes (900s) = full score
    # Maximum: cap at 100
    target_duration = 900
    effort_score = (average_duration_seconds / target_duration) * 100

    return min(100, int(effort_score))


def _calculate_risk_penalty(step_signatures: List[str]) -> int:
    """
    Calculate risk adjustment (penalty/reward).

    Workflows with approval or financial steps need human oversight.
    Risk score should reduce the overall score by up to 10%.

    Returns 0-100, where 90-100 means "apply minimal penalty",
    and 0-10 means "apply maximum penalty".
    """
    if not step_signatures:
        return 100  # No penalty for unknown

    risk_factors = ["approval", "policy", "review"]
    has_risk = any(
        any(risk in s.lower() for risk in risk_factors)
        for s in step_signatures
    )

    if has_risk:
        # Workflows with built-in approval/policy/review need human oversight
        # Apply a modest penalty (score would be reduced by up to 10%)
        return 80  # 20% penalty applied

    return 100  # No penalty


def format_ghostscore_for_display(
    score: int,
    breakdown: Dict[str, int]
) -> Dict[str, Any]:
    """Format GhostScore for UI display with explanation."""
    return {
        "score": score,
        "grade": _score_to_grade(score),
        "explanation": _score_to_explanation(score),
        "breakdown": breakdown,
        "components": [
            {
                "name": "Frequency",
                "value": breakdown.get("frequency", 0),
                "weight": 25,
                "description": "How often this workflow occurs"
            },
            {
                "name": "Repeatability",
                "value": breakdown.get("repeatability", 0),
                "weight": 25,
                "description": "Consistency of the workflow sequence"
            },
            {
                "name": "Manual Effort",
                "value": breakdown.get("manual_effort", 0),
                "weight": 20,
                "description": "Time spent per workflow instance"
            },
            {
                "name": "Automation Potential",
                "value": breakdown.get("automation_potential", 0),
                "weight": 20,
                "description": "% of steps that can be automated"
            },
            {
                "name": "Risk Factor",
                "value": breakdown.get("risk_penalty", 0),
                "weight": 10,
                "description": "Adjustment for critical decision points"
            },
        ]
    }


def _score_to_grade(score: int) -> str:
    """Convert numerical score to letter grade."""
    if score >= 85:
        return "A"
    elif score >= 70:
        return "B"
    elif score >= 55:
        return "C"
    elif score >= 40:
        return "D"
    else:
        return "F"


def _score_to_explanation(score: int) -> str:
    """Generate human-readable explanation of score."""
    if score >= 85:
        return "Excellent automation candidate: high frequency, consistent, and valuable time savings"
    elif score >= 70:
        return "Good automation candidate: moderate frequency and clear repetition pattern"
    elif score >= 55:
        return "Fair candidate: workflow repeats but may have variability or lower effort"
    elif score >= 40:
        return "Consider for future: workflow shows some patterns but may not be ready yet"
    else:
        return "Not recommended: workflow is infrequent or has high variability"
