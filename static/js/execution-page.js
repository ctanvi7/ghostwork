/**
 * Execution page functionality
 */

const executionId = parseInt(document.querySelector('script[data-execution-id]')?.getAttribute('data-execution-id') || '0');
let pollInterval = null;

async function loadExecution() {
    if (!Number.isInteger(executionId) || executionId < 1) {
        ui.showError('Failed to load execution', new Error('Select a run from the Executions page.'));
        return;
    }
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
                            ${execution.refund_amount == null
                                ? `<div>Refund Amount: <strong>Not provided on ticket</strong></div>
                                   <div>Autonomy Limit: <strong>₹25,000</strong></div>
                                   <div class="amount-exceeds">Amount unknown, so a human must review before any refund</div>`
                                : `<div>Refund Amount: <strong>₹${formatNumber(amount)}</strong></div>
                                   <div>Autonomy Limit: <strong>₹25,000</strong></div>
                                   <div class="amount-exceeds">Exceeds limit by ₹${formatNumber(amount - 25000)}</div>`}
                        </div>
                    </div>
                    <div class="approval-buttons">
                        <button id="approve-btn" class="btn btn-success">Approve</button>
                        <button id="reject-btn" class="btn btn-danger">Reject</button>
                        <button id="call-btn" class="btn btn-secondary">Call Approver</button>
                    </div>
                    ${approval.channel === 'voice' ? '<p class="verification-note">Approval call requested. Web approval remains available.</p>' : ''}
                </section>
            `;
        }
    }

    const stepsHtml = renderSteps(execution.steps || []);
    const impactHtml = renderImpact(execution);
    const sourceHtml = renderSource(execution);

    container.innerHTML = `
        <div class="execution-header">
            <h2>Execution #${execution.id}</h2>
            <div class="status-badge" data-status="${status}">
                ${statusLabel(status)}
            </div>
        </div>

        ${sourceHtml}

        <section class="section">
            <h3>Workflow Steps</h3>
            <div class="steps-timeline">
                ${stepsHtml}
            </div>
        </section>

        ${approvalHtml}
        ${impactHtml}
    `;

    // Add event listeners for approval buttons
    const approveBtn = document.getElementById('approve-btn');
    const rejectBtn = document.getElementById('reject-btn');
    const callBtn = document.getElementById('call-btn');

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
    if (callBtn) {
        callBtn.addEventListener('click', async () => {
            callBtn.disabled = true;
            callBtn.textContent = 'Calling...';
            try {
                const call = await api.callApprover(executionId);
                const who = call.approver && call.approver.source === 'ticket_assignee'
                    ? `ticket assignee (${call.approver.number})`
                    : `fallback approver (${call.approver ? call.approver.number : 'configured number'})`;
                ui.showSuccess(`Calling ${who}. Web approval remains available.`);
            } catch (error) {
                ui.showError('Call unavailable', error);
                callBtn.disabled = false;
                callBtn.textContent = 'Call Approver';
            }
        });
    }
}

function stepOutput(execution, stepName) {
    const step = (execution.steps || []).find(s => s.step_name === stepName);
    return (step && step.output_json && typeof step.output_json === 'object') ? step.output_json : null;
}

function safeFreshdeskUrl(url) {
    try {
        const parsed = new URL(url);
        return parsed.protocol === 'https:' && parsed.hostname.endsWith('.freshdesk.com') ? parsed.href : null;
    } catch (e) {
        return null;
    }
}

function renderSource(execution) {
    const context = stepOutput(execution, 'context_agent');
    if (!context) return '';

    if (context.source !== 'freshdesk' || !context.ticket) {
        const label = context.source === 'fallback_error' ? 'Demo data (Freshdesk read failed)' : 'Demo data';
        return `
            <section class="section source-section" data-source="demo">
                <h3>Source</h3>
                <div class="source-grid">
                    <div><span class="source-label">Source</span><strong>${escapeHtml(label)}</strong></div>
                    <div><span class="source-label">Ticket</span><strong>#${escapeHtml(String(execution.ticket_id ?? '—'))}</strong></div>
                    ${context.freshdesk_error ? `<div class="source-subject"><span class="source-label">Reason</span><strong>${escapeHtml(context.freshdesk_error)}</strong></div>` : ''}
                </div>
            </section>
        `;
    }

    const ticket = context.ticket;
    const url = safeFreshdeskUrl(ticket.url);
    const write = stepOutput(execution, 'communication_agent');
    const verify = stepOutput(execution, 'verification_agent');
    const closure = stepOutput(execution, 'closure_agent');
    const amountSource = {
        request: 'Entered at execution start',
        freshdesk_custom_field: 'Freshdesk Refund Amount field',
        missing: 'Not provided (approval required)'
    }[context.refund_amount_source] || '—';

    return `
        <section class="section source-section" data-source="freshdesk">
            <h3>Source: Freshdesk</h3>
            <div class="source-grid">
                <div><span class="source-label">Provider</span><strong>${escapeHtml((context.provider || '—').toUpperCase())}</strong></div>
                <div><span class="source-label">Ticket</span><strong>#${escapeHtml(String(ticket.ticket_id))}</strong></div>
                <div class="source-subject"><span class="source-label">Subject</span><strong>${escapeHtml(ticket.subject || '')}</strong></div>
                <div><span class="source-label">Refund amount from</span><strong>${escapeHtml(amountSource)}</strong></div>
                <div><span class="source-label">Write-back</span><strong>${write ? escapeHtml(write.action_performed ? `Note ${write.note_id} via ${(write.provider || '').toUpperCase()}` : 'Not written') : 'Not yet (after approval)'}</strong></div>
                <div><span class="source-label">Readback</span><strong>${verify ? escapeHtml(verify.verified ? `Verified via ${(verify.provider || '').toUpperCase()}` : 'Not verified') : 'Not yet'}</strong></div>
                <div><span class="source-label">Ticket closure</span><strong>${closure ? escapeHtml(closure.closed ? 'Closed and confirmed' : closure.reason || 'Left open') : 'Not yet (after verification)'}</strong></div>
            </div>
            ${url ? `<a class="btn btn-secondary source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">View in Freshdesk</a>` : ''}
        </section>
    `;
}

function renderImpact(execution) {
    if (execution.status !== 'COMPLETED') return '';
    const verification = (execution.steps || []).find(step => step.step_name === 'verification_agent');
    const verified = verification?.output_json?.verified === true;
    const verificationText = verified
        ? 'Freshdesk write-back verified'
        : 'External write-back was not verified in this demo run';
    return `
        <section class="section impact-section">
            <h3>Estimated impact</h3>
            <p class="impact-note">Demo estimates; measured results require a live workflow study.</p>
            <div class="metrics-grid">
                <div class="metric-card"><span class="metric-label">Manual time</span><strong class="metric-value">11m 07s</strong></div>
                <div class="metric-card"><span class="metric-label">Automated time</span><strong class="metric-value">1m 48s</strong></div>
                <div class="metric-card"><span class="metric-label">Human touches</span><strong class="metric-value">6 → 1</strong></div>
            </div>
            <p class="verification-note">${verificationText}</p>
        </section>
    `;
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
