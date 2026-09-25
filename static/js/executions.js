/**
 * Executions page - load and render execution list
 */

async function loadExecutions() {
    try {
        const res = await fetch('/api/executions');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        const executions = Array.isArray(data.executions) ? data.executions : [];
        renderExecutions(executions);

        document.getElementById('loading').classList.add('hidden');
        document.getElementById('content').classList.remove('hidden');

    } catch (err) {
        console.error('Executions load error:', err);
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('error').classList.remove('hidden');
    }
}

function renderExecutions(executions) {
    const listEl = document.getElementById('executions-list');

    if (!executions || executions.length === 0) {
        listEl.innerHTML = '<p class="empty-state">No executions yet. Run a workflow to see execution history here.</p>';
        return;
    }

    listEl.innerHTML = executions.map(exec => {
        const statusClass = `status-${exec.status.toLowerCase()}`;
        const createdTime = new Date(exec.created_at).toLocaleString();

        return `
            <div class="execution-item">
                <div class="exec-header">
                    <span class="exec-id">Execution #${exec.id}</span>
                    <span class="status-badge ${statusClass}">${exec.status}</span>
                </div>
                <div class="exec-details">
                    <div>
                        <span class="label">Workflow:</span>
                        <span>${escapeHtml(exec.workflow_name || 'Unknown')}</span>
                    </div>
                    <div>
                        <span class="label">Current Step:</span>
                        <span>${escapeHtml(exec.current_step || '—')}</span>
                    </div>
                    <div>
                        <span class="label">Created:</span>
                        <span>${createdTime}</span>
                    </div>
                </div>
                <div class="exec-actions">
                    <a href="/execution?id=${exec.id}" class="btn btn-secondary">Details</a>
                </div>
            </div>
        `;
    }).join('');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', function() {
    loadExecutions();

    // Add retry button listener if it exists
    const retryBtn = document.getElementById('retry-btn');
    if (retryBtn) {
        retryBtn.addEventListener('click', function() {
            document.getElementById('error').classList.add('hidden');
            loadExecutions();
        });
    }
});
