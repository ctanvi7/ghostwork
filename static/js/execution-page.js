const executionId = Number(document.getElementById('execution-content')?.dataset.executionId || 0);
let pollInterval = null;
let lastStatus = null;
let lastSnapshot = null;
let decisionInProgress = false;
let callInProgress = false;
const STAGES = [
    ['context_agent', 'Context'], ['billing_agent', 'Billing'], ['policy_agent', 'Policy'],
    ['risk_agent', 'Risk assessment'], ['approval_gate', 'Human approval'],
    ['communication_agent', 'Freshdesk update'], ['verification_agent', 'Verification'],
    ['closure_agent', 'Ticket closure'],
    ['diagnosis_agent', 'Diagnosis'], ['it_communication_agent', 'Freshdesk reply'],
    ['it_verification_agent', 'Verification'], ['it_closure_agent', 'Ticket resolution']
];

/** True only for a workflow with an approval gate (currently: Refund Verification). */
function hasApprovalGate(execution) {
    return (execution.steps || []).some(item => item.step_name === 'risk_agent');
}

function stepOutput(execution, name) {
    const step = (execution.steps || []).find(item => item.step_name === name);
    return step?.output_json && typeof step.output_json === 'object' ? step.output_json : null;
}

function safeFreshdeskUrl(url) {
    try {
        const parsed = new URL(url);
        return parsed.protocol === 'https:' && parsed.hostname.endsWith('.freshdesk.com') ? parsed.href : null;
    } catch { return null; }
}

function statusLabel(status) {
    return ({PENDING: 'Pending', RUNNING: 'In progress', WAITING_FOR_APPROVAL: 'Human approval required',
        APPROVED: 'Approved', COMPLETED: 'Completed', REJECTED: 'Rejected', FAILED: 'Failed'})[status] || status;
}

function ticketStatus(code) {
    return ({2: 'Open', 3: 'Pending', 4: 'Resolved', 5: 'Closed'})[Number(code)] || (code ? String(code) : 'Unknown');
}

function money(amount) { return amount == null ? 'Not provided' : `₹${Number(amount).toLocaleString('en-IN')}`; }

/** The limit the Risk Agent applied (a GhostSkill may be stricter than ₹25,000). */
function approvalLimit(execution) {
    const limit = Number(stepOutput(execution, 'risk_agent')?.effective_limit);
    return Number.isFinite(limit) && limit > 0 ? limit : 25000;
}

function pendingApproval(execution) {
    const approvals = execution.approvals || [];
    return approvals.find(item => item.status === 'PENDING') || null;
}

