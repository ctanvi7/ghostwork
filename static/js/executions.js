async function loadExecutions() {
    const loading = document.getElementById('loading');
    const error = document.getElementById('error');
    const content = document.getElementById('content');
    loading.classList.remove('hidden'); error.classList.add('hidden'); content.classList.add('hidden');
    try {
        const data = await api.listExecutions(50);
        renderExecutions(Array.isArray(data.executions) ? data.executions : []);
        content.classList.remove('hidden');
    } catch (cause) { error.classList.remove('hidden'); ui.showError('Executions unavailable', cause); }
    finally { loading.classList.add('hidden'); }
}

function renderExecutions(executions) {
    const list = document.getElementById('executions-list');
    if (!executions.length) {
        list.innerHTML = '<p class="empty-state">No executions yet. Open a workflow to start a run from an eligible ticket.</p>';
        return;
    }
    list.innerHTML = executions.map(item => {
        const id = Number(item.id);
        const status = String(item.status || 'PENDING');
        const created = item.created_at ? new Date(item.created_at).toLocaleString() : 'Unknown';
        return `<article class="execution-item"><div><div class="exec-header"><strong class="exec-id">Execution #${id}</strong><span class="status-badge status-${escapeHtml(status.toLowerCase())}">${escapeHtml(ui.statusLabel(status))}</span></div><div class="exec-details"><div><span class="label">Workflow</span><span>${escapeHtml(item.workflow_name || 'Workflow')}</span></div><div><span class="label">Freshdesk ticket</span><span>#${escapeHtml(item.ticket_id ?? '—')}</span></div><div><span class="label">Created</span><span>${escapeHtml(created)}</span></div></div></div><div class="exec-actions"><a href="/execution/${id}" class="btn btn-secondary">View execution</a></div></article>`;
    }).join('');
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('retry-btn').addEventListener('click', loadExecutions);
    loadExecutions();
});
