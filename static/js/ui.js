/** Shared, accessible product messages and plain-language labels. */
const ui = (() => {
    const STATUS_LABELS = {PENDING: 'Pending', RUNNING: 'In progress', WAITING_FOR_APPROVAL: 'Human approval required',
        APPROVED: 'Approved', COMPLETED: 'Completed', REJECTED: 'Rejected', FAILED: 'Failed'};
    const STAGE_LABELS = {context_agent: 'Context', billing_agent: 'Billing', policy_agent: 'Policy',
        risk_agent: 'Risk assessment', approval_gate: 'Human approval', communication_agent: 'Freshdesk update',
        verification_agent: 'Verification', closure_agent: 'Ticket closure'};

    function showMessage(kind, title, detail = '', persistent = false) {
        const region = document.getElementById('message-region') || document.body;
        const message = document.createElement('div');
        message.className = 'system-message';
        message.dataset.kind = kind;
        message.setAttribute('role', kind === 'error' ? 'alert' : 'status');
        const content = document.createElement('div');
        const heading = document.createElement('strong');
        heading.textContent = title;
        content.appendChild(heading);
        if (detail) {
            const paragraph = document.createElement('p');
            paragraph.textContent = detail;
            content.appendChild(paragraph);
        }
        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'message-close';
        close.setAttribute('aria-label', 'Dismiss message');
        close.textContent = '×';
        close.addEventListener('click', () => message.remove());
        message.append(content, close);
        region.prepend(message);
        if (!persistent) setTimeout(() => message.remove(), kind === 'error' ? 12000 : 6500);
        return message;
    }
    return {
        statusLabel(status) { return STATUS_LABELS[status] || String(status || 'Pending'); },
        stageLabel(step) { return STAGE_LABELS[step] || String(step || 'Step').replaceAll('_', ' '); },
        showMessage,
        showError(title, error) { return showMessage('error', title, error?.message || String(error)); },
        showSuccess(message) { return showMessage('success', message); },
        showInfo(title, detail) { return showMessage('info', title, detail); }
    };
})();

function escapeHtml(value) {
    const element = document.createElement('div');
    element.textContent = value == null ? '' : String(value);
    return element.innerHTML;
}