function field(label, value, wide = false) {
    return `<div class="${wide ? 'wide' : ''}"><span class="source-label">${label}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function renderSource(execution) {
    const context = stepOutput(execution, 'context_agent');
    const cached = context?.source === 'cached_demo';
    if (!context || !(context.source === 'freshdesk' || cached) || !context.ticket) {
        const reason = context?.freshdesk_error ? `Freshdesk read failed: ${context.freshdesk_error}` : 'Ticket context is not available yet.';
        return `<section class="panel"><h2>Ticket source</h2><p>${escapeHtml(reason)}</p></section>`;
    }
    const ticket = context.ticket;
    const url = cached ? null : safeFreshdeskUrl(ticket.url);
    const provider = (context.provider || '').toLowerCase();
    const providerLabel = cached ? 'Cached demo ticket' : provider === 'mcp' ? 'MCP' : provider === 'rest' ? 'REST' : 'Unknown';
    const gated = hasApprovalGate(execution);
    const amountSource = ({request: 'Entered at execution start',
        freshdesk_custom_field: cached ? 'Cached ticket Refund Amount field' : 'Freshdesk Refund Amount field',
        missing: 'Not provided'})[context.refund_amount_source] || 'Unknown';
    const amountFields = gated ? `${field('Refund request', money(execution.refund_amount))}${field('Amount source', amountSource)}` : '';
    const cachedNote = cached ? `<p class="fallback-note" role="status">Freshdesk is unavailable (${escapeHtml(context.freshdesk_error || 'not configured')}). This run uses the cached demo ticket, so nothing is written to Freshdesk.</p>` : '';
    return `<section class="freshdesk-panel" aria-label="Freshdesk ticket">
        <div class="panel-header"><div><div class="freshdesk-identity"><span class="freshdesk-mark" aria-hidden="true">F</span>${cached ? 'Freshdesk (cached)' : 'Freshdesk'}</div><h2>Ticket #${escapeHtml(ticket.ticket_id)}</h2></div><span class="status-badge">${escapeHtml(ticketStatus(ticket.status))}</span></div>
        <div class="data-list">${field('Subject', ticket.subject || 'Untitled ticket', true)}${field('Provider', providerLabel)}${field('Execution', `#${execution.id}`)}${amountFields}</div>
        ${cachedNote}${url ? `<a class="btn btn-secondary source-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">View in Freshdesk</a>` : ''}
    </section>`;
}

function renderSummary(execution) {
    const gated = hasApprovalGate(execution);
    const write = stepOutput(execution, 'communication_agent') || stepOutput(execution, 'it_communication_agent');
    const verify = stepOutput(execution, 'verification_agent') || stepOutput(execution, 'it_verification_agent');
    const closure = stepOutput(execution, 'closure_agent') || stepOutput(execution, 'it_closure_agent');
    const stages = execution.steps || [];
    const active = stages.find(item => ['RUNNING', 'PAUSED'].includes(item.status)) || stages.find(item => item.status === 'PENDING');
    const current = execution.status === 'WAITING_FOR_APPROVAL' ? 'Human approval' :
        execution.status === 'COMPLETED' ? 'Completed' :
        STAGES.find(([key]) => key === (active?.step_name || execution.current_step))?.[1] ||
        (execution.current_step ? execution.current_step.replaceAll('_', ' ') : statusLabel(execution.status));
    const writeText = write?.action_performed
        ? `Freshdesk updated via ${(write.provider || 'provider').toUpperCase()}`
        : write?.writeback_status === 'skipped' ? 'Skipped (no live Freshdesk ticket)'
        : write ? 'Not written' : 'Pending approval and execution';
    const verifyText = verify?.verified
        ? 'Freshdesk update verified'
        : verify?.verification_status === 'skipped_fallback' ? 'Skipped (nothing was written)'
        : verify ? 'Verification did not pass' : 'Not yet verified';
    const amountFields = gated
        ? `${field('Refund amount', money(execution.refund_amount))}${field('Autonomy limit', money(approvalLimit(execution)))}`
        : '';
    const approvalField = gated
        ? field('Approval', statusLabel(execution.status === 'WAITING_FOR_APPROVAL' ? execution.status : (execution.approvals?.[0]?.status || execution.status)))
        : '';
    return `<section class="panel execution-summary"><h2>Execution state</h2><div class="data-list">
        ${amountFields}${field('Current stage', current)}${approvalField}
        ${field('Write-back', writeText)}${field('Verification', verifyText)}${field('Ticket status', closure?.closed ? (closure.ticket_status ? `${closure.ticket_status} and confirmed` : 'Closed and confirmed') : closure ? (closure.reason || 'Left open') : 'Not yet')}</div></section>`;
}

function renderProgress(execution) {
    const steps = execution.steps || [];
    if (!steps.length) return '<section class="panel"><h2>Workflow progress</h2><p>No steps have started yet.</p></section>';
    // The paused approval gate is stored as SUCCESS internally; show what it really is.
    const gateState = ({WAITING_FOR_APPROVAL: 'Waiting for approval', REJECTED: 'Rejected'})[execution.status];
    const gateOpen = step => step.step_name === 'approval_gate' && gateState;
    const isDone = step => step.status === 'SUCCESS' && !gateOpen(step);
    const done = steps.filter(isDone).length;
    // Recorded steps only: the client has no reliable way to know how many
    // steps a given workflow has in total (STAGES spans multiple playbooks).
    const total = steps.length;
    const filled = Math.floor(done / total * 4);
    const segments = Array.from({length: 4}, (_, index) => `<span class="${index < filled ? 'done' : index === filled ? 'current' : ''}"></span>`).join('');
    const rows = steps.map(step => {
        const name = STAGES.find(([key]) => key === step.step_name)?.[1] || String(step.step_name || 'Step').replaceAll('_', ' ');
        const state = gateOpen(step) ? gateState : step.status === 'SUCCESS' ? 'Completed' : step.status === 'RUNNING' ? 'In progress' : step.status === 'FAILED' ? 'Failed' : step.status === 'PAUSED' ? 'Paused' : 'Pending';
        const reason = typeof step.output_json?.reason === 'string' ? step.output_json.reason : '';
        return `<div class="step-item" data-status="${escapeHtml(step.status || 'PENDING')}"><div class="step-status-icon" aria-hidden="true">${isDone(step) ? '●' : '○'}</div><div class="step-info"><div class="step-name">${escapeHtml(name)} <span class="status-badge">${state}</span></div>${reason ? `<div class="step-detail">${escapeHtml(reason)}</div>` : ''}</div></div>`;
    }).join('');
    return `<section class="panel"><div class="section-head"><div><h2>Workflow progress</h2><p>${done} of ${total} steps completed</p></div></div><div class="progress-rail" aria-hidden="true">${segments}</div><div class="steps-timeline">${rows}</div></section>`;
}

function renderApproval(execution) {
    const approval = pendingApproval(execution);
    if (execution.status !== 'WAITING_FOR_APPROVAL' || !approval) return '';
    const limit = approvalLimit(execution);
    const over = Number(execution.refund_amount) - limit;
    // After a call ends without a decision the approver can be called again.
    const callEnded = approval.raw_response_json?.voice_status === 'ended';
    const callRequested = approval.channel === 'voice' && !callEnded;
    return `<section class="section approval-section" aria-labelledby="approval-title"><p class="eyebrow">Decision needed</p><h2 id="approval-title">Human approval required</h2><p>The risk assessment has paused this execution. Freshdesk will not be updated until a person approves it.</p>
        <div class="amount-display"><div>Refund request<strong>${money(execution.refund_amount)}</strong></div><div>Autonomy limit<strong>${money(limit)}</strong></div><div>Over limit<strong>${over > 0 ? money(over) : 'Amount requires review'}</strong></div></div>
        <div class="approval-buttons"><button id="approve-btn" class="btn btn-primary" type="button">Approve request</button><button id="reject-btn" class="btn btn-danger" type="button">Reject request</button><button id="call-btn" class="btn btn-secondary" type="button" ${callRequested ? 'disabled' : ''}>${callRequested ? 'Call requested' : callEnded ? 'Call again' : 'Call approver'}</button></div>
        ${callRequested ? '<div class="system-message" data-kind="info" role="status"><div><strong>Waiting for a response</strong><p>The approval call was requested. Web approval remains available.</p></div></div>' : ''}
        ${callEnded ? '<div class="system-message" data-kind="info" role="status"><div><strong>Call ended without a decision</strong><p>Call the approver again or use web approval.</p></div></div>' : ''}
    </section>`;
}

function renderExecution(execution) {
    const snapshot = JSON.stringify(execution);
    if (snapshot === lastSnapshot) return;
    lastSnapshot = snapshot;
    const container = document.getElementById('execution-content');
    const status = execution.status || 'PENDING';
    if (lastStatus && lastStatus !== status) ui.showInfo('Execution updated', statusLabel(status));
    lastStatus = status;
    container.innerHTML = `<header class="execution-header"><div><p class="eyebrow">Workflow execution</p><h1>Execution #${Number(execution.id)}</h1><p class="page-subtitle">${escapeHtml(execution.workflow_name || 'Refund verification')}</p></div><span class="status-badge" data-status="${escapeHtml(status)}">${statusLabel(status)}</span></header>
        ${renderSource(execution)}${renderSummary(execution)}${renderApproval(execution)}${renderProgress(execution)}`;
    document.getElementById('approve-btn')?.addEventListener('click', () => decide('approve'));
    document.getElementById('reject-btn')?.addEventListener('click', () => decide('reject'));
    document.getElementById('call-btn')?.addEventListener('click', callApprover);
    if (decisionInProgress) {
        document.getElementById('approve-btn').disabled = true;
        document.getElementById('reject-btn').disabled = true;
    }
    if (callInProgress && document.getElementById('call-btn')) document.getElementById('call-btn').disabled = true;
}

async function decide(action) {
    if (decisionInProgress) return;
    decisionInProgress = true;
    const button = document.getElementById(`${action}-btn`);
    if (button) button.disabled = true;
    try {
        const execution = await api.getExecution(executionId);
        const approval = pendingApproval(execution);
        if (!approval) throw new Error('This execution has no pending approval.');
        if (action === 'approve') await api.approveExecution(approval.id);
        else await api.rejectExecution(approval.id);
        ui.showSuccess(action === 'approve' ? 'Approval received. The workflow is resuming.' : 'Request rejected. The workflow has stopped.');
        await loadExecution();
    } catch (error) {
        ui.showError(action === 'approve' ? 'Approval failed' : 'Rejection failed', error);
        if (button) button.disabled = false;
    } finally { decisionInProgress = false; }
}

async function callApprover() {
    if (callInProgress) return;
    callInProgress = true;
    const button = document.getElementById('call-btn');
    if (button) button.disabled = true;
    const progress = ui.showMessage('info', 'Calling approver', 'Connecting by phone. Web approval remains available.', true);
    try {
        const call = await api.callApprover(executionId);
        progress.remove();
        ui.showInfo('Call requested', `Calling ${call.approver?.number || 'the configured approver'}. Waiting for a response. Web approval remains available.`);
    } catch (error) {
        progress.remove();
        ui.showMessage('warning', 'Call failed', `${error.message} Use web approval to continue.`, true);
        if (button) button.disabled = false;
    } finally { callInProgress = false; }
}

async function loadExecution() {
    if (!Number.isInteger(executionId) || executionId < 1) { ui.showError('Invalid execution', new Error('Select an execution from the list.')); return; }
    try {
        const execution = await api.getExecution(executionId);
        renderExecution(execution);
        if (['COMPLETED', 'REJECTED', 'FAILED'].includes(execution.status)) { clearInterval(pollInterval); pollInterval = null; }
        else if (!pollInterval) pollInterval = setInterval(loadExecution, 3000);
    } catch (error) {
        lastSnapshot = null;
        document.getElementById('execution-content').innerHTML = '<div class="error-state" role="alert">Execution could not be loaded. <button id="execution-retry" type="button">Try again</button></div>';
        document.getElementById('execution-retry').addEventListener('click', loadExecution);
        ui.showError('Execution unavailable', error);
        clearInterval(pollInterval); pollInterval = null;
    }
}
document.addEventListener('DOMContentLoaded', loadExecution);
window.addEventListener('beforeunload', () => clearInterval(pollInterval));
