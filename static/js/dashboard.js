async function loadDashboard() {
    const loading = document.getElementById('dashboard-loading');
    const error = document.getElementById('dashboard-error');
    const content = document.getElementById('dashboard-content');
    loading.classList.remove('hidden'); error.classList.add('hidden'); content.classList.add('hidden');
    try {
        const [workflowData, executionData] = await Promise.all([
            api.getDiscoveredWorkflows(1), api.listExecutions(20)
        ]);
        const workflows = workflowData.workflows || [];
        const executions = executionData.executions || [];
        const pending = executions.filter(item => item.status === 'WAITING_FOR_APPROVAL');
        document.getElementById('dashboard-metrics').innerHTML = [
            ['Discovered workflows', workflows.length, 'From current discovery data'],
            ['Recent executions', executions.length, 'Latest 20 workflow runs'],
            ['Recent approvals due', pending.length, 'Among the latest 20 runs']
        ].map(([label, value, note]) => `<div class="metric-card"><span class="metric-label">${label}</span><strong class="metric-value">${value}</strong><span class="metric-note">${note}</span></div>`).join('');
        document.getElementById('dashboard-source').textContent = workflowData.source === 'freshdesk'
            ? 'Patterns found in live Freshdesk ticket metadata.' : 'Patterns from available activity events.';
        document.getElementById('dashboard-approvals').innerHTML = pending.length
            ? pending.slice(0, 3).map(item => `<div class="ticket-row"><span><strong>Execution #${Number(item.id)}</strong><span class="ticket-meta">Ticket #${escapeHtml(item.ticket_id ?? '—')} · ${escapeHtml(item.workflow_name || 'Workflow')}</span></span><a class="btn btn-secondary btn-small" href="/execution/${Number(item.id)}">Review</a></div>`).join('')
            : '<p class="empty-state">No executions are waiting for approval.</p>';
        document.getElementById('dashboard-executions').innerHTML = executions.length
            ? executions.slice(0, 5).map(item => `<div class="ticket-row"><span><strong>Execution #${Number(item.id)}</strong><span class="ticket-meta">${escapeHtml(item.workflow_name || 'Workflow')} · ${escapeHtml(ui.statusLabel(item.status))}</span></span><a class="btn btn-secondary btn-small" href="/execution/${Number(item.id)}">View execution</a></div>`).join('')
            : '<p class="empty-state">No executions yet. Explore a workflow to begin.</p>';
        document.getElementById('dashboard-workflows').innerHTML = workflows.length
            ? workflows.slice(0, 4).map(item => `<div class="ticket-row"><span><strong>${escapeHtml(item.name)}</strong><span class="ticket-meta">${Number(item.frequency || 0)} observed · ${escapeHtml(item.automation?.automatable ? 'Automation available' : 'Human review')}</span></span><a class="btn btn-secondary btn-small" href="/workflow/${Number(item.id)}">View workflow</a></div>`).join('')
            : '<p class="empty-state">No workflows discovered yet. Check the Freshdesk integration or try again.</p>';
        content.classList.remove('hidden');
    } catch (cause) {
        error.classList.remove('hidden');
        ui.showError('Dashboard unavailable', cause);
    } finally { loading.classList.add('hidden'); }
}
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('dashboard-retry').addEventListener('click', loadDashboard);
    loadDashboard();
});
