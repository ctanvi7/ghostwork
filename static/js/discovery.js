/**
 * Discovery page - load and render discovered workflows
 */

async function loadDiscoveryData() {
    const loadingEl = document.getElementById('workflows-loading');
    const errorEl = document.getElementById('workflows-error');
    const gridEl = document.getElementById('workflows-grid');

    try {
        loadingEl.classList.remove('hidden');
        errorEl.classList.add('hidden');

        // Load workflows
        const workflowsRes = await fetch('/api/discovery/workflows');
        if (!workflowsRes.ok) throw new Error('Failed to load workflows');
        const workflowsData = await workflowsRes.json();

        // Load stats
        const statsRes = await fetch('/api/discovery/stats');
        if (statsRes.ok) {
            const statsData = await statsRes.json();
            document.getElementById('metric-workflows').textContent = statsData.discovered_workflows;
            document.getElementById('metric-sessions').textContent = statsData.total_sessions;
            document.getElementById('metric-instances').textContent = statsData.total_workflow_instances;
        }

        loadingEl.classList.add('hidden');

        // Render workflows
        renderWorkflows(workflowsData.workflows);

    } catch (err) {
        console.error('Discovery load error:', err);
        loadingEl.classList.add('hidden');
        errorEl.classList.remove('hidden');
    }
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
                    <span class="value">${w.frequency}× recurring</span>
                </div>
                <div class="metric-row">
                    <span class="label">Automation</span>
                    <span class="value">${Math.round(w.automation_percentage)}%</span>
                </div>
                <div class="metric-row">
                    <span class="label">Duration</span>
                    <span class="value">${formatDuration(w.average_duration_seconds)}</span>
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

            <div class="card-risk">
                <span class="risk-badge risk-${w.risk_level}">${w.risk_level}</span>
            </div>

            <div class="card-actions">
                <button class="btn btn-secondary" data-workflow-id="${w.id}">
                    Explore
                </button>
                ${w.name.toLowerCase().includes('refund') ?
                    `<button class="btn btn-primary run-refund-btn" type="button">Run Automation</button>`
                    : ''}
            </div>
        </div>
    `).join('');

    // Add event listeners to Explore buttons
    document.querySelectorAll('.workflow-card .btn-secondary').forEach(btn => {
        btn.addEventListener('click', function() {
            const workflowId = this.dataset.workflowId;
            window.location.href = `/workflow/${workflowId}`;
        });
    });

    document.querySelectorAll('.run-refund-btn').forEach(btn => {
        btn.addEventListener('click', () => startRefundExecution(btn));
    });
}

async function startRefundExecution(button) {
    button.disabled = true;
    button.textContent = 'Starting...';
    try {
        // Discovery IDs describe observed patterns; executable workflow IDs come from /api/workflows.
        const data = await api.getWorkflows();
        const refund = (data.workflows || []).find(w => w.name === 'Refund Verification');
        if (!refund) throw new Error('Refund Verification workflow is unavailable');
        const execution = await api.createExecution({
            workflow_id: refund.id,
            ticket_id: 2048,
            refund_amount: 32000
        });
        window.location.href = `/execution/${execution.id}`;
    } catch (error) {
        ui.showError('Failed to start automation', error);
        button.disabled = false;
        button.textContent = 'Run Automation';
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
