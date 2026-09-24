/**
 * Dashboard page functionality
 */

async function loadWorkflows() {
    try {
        const response = await api.getWorkflows();
        const workflows = response.workflows || [];
        const container = document.getElementById('workflows-list');
        container.innerHTML = '';

        if (workflows.length === 0) {
            container.innerHTML = '<p class="empty-state">No workflows discovered.</p>';
            return;
        }

        workflows.forEach(workflow => {
            const card = createWorkflowCard(workflow);
            container.appendChild(card);
        });
    } catch (error) {
        ui.showError('Failed to load workflows', error);
    }
}

function createWorkflowCard(workflow) {
    const card = document.createElement('div');
    card.className = 'workflow-card';

    const ghostScore = workflow.ghost_score || 0;
    const frequency = workflow.frequency || 0;
    const automation = workflow.automation_percentage || 0;
    const duration = formatDuration(workflow.manual_duration_seconds || 0);

    card.innerHTML = `
        <div class="card-header">
            <h3>${escapeHtml(workflow.name)}</h3>
            <div class="ghost-score">GhostScore: ${ghostScore}</div>
        </div>
        <p class="description">${escapeHtml(workflow.description || '')}</p>
        <div class="metrics">
            <div class="metric">
                <span class="label">Frequency</span>
                <span class="value">${frequency} cases</span>
            </div>
            <div class="metric">
                <span class="label">Automation</span>
                <span class="value">${automation}%</span>
            </div>
            <div class="metric">
                <span class="label">Manual Duration</span>
                <span class="value">${duration}</span>
            </div>
        </div>
        <a href="/workflow/${workflow.id}" class="btn btn-primary">
            Run Workflow
        </a>
    `;

    return card;
}

function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    } else if (minutes > 0) {
        return `${minutes}m ${secs}s`;
    } else {
        return `${secs}s`;
    }
}

// Load workflows on page load
window.addEventListener('load', loadWorkflows);
