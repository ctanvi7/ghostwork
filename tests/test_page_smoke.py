"""Smoke checks for every served page and its client assets."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from config import Config


@pytest.mark.parametrize(
    "path",
    ["/", "/workflow/1", "/executions", "/execution/1", "/execution?id=1", "/integrations"],
)
def test_page_and_referenced_assets_load(client, path):
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "GhostWork" in html
    for asset in re.findall(r'<(?:script|link)[^>]+(?:src|href)="(/static/[^"]+)"', html):
        asset_response = client.get(asset)
        assert asset_response.status_code == 200, asset


def test_freshdesk_tier_uses_selected_provider(monkeypatch):
    monkeypatch.setattr(Config, "FRESHDESK_PROVIDER", "mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_URL", "https://example.freshdesk.com/mcp")
    monkeypatch.setattr(Config, "MCP_FRESHDESK_AUTH_TOKEN", "test-token")
    monkeypatch.setattr(Config, "FRESHDESK_DOMAIN", None)
    monkeypatch.setattr(Config, "FRESHDESK_API_KEY", None)
    monkeypatch.setattr(Config, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(Config, "SARVAM_API_KEY", None)
    assert Config.derive_tier() == "B"


def test_integrations_page_renders_unconfigured_mcp_as_unconfigured():
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable")
    source_path = Path("static/js/integrations.js").resolve()
    script = """
const vm = require('vm');
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const grid = { innerHTML: '' };
const document = {
  addEventListener() {},
  getElementById(id) { return id === 'integrations-grid' ? grid : null; }
};
vm.runInNewContext(source + '\\nrenderIntegrations({configured: {freshdesk: {configured: false, provider: "mcp"}}});', {document});
const card = grid.innerHTML.split('class="integration-card"').find(part => part.includes('>Freshdesk</h3>'));
if (!card || !card.includes('status-not-configured')) process.exit(1);
"""
    result = subprocess.run(
        ["node", "-e", script, str(source_path)],
        text=True, capture_output=True, check=False, timeout=10
    )
    assert result.returncode == 0, result.stderr
