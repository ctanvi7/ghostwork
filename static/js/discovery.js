/**
 * Discovery page - load and render discovered workflows.
 *
 * Patterns come from live Freshdesk tickets (fallback: synthetic activity events).
 * Each pattern carries a server-side automation decision:
 *   AUTOMATE     -> "Run automation" on an open ticket (approval gate still applies)
 *   HUMAN_REVIEW -> "Route to human" adds a private handoff note to the ticket
 */

async function loadDiscoveryData() {
    const loadingEl = document.getElementById('workflows-loading');
    const errorEl = document.getElementById('workflows-error');

    try {
        loadingEl.classList.remove('hidden');
        errorEl.classList.add('hidden');
        document.getElementById('workflows-content').classList.add('hidden');

        // min_frequency=1: show one-off patterns too, marked as not yet repeating
        const workflowsData = await api.getDiscoveredWorkflows(1);
        const workflows = workflowsData.workflows || [];
        let ticketProvider = 'Provider unavailable';
        if (workflowsData.source === 'freshdesk') {
            try {
                const integrationData = await api.getIntegrations();
                const selected = integrationData.configured?.freshdesk?.provider;
                ticketProvider = selected === 'mcp' ? 'MCP' : selected === 'rest' ? 'REST' : 'Provider unavailable';
            } catch (_) { /* Discovery remains usable when integration status is unavailable. */ }
        }

        try {
            const statsData = await api.getDiscoveryStats();
            document.getElementById('metric-sessions').textContent = statsData.total_sessions;
        } catch (_) { /* The ticket count is optional. */ }
        document.getElementById('metric-workflows').textContent = workflows.length;
        document.getElementById('metric-instances').textContent =
            workflows.filter(w => w.is_repeating !== false).length;

        loadingEl.classList.add('hidden');
        document.getElementById('workflows-content').classList.remove('hidden');
        renderSource(workflowsData, ticketProvider);
        renderWorkflows(workflows, ticketProvider);

    } catch (err) {
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
        ui.showError('Workflows unavailable', err);
    }
}

function renderSource(data, provider) {
    const el = document.getElementById('discovery-source');
    const label = document.getElementById('metric-sessions-label');
    if (data.source === 'freshdesk') {
        el.textContent = `Live Freshdesk tickets · ${provider} provider · grouped from ticket metadata.`;
        label.textContent = 'Tickets Analyzed';
    } else {
        const reason = data.fallback_reason ? ` (${data.fallback_reason})` : '';
        el.textContent = `Activity event fallback${reason}`;
        label.textContent = 'Sessions Analyzed';
    }
    el.classList.remove('hidden');
}

function renderDecision(w) {
    if (!w.automation) return '';
    const automatable = w.automation.automatable;
    return `
        <div class="card-decision">
            <span class="risk-badge ${automatable ? 'risk-low' : 'risk-medium'}">
                ${automatable ? 'Automatable' : 'Human review'}
            </span>
            <p class="decision-reason">${escapeHtml(w.automation.reason)}</p>
        </div>`;
}

function renderTicketRows(w, provider) {
    if (!w.tickets || w.tickets.length === 0) return '';
    const automatable = w.automation && w.automation.automatable;
    const rows = w.tickets.map(t => {
        const ticketUrl = safeFreshdeskUrl(t.url);
        let action;
        if (!t.actionable) {
            action = `<span class="ticket-status">${escapeHtml(t.status)}</span>`;
        } else if (automatable) {
            action = `<button class="btn btn-primary btn-small run-ticket-btn" type="button" data-ticket-id="${t.ticket_id}" data-workflow-name="${escapeHtml(w.automation.workflow_name)}">Run automation</button>`;
        } else {
            action = `<button class="btn btn-secondary btn-small handoff-btn" type="button" data-ticket-id="${t.ticket_id}">Route to human</button>`;
        }
        return `
            <li class="ticket-row">
                <span class="ticket-subject"><span class="ticket-brand"><span class="freshdesk-mark" aria-hidden="true">F</span>Freshdesk ticket #${Number(t.ticket_id)}</span><span class="ticket-meta">${escapeHtml(t.subject)} · ${escapeHtml(t.status)} · ${escapeHtml(provider)}</span></span>
                <span class="ticket-actions">${ticketUrl ? `<a class="btn btn-secondary btn-small" href="${escapeHtml(ticketUrl)}" target="_blank" rel="noopener noreferrer">View in Freshdesk</a>` : ''}${action}</span>
            </li>`;
    }).join('');
    return `<ul class="ticket-list">${rows}</ul>`;
}

