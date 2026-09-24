/**
 * Execution page functionality
 */

const executionId = parseInt(document.querySelector('script[data-execution-id]')?.getAttribute('data-execution-id') || '0');
let pollInterval = null;

async function loadExecution() {
    try {
        const execution = await api.getExecution(executionId);
        renderExecution(execution);

        // Poll for updates if still running
        if (!isTerminalStatus(execution.status)) {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(pollExecution, 1000);
        }
    } catch (error) {
        ui.showError('Failed to load execution', error);
    }
}

async function pollExecution() {
    try {
        const execution = await api.getExecution(executionId);
        renderExecution(execution);

        // Stop polling if execution is complete
        if (isTerminalStatus(execution.status)) {
            if (pollInterval) clearInterval(pollInterval);
        }
    } catch (error) {
        // Silently ignore poll errors
    }
}

function isTerminalStatus(status) {
    return ['COMPLETED', 'REJECTED', 'FAILED'].includes(status);
}

function renderExecution(execution) {
    const container = document.getElementById('execution-content');
    const amount = execution.refund_amount || 0;
    const status = execution.status || 'PENDING';

    let approvalHtml = '';
    if (status === 'WAITING_FOR_APPROVAL') {
        const approval = execution.approvals && execution.approvals[0];
        if (approval) {
            approvalHtml = `
                <section class="section approval-section">
                    <h3>Human Approval Required</h3>
                    <div class="approval-amount">
                        <div class="amount-display">
                            <div>Refund Amount: <strong>₹${formatNumber(amount)}</strong></div>
                            <div>Autonomy Limit: <strong>₹25,000</strong></div>
                            <div class="amount-exceeds">Exceeds limit by ₹${formatNumber(amount - 25000)}</div>
                        </div>
                    </div>
                    <div class="approval-buttons">
                        <button id="approve-btn" class="btn btn-success">Approve</button>
                        <button id="reject-btn" class="btn btn-danger">Reject</button>
                    </div>
                </section>
            `;
        }
    }

    const stepsHtml = renderSteps(execution.steps || []);

    container.innerHTML = `
        <div class="execution-header">
            <h2>Execution #${execution.id}</h2>
            <div class="status-badge" data-status="${status}">
                ${statusLabel(status)}
            </div>
        </div>

        <section class="section">
            <h3>Workflow Steps</h3>
            <div class="steps-timeline">
                ${stepsHtml}
            </div>
        </section>

        ${approvalHtml}
    `;

    // Add event listeners for approval buttons
    const approveBtn = document.getElementById('approve-btn');
    const rejectBtn = document.getElementById('reject-btn');

    if (approveBtn) {
        approveBtn.addEventListener('click', async () => {
            await approveExecution();
        });
    }

    if (rejectBtn) {
        rejectBtn.addEventListener('click', async () => {
            await rejectExecution();
        });
    }
}

function renderSteps(steps) {
    if (steps.length === 0) {
        return '<p class="no-steps">No steps executed yet</p>';
    }

    return steps.map(step => {
        const status = step.status || 'PENDING';
        const stepName = step.step_name || 'unknown';
        const duration = step.completed_at && step.started_at
            ? new Date(step.completed_at) - new Date(step.started_at)
            : null;

        let output = '';
        if (step.output_json && typeof step.output_json === 'object') {
            if (step.output_json.reason) {
                output = `<div class="step-detail">${escapeHtml(step.output_json.reason)}</div>`;
            }
        }

        return `
            <div class="step-item" data-status="${status}">
                <div class="step-status-icon">${statusIcon(status)}</div>
                <div class="step-info">
                    <div class="step-name">${escapeHtml(stepName)}</div>
                    ${output}
                    ${duration ? `<div class="step-duration">${Math.round(duration)}ms</div>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

async function approveExecution() {
    const execution = await api.getExecution(executionId);
    const approval = execution.approvals && execution.approvals[0];

    if (!approval) {
        ui.showError('No approval found', new Error('Cannot find approval record'));
        return;
    }

    const button = document.getElementById('approve-btn');
    button.disabled = true;
    button.textContent = 'Approving...';

    try {
        await api.approveExecution(approval.id);

        // Reload execution
        await loadExecution();
    } catch (error) {
        if (error.status === 409) {
            ui.showError('Already Decided', new Error('This approval has already been decided'));
        } else {
            ui.showError('Failed to approve', error);
        }
        button.disabled = false;
        button.textContent = 'Approve';
    }
}

async function rejectExecution() {
    const execution = await api.getExecution(executionId);
    const approval = execution.approvals && execution.approvals[0];

    if (!approval) {
        ui.showError('No approval found', new Error('Cannot find approval record'));
        return;
    }

    const button = document.getElementById('reject-btn');
    button.disabled = true;
    button.textContent = 'Rejecting...';

    try {
        await api.rejectExecution(approval.id);

        // Reload execution
        await loadExecution();
    } catch (error) {
        if (error.status === 409) {
            ui.showError('Already Decided', new Error('This approval has already been decided'));
        } else {
            ui.showError('Failed to reject', error);
        }
        button.disabled = false;
        button.textContent = 'Reject';
    }
}

function statusLabel(status) {
    const labels = {
        'PENDING': 'Pending',
        'RUNNING': 'Running',
        'WAITING_FOR_APPROVAL': 'Awaiting Approval',
        'APPROVED': 'Approved',
        'COMPLETED': 'Completed',
        'REJECTED': 'Rejected',
        'FAILED': 'Failed'
    };
    return labels[status] || status;
}

function statusIcon(status) {
    const icons = {
        'SUCCESS': '✓',
        'RUNNING': '⟳',
        'FAILED': '✕',
        'PAUSED': '⏸'
    };
    return icons[status] || '○';
}

function formatNumber(num) {
    return Math.floor(num).toLocaleString('en-IN');
}

// Load execution on page load
window.addEventListener('load', loadExecution);

// Cleanup on unload
window.addEventListener('beforeunload', () => {
    if (pollInterval) clearInterval(pollInterval);
});
