"""Regression checks for the operational UI without changing workflow APIs."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("path", ["/", "/workflows", "/executions", "/approvals", "/integrations"])
def test_navigation_and_csp(client, path):
    response = client.get(path)
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'href="/approvals"' in html
    assert 'href="/workflows"' in html
    assert "GhostSkills" not in html
    assert 'id="sidebar-toggle"' in html
    assert 'id="message-region"' in html
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_privacy_and_terms_are_available(client, monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "AUTH_REQUIRED", True)
    assert b"Privacy Policy" in client.get("/privacy").data
    assert b"Terms of Service" in client.get("/terms").data


def test_execution_ui_uses_live_freshdesk_and_approval_fields():
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable")
    source = Path("static/js/execution-page.js").resolve()
    script = r"""
const vm = require('vm');
const fs = require('fs');
const container = {innerHTML: '', dataset: {executionId: '29'}};
const document = {
  getElementById(id) { return id === 'execution-content' ? container : null; },
  addEventListener() {}
};
const context = {document, window:{addEventListener(){}}, URL, console,
  ui:{showInfo(){},showError(){}},
  escapeHtml(value){return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;');}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const execution = {id:29,status:'WAITING_FOR_APPROVAL',ticket_id:3,refund_amount:32000,
  approvals:[{id:9,status:'PENDING'}],steps:[{step_name:'context_agent',status:'SUCCESS',
    output_json:{source:'freshdesk',provider:'mcp',refund_amount_source:'freshdesk_custom_field',
      ticket:{ticket_id:3,subject:'When will I get my refund??',status:2,url:'https://example.freshdesk.com/a/tickets/3'}}}]};
vm.runInContext('renderExecution', context)(execution);
const html = container.innerHTML;
for(const expected of ['Freshdesk','MCP','Ticket #3','When will I get my refund??',
  '₹32,000','₹25,000','Human approval required','View in Freshdesk','Not yet verified']) {
  if (!html.includes(expected)) throw new Error('Missing '+expected);
}
if (html.includes('Freshdesk updated via MCP')) throw new Error('Premature write-back claim');
execution.status = 'COMPLETED';
execution.steps.push({step_name:'communication_agent',status:'SUCCESS',output_json:{action_performed:true,provider:'mcp'}});
execution.steps.push({step_name:'verification_agent',status:'SUCCESS',output_json:{verified:true,provider:'mcp'}});
vm.runInContext('renderExecution', context)(execution);
if (!container.innerHTML.includes('Freshdesk updated via MCP') ||
    !container.innerHTML.includes('Freshdesk update verified')) {
  throw new Error('Verified completion labels missing');
}
"""
    result = subprocess.run(
        ["node", "-e", script, str(source)], capture_output=True, text=True, check=False, timeout=10
    )
    assert result.returncode == 0, result.stderr