function safeFreshdeskUrl(url) {
    try {
        const parsed = new URL(url);
        return parsed.protocol === 'https:' && parsed.hostname.endsWith('.freshdesk.com') ? parsed.href : null;
    } catch (_) { return null; }
}

function renderWorkflows(workflows, provider) {
    const gridEl = document.getElementById('workflows-grid');

    if (!workflows || workflows.length === 0) {
        gridEl.innerHTML = '<p class="empty-state">No workflows discovered yet. Check the Freshdesk integration or try again when new tickets are available.</p>';
        return;
    }

    gridEl.innerHTML = workflows.map(w => `
        <div class="workflow-card">
            <div class="card-header">
                <h3 class="workflow-name">${escapeHtml(w.name)}</h3>
                <span class="ghostscore-badge">
                    ${w.ghost_score}
                </span>
            </div>

            <div class="card-metrics">
                <div class="metric-row">
                    <span class="label">Frequency</span>
                    <span class="value">${w.is_repeating === false ? 'Seen once' : `${w.frequency}× recurring`}</span>
                </div>
                <div class="metric-row">
                    <span class="label">Automation</span>
                    <span class="value">${Math.round(w.automation_percentage)}%</span>
                </div>
                <div class="metric-row">
                    <span class="label">Duration</span>
                    <span class="value">${formatDuration(w.average_duration_seconds)}${w.duration_is_estimate ? ' (est.)' : ''}</span>
                </div>
                <div class="metric-row">
                    <span class="label">Steps</span>
                    <span class="value">${w.step_count}</span>
                </div>
            </div>

            <div class="card-sequence">
                <p class="sequence-label">Observed process</p>
                <p class="sequence-text">${escapeHtml(w.sequence)}</p>
            </div>

            ${renderDecision(w)}
            ${renderTicketRows(w, provider)}

            <div class="card-actions">
                <button class="btn btn-secondary explore-btn" data-workflow-id="${w.id}">
                    View workflow
                </button>
            </div>
        </div>
    `).join('');

    document.querySelectorAll('.explore-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            window.location.href = `/workflow/${this.dataset.workflowId}`;
        });
    });

    // Freshdesk mode: run on the real ticket, using whichever playbook this pattern matched.
    document.querySelectorAll('.run-ticket-btn').forEach(btn => {
        btn.addEventListener('click', () =>
            startAutomation(btn, btn.dataset.workflowName, { ticket_id: Number(btn.dataset.ticketId) }));
    });

    document.querySelectorAll('.handoff-btn').forEach(btn => {
        btn.addEventListener('click', () => routeToHuman(btn));
    });
}

async function startAutomation(button, workflowName, payload) {
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Starting...';
    try {
        // Discovery IDs describe observed patterns; executable workflow IDs come from /api/workflows.
        const data = await api.getWorkflows();
        const workflow = (data.workflows || []).find(w => w.name === workflowName);
        if (!workflow) throw new Error(`${workflowName} workflow is unavailable`);
        const execution = await api.createExecution({ workflow_id: workflow.id, ...payload });
        window.location.href = `/execution/${execution.id}`;
    } catch (error) {
        ui.showError('Failed to start automation', error);
        button.disabled = false;
        button.textContent = originalText;
    }
}

async function routeToHuman(button) {
    button.disabled = true;
    button.textContent = 'Routing...';
    try {
        const result = await api.handoffTicket(Number(button.dataset.ticketId));
        const state = result.status === 'already_routed' ? 'Already with a human' : 'Routed to human';
        button.textContent = result.verified ? `${state} ✓` : `${state} (not verified)`;
    } catch (error) {
        ui.showError('Failed to route ticket', error);
        button.disabled = false;
        button.textContent = 'Route to human';
    }
}

function formatDuration(seconds) {
    if (seconds < 60) return Math.round(seconds) + 's';
    const minutes = Math.round(seconds / 60);
    return minutes + 'm';
}

// Load on page load
document.addEventListener('DOMContentLoaded', function() {
    loadDiscoveryData();

    // Add retry button listener if it exists
    const retryBtn = document.getElementById('retry-btn');
    if (retryBtn) {
        retryBtn.addEventListener('click', function() {
            document.getElementById('workflows-error').classList.add('hidden');
            loadDiscoveryData();
        });
    }
});
