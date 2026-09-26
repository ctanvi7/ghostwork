"""Diagnosis agent: deterministic Windows troubleshooting guide selection.

No approval is required for this playbook (it is advice, not a financial or
irreversible action), so this agent never pauses. It reuses the ticket subject
already captured by context_agent - no second Freshdesk call.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# (issue key, display name, keywords, resolution steps). First match wins.
RESOLUTION_GUIDES = [
    ("bsod", "Blue Screen of Death", ["bsod", "blue screen"], [
        "Note the stop code shown on the blue screen (or check Reliability Monitor for it).",
        "Run Windows Update to install any pending cumulative or driver updates.",
        "Run 'sfc /scannow' and 'DISM /Online /Cleanup-Image /RestoreHealth' from an elevated prompt.",
        "If the crash started after a specific driver update, roll that driver back.",
    ]),
    ("boot_failure", "Boot Failure", ["boot", "loading screen", "won't start", "wont start"], [
        "Try Safe Mode (hold Shift while clicking Restart, or interrupt boot 3 times).",
        "If Safe Mode works, run 'sfc /scannow' and check Device Manager for a conflicting driver.",
        "If Safe Mode also fails, use Windows Recovery > Startup Repair from installation media.",
        "As a last resort, check System Restore points from before the issue started.",
    ]),
    ("network", "Wi-Fi / Network Adapter", ["wi-fi", "wifi", "network adapter", "no internet"], [
        "Check Device Manager for the network adapter; update or reinstall its driver if flagged.",
        "Run 'ipconfig /release' then 'ipconfig /renew', and 'ipconfig /flushdns'.",
        "Run the built-in Network Adapter troubleshooter (Settings > Network > Status).",
        "Confirm the issue is not limited to one network by testing another Wi-Fi network or a wired connection.",
    ]),
    ("windows_update", "Windows Update Stuck", ["windows update", "update stuck", "update failing"], [
        "Run the Windows Update troubleshooter (Settings > Troubleshoot > Other troubleshooters).",
        "Restart the Windows Update service, or clear the SoftwareDistribution cache and retry.",
        "Check available disk space; updates can stall silently when the disk is nearly full.",
        "If a specific update (KB number) keeps failing, note it and pause that update while investigating.",
    ]),
    ("performance", "Slow Performance", ["slow performance", "high cpu", "high disk"], [
        "Open Task Manager and identify which process is using the CPU/disk.",
        "Run a malware scan; unexpected high usage is a common infection symptom.",
        "Check available disk space and consider disabling unnecessary startup programs.",
        "If a Windows Update was recently installed, check whether usage returns to normal after a restart.",
    ]),
]
GENERIC_GUIDE = ("general", "General Windows Issue", [
    "Restart the device to rule out a transient issue.",
    "Run Windows Update and install any pending updates.",
    "Run 'sfc /scannow' from an elevated command prompt to check for corrupted system files.",
    "If the issue persists, collect the exact error message or behavior for a follow-up.",
])


def _select_guide(text: str) -> tuple:
    text = text.lower()
    for key, name, keywords, steps in RESOLUTION_GUIDES:
        if any(word in text for word in keywords):
            return key, name, steps
    return GENERIC_GUIDE


def _ticket_text(context: Optional[Dict[str, Any]]) -> str:
    ticket = ((context or {}).get("context_agent") or {}).get("result", {}).get("ticket") or {}
    return ticket.get("subject") or ""


def run(execution: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Select a deterministic troubleshooting guide for the ticket.

    Always returns SUCCESS: this agent gives advice, so there is nothing to
    fail closed on. Never requires human approval.
    """
    text = _ticket_text(context) or execution.get("ticket_text", "")
    issue_key, issue_name, steps = _select_guide(text)

    logger.info(f"Execution {execution.get('id')}: matched '{issue_name}' troubleshooting guide")

    return {
        "status": "SUCCESS",
        "result": {
            "reason": f"Matched '{issue_name}' troubleshooting guide",
            "issue_type": issue_key,
            "issue_name": issue_name,
            "resolution_steps": steps,
        },
    }
