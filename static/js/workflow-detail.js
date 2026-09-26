/**
 * Workflow detail page - render discovery and the approved automation path.
 */

const workflowId = window.location.pathname.split('/').pop();

async function loadWorkflowDetail() {
    try {
        const workflow = await api.getDiscoveredWorkflow(workflowId);
        renderWorkflowDetail(workflow);
    } catch (err) {
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('error').classList.remove('hidden');
        ui.showError('Workflow unavailable', err);
    }
}

function renderWorkflowDetail(w) {
    // Header
    document.getElementById('workflow-name').textContent = w.name;
    document.getElementById('workflow-score').textContent = w.ghost_score;
    document.getElementById('workflow-grade').textContent = scoreToGrade(w.ghost_score);
    document.getElementById('workflow-from').textContent = w.discovered_from === 'freshdesk_tickets'
        ? 'Observed in live Freshdesk tickets.' : 'Observed in available activity metadata.';

    // Metrics
    document.getElementById('metric-frequency').textContent = `${w.frequency} occurrences`;
    document.getElementById('metric-automation').textContent = `${Math.round(w.automation_percentage)}%`;
    document.getElementById('metric-duration').textContent = formatDuration(w.average_duration_seconds);
    const risk = ['low', 'medium', 'high'].includes(w.risk_level) ? w.risk_level : 'medium';
    document.getElementById('metric-risk').innerHTML = `<span class="risk-badge risk-${risk}">${risk} risk</span>`;

    renderWorkflowPath(w);

    // GhostScore Breakdown
    renderBreakdown(w.ghost_score_breakdown);

    // Automation decision is made server-side (deterministic playbook check)
    if (w.automation) {
        document.getElementById('decision-label').innerHTML =
            `<span class="risk-badge ${w.automation.automatable ? 'risk-low' : 'risk-medium'}">` +
            `${w.automation.automatable ? 'Automatable' : 'Human review'}</span>`;
        document.getElementById('decision-reason').textContent = w.automation.reason;
        document.getElementById('decision-section').classList.remove('hidden');
    }

    // Autonomy Boundary (Refund Verification only)
    if (w.name.toLowerCase().includes('refund')) {
        document.getElementById('autonomy-section').classList.remove('hidden');
    }

    // Runnable playbook: works with live Freshdesk and with the fallback data.
    if (w.name === 'Refund Verification' && w.automation?.automatable !== false) {
        document.getElementById('run-section').classList.remove('hidden');
    }

    // Show content
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('content').classList.remove('hidden');
}

function renderWorkflowPath(workflow) {
    if (!workflow.step_signatures || workflow.step_signatures.length === 0) {
        document.getElementById('ghostgraph').innerHTML = '<p>No workflow sequence available.</p>';
        return;
    }

    const refundPath = workflow.automation?.automatable && workflow.name.toLowerCase().includes('refund');
    const steps = refundPath
        ? ['Freshdesk ticket', 'Context', 'Billing', 'Policy', 'Risk assessment', 'Human approval', 'Freshdesk update', 'Verification', 'Ticket closure'].map(label => ({tool: label, action: ''}))
        : workflow.step_signatures.map(sig => { const [tool, action] = sig.split(':'); return {tool, action}; });
    document.getElementById('workflow-path-description').textContent = refundPath
        ? 'Approved refund automation path. Human approval is required above ₹25,000.'
        : 'Observed process from connected activity.';

    let html = '<div class="graph-nodes">';

    steps.forEach((step, idx) => {
        const category = categorizeStep(step.tool);
        html += `
            <div class="graph-node ${category}">
                <span class="node-tool">${escapeHtml(stepLabel(step.tool))}</span>
                ${step.action ? `<span class="node-action">${escapeHtml(step.action.replaceAll('_', ' '))}</span>` : ''}
            </div>
        `;

        if (idx < steps.length - 1) {
            html += '<div class="graph-arrow" aria-hidden="true">→</div>';
        }
    });

    html += '</div>';
    document.getElementById('ghostgraph').innerHTML = html;
}

function categorizeStep(tool) {
    const tool_lower = tool.toLowerCase();
    if (tool_lower.includes('freshdesk')) return 'category-source';
    if (tool_lower.includes('approval') || tool_lower.includes('review')) return 'category-approval';
    if (tool_lower.includes('policy')) return 'category-policy';
    if (tool_lower.includes('crm') || tool_lower.includes('billing')) return 'category-lookup';
    return 'category-default';
}

function stepLabel(tool) {
    const labels = {freshdesk: 'Freshdesk ticket', ghostwork: 'GhostWork', context_agent: 'Context',
        billing_agent: 'Billing', policy_agent: 'Policy', risk_agent: 'Risk assessment',
        approval_gate: 'Human approval', communication_agent: 'Freshdesk update',
        verification_agent: 'Verification', closure_agent: 'Ticket closure',
        diagnosis_agent: 'Diagnosis', it_communication_agent: 'Freshdesk reply',
        it_verification_agent: 'Verification', it_closure_agent: 'Ticket resolution'};
    return labels[tool.toLowerCase()] || tool.replaceAll('_', ' ');
}

function renderBreakdown(breakdown) {
    if (!breakdown) return;

    const components = [
        { name: 'Frequency', value: breakdown.frequency, weight: 25 },
        { name: 'Repeatability', value: breakdown.repeatability, weight: 25 },
        { name: 'Manual Effort', value: breakdown.manual_effort, weight: 20 },
        { name: 'Automation Potential', value: breakdown.automation_potential, weight: 20 },
        { name: 'Risk Factor', value: breakdown.risk_penalty, weight: 10 },
    ];

    let html = '';
    components.forEach(comp => {
        const percentage = (comp.value / 100) * 100;
        html += `
            <div class="breakdown-item">
                <div class="breakdown-header">
                    <span class="comp-name">${comp.name}</span>
                    <span class="comp-score">${comp.value}/100</span>
                </div>
                <div class="breakdown-bar">
                    <div class="breakdown-fill" style="width: ${percentage}%"></div>
                </div>
                <span class="comp-weight">${comp.weight}% weight</span>
            </div>
        `;
    });

    document.getElementById('breakdown-components').innerHTML = html;
}

function scoreToGrade(score) {
    if (score >= 85) return 'A';
    if (score >= 70) return 'B';
    if (score >= 55) return 'C';
    if (score >= 40) return 'D';
    return 'F';
}

function formatDuration(seconds) {
    if (seconds < 60) return Math.round(seconds) + 's';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return minutes + 'm';
    const hours = Math.round(minutes / 60);
    return hours + 'h';
}

async function runDemoTicket() {
    const button = document.getElementById('run-demo-btn');
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = 'Starting...';
    try {
        // Discovery IDs describe observed patterns; executable workflow IDs come from /api/workflows.
        const data = await api.getWorkflows();
        const refund = (data.workflows || []).find(item => item.name === 'Refund Verification');
        if (!refund) throw new Error('Refund Verification workflow is unavailable');
        // No ticket_id: the server uses the configured demo ticket and its checks.
        const execution = await api.createExecution({ workflow_id: refund.id });
        window.location.href = `/execution/${Number(execution.id)}`;
    } catch (error) {
        ui.showError('Could not start the automation', error);
        button.disabled = false;
        button.textContent = originalText;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('run-demo-btn').addEventListener('click', runDemoTicket);
    loadWorkflowDetail();
});
