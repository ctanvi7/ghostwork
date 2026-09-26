async function loadApprovals() {
    const loading = document.getElementById('approvals-loading');
    const error = document.getElementById('approvals-error');
    const content = document.getElementById('approvals-content');
    loading.classList.remove('hidden'); error.classList.add('hidden'); content.classList.add('hidden');
    try {
        const pending = [];
        let offset = 0;
        while (true) {
            const data = await api.listExecutions(100, offset);
            const page = data.executions || [];
            pending.push(...page.filter(item => item.status === 'WAITING_FOR_APPROVAL'));
            if (page.length < 100) break;
            offset += 100;
        }
        document.getElementById('approval-count').textContent = `${pending.length} pending`;
        document.getElementById('approvals-list').innerHTML = pending.length
            ? pending.map(item => `<article class="execution-item"><div><div class="exec-header"><strong class="exec-id">Execution #${Number(item.id)}</strong><span class="status-badge status-waiting_for_approval">Human approval required</span></div><div class="exec-details"><div><span class="label">Workflow</span>${escapeHtml(item.workflow_name || 'Workflow')}</div><div><span class="label">Freshdesk ticket</span>#${escapeHtml(item.ticket_id ?? '—')}</div><div><span class="label">Current stage</span>${escapeHtml(ui.stageLabel(item.current_step || 'approval_gate'))}</div></div></div><a class="btn btn-primary" href="/execution/${Number(item.id)}">Review approval</a></article>`).join('')
            : '<p class="empty-state">No approvals are pending. New requests will appear here when a workflow reaches its autonomy boundary.</p>';
        content.classList.remove('hidden');
    } catch (cause) { error.classList.remove('hidden'); ui.showError('Approvals unavailable', cause); }
    finally { loading.classList.add('hidden'); }
}
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('approvals-retry').addEventListener('click', loadApprovals);
    loadApprovals();
});
