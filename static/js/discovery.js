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

        // min_frequency=1: show one-off patterns too, marked as not yet repeating
        const workflowsRes = await fetch('/api/discovery/workflows?min_frequency=1');
        if (!workflowsRes.ok) throw new Error('Failed to load workflows');
        const workflowsData = await workflowsRes.json();
        const workflows = workflowsData.workflows || [];

        const statsRes = await fetch('/api/discovery/stats');
        if (statsRes.ok) {
            const statsData = await statsRes.json();
            document.getElementById('metric-sessions').textContent = statsData.total_sessions;
        }
        document.getElementById('metric-workflows').textContent = workflows.length;
        document.getElementById('metric-instances').textContent =
            workflows.filter(w => w.is_repeating !== false).length;

        loadingEl.classList.add('hidden');
        renderSource(workflowsData);
        renderWorkflows(workflows);

    } catch (err) {
        console.error('Discovery load error:', err);
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
    }
}

function renderSource(data) {
    const el = document.getElementById('discovery-source');
    const label = document.getElementById('metric-sessions-label');
    if (data.source === 'freshdesk') {
        el.textContent = 'Source: live Freshdesk tickets (subject, type, tags and status only)';
        label.textContent = 'Tickets Analyzed';
    } else {
        const reason = data.fallback_reason ? ` (${data.fallback_reason})` : '';
        el.textContent = `Source: demo activity events${reason}`;
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

function renderTicketRows(w) {
    if (!w.tickets || w.tickets.length === 0) return '';
    const automatable = w.automation && w.automation.automatable;
    const rows = w.tickets.map(t => {
        let action;
        if (!t.actionable) {
            action = `<span class="ticket-status">${escapeHtml(t.status)}</span>`;
        } else if (automatable) {
            action = `<button class="btn btn-primary btn-small run-ticket-btn" type="button" data-ticket-id="${t.ticket_id}">Run automation</button>`;
        } else {
            action = `<button class="btn btn-secondary btn-small handoff-btn" type="button" data-ticket-id="${t.ticket_id}">Route to human</button>`;
        }
        return `
            <li class="ticket-row">
                <span class="ticket-subject">#${t.ticket_id} ${escapeHtml(t.subject)}</span>
                ${action}
            </li>`;
    }).join('');
    return `<ul class="ticket-list">${rows}</ul>`;
}

function renderWorkflows(workflows) {
    const gridEl = document.getElementById('workflows-grid');

    if (!workflows || workflows.length === 0) {
        gridEl.innerHTML = '<p class="empty-state">No workflows discovered yet.</p>';
        return;
    }

    gridEl.innerHTML = workflows.map(w => `
        <div class="workflow-card">
            <div class="card-header">
                <h3 class="workflow-name">${escapeHtml(w.name)}</h3>
                <span class="ghostscore-badge" style="background-color: ${scoreColor(w.ghost_score)}">
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
                <p class="sequence-label">Process</p>
                <p class="sequence-text">${escapeHtml(w.sequence)}</p>
            </div>

            ${renderDecision(w)}
            ${renderTicketRows(w)}

            <div class="card-actions">
                <button class="btn btn-secondary explore-btn" data-workflow-id="${w.id}">
                    Explore
                </button>
                ${!w.tickets && w.name.toLowerCase().includes('refund') ?
                    `<button class="btn btn-primary run-refund-btn" type="button">Run Automation</button>`
                    : ''}
            </div>
        </div>
    `).join('');

    document.querySelectorAll('.explore-btn').forEach(btn => {
        btn.addEventListener('click', function() {
            window.location.href = `/workflow/${this.dataset.workflowId}`;
        });
    });

    // Demo-events fallback: canonical demo ticket and amount
    document.querySelectorAll('.run-refund-btn').forEach(btn => {
        btn.addEventListener('click', () => startRefundExecution(btn, { refund_amount: 32000 }));
    });

    // Freshdesk mode: run on the real ticket; the amount comes from the ticket or a human
    document.querySelectorAll('.run-ticket-btn').forEach(btn => {
        btn.addEventListener('click', () =>
            startRefundExecution(btn, { ticket_id: Number(btn.dataset.ticketId) }));
    });

    document.querySelectorAll('.handoff-btn').forEach(btn => {
        btn.addEventListener('click', () => routeToHuman(btn));
    });
}

async function startRefundExecution(button, payload) {
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Starting...';
    try {
        // Discovery IDs describe observed patterns; executable workflow IDs come from /api/workflows.
        const data = await api.getWorkflows();
        const refund = (data.workflows || []).find(w => w.name === 'Refund Verification');
        if (!refund) throw new Error('Refund Verification workflow is unavailable');
        const execution = await api.createExecution({ workflow_id: refund.id, ...payload });
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

function scoreColor(score) {
    if (score >= 80) return '#10b981';  // green
    if (score >= 60) return '#f59e0b';  // amber
    return '#ef4444';                    // red
}

function formatDuration(seconds) {
    if (seconds < 60) return Math.round(seconds) + 's';
    const minutes = Math.round(seconds / 60);
    return minutes + 'm';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
