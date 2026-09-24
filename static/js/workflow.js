/**
 * Workflow detail page functionality
 */

const workflowId = parseInt(document.querySelector('script[data-workflow-id]')?.getAttribute('data-workflow-id') || '0');

async function loadWorkflow() {
    try {
        const response = await api.getWorkflow(workflowId);
        const workflow = response.workflow || response;
        renderWorkflow(workflow);
    } catch (error) {
        ui.showError('Failed to load workflow', error);
    }
}

function renderWorkflow(workflow) {
    const container = document.getElementById('workflow-content');

    const ghostScore = workflow.ghost_score || 0;
    const frequency = workflow.frequency || 0;
    const automation = workflow.automation_percentage || 0;

    container.innerHTML = `
        <section class="section">
            <div class="workflow-header">
                <h2>${escapeHtml(workflow.name)}</h2>
                <div class="workflow-metrics">
                    <div class="metric-box">
                        <div class="metric-label">GhostScore</div>
                        <div class="metric-value">${ghostScore}</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Frequency</div>
                        <div class="metric-value">${frequency} cases</div>
                    </div>
                    <div class="metric-box">
                        <div class="metric-label">Automation</div>
                        <div class="metric-value">${automation}%</div>
                    </div>
                </div>
            </div>
            <p class="description">${escapeHtml(workflow.description || '')}</p>
        </section>

        <section class="section">
            <h3>Run Workflow</h3>
            <form id="run-form" class="form">
                <div class="form-group">
                    <label for="refund-amount">Refund Amount (₹)</label>
                    <input
                        type="number"
                        id="refund-amount"
                        name="refund_amount"
                        placeholder="32000"
                        value="32000"
                        min="0"
                        step="1"
                        required
                    >
                    <small>Demo: ₹32,000 (requires approval)</small>
                </div>
                <button type="submit" class="btn btn-primary">
                    Start Execution
                </button>
            </form>
        </section>
    `;

    const form = document.getElementById('run-form');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        await startExecution();
    });
}

async function startExecution() {
    const amount = parseFloat(document.getElementById('refund-amount').value);

    if (isNaN(amount) || amount < 0) {
        ui.showError('Invalid amount', new Error('Refund amount must be a positive number'));
        return;
    }

    const button = document.querySelector('#run-form button');
    button.disabled = true;
    button.textContent = 'Starting...';

    try {
        const execution = await api.createExecution({
            workflow_id: workflowId,
            ticket_id: 2048,
            refund_amount: amount
        });

        // Redirect to execution view
        window.location.href = `/execution/${execution.id}`;
    } catch (error) {
        ui.showError('Failed to start execution', error);
        button.disabled = false;
        button.textContent = 'Start Execution';
    }
}

// Load workflow on page load
window.addEventListener('load', loadWorkflow);
