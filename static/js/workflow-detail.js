/**
 * Workflow detail page - load and render workflow details with GhostGraph
 */

const workflowId = new URLSearchParams(window.location.search).get('id');

async function loadWorkflowDetail() {
    try {
        const res = await fetch(`/api/discovery/workflows/${workflowId}`);
        if (!res.ok) {
            if (res.status === 404) throw new Error('Workflow not found');
            throw new Error('Failed to load workflow');
        }

        const workflow = await res.json();
        renderWorkflowDetail(workflow);

    } catch (err) {
        console.error('Workflow detail error:', err);
        document.getElementById('loading').style.display = 'none';
        document.getElementById('error').style.display = 'block';
    }
}

function renderWorkflowDetail(w) {
    // Header
    document.getElementById('workflow-name').textContent = w.name;
    document.getElementById('workflow-score').textContent = w.ghost_score;
    document.getElementById('workflow-grade').textContent = scoreToGrade(w.ghost_score);

    // Metrics
    document.getElementById('metric-frequency').textContent = `${w.frequency} occurrences`;
    document.getElementById('metric-automation').textContent = `${Math.round(w.automation_percentage)}%`;
    document.getElementById('metric-duration').textContent = formatDuration(w.average_duration_seconds);
    document.getElementById('metric-risk').innerHTML = `<span class="risk-badge risk-${w.risk_level}">${w.risk_level}</span>`;

    // GhostGraph
    renderGhostGraph(w);

    // GhostScore Breakdown
    renderBreakdown(w.ghost_score_breakdown);

    // Autonomy Boundary (Refund Verification only)
    if (w.name.toLowerCase().includes('refund')) {
        document.getElementById('autonomy-section').style.display = 'block';
    }

    // Show content
    document.getElementById('loading').style.display = 'none';
    document.getElementById('content').style.display = 'block';
}

function renderGhostGraph(workflow) {
    if (!workflow.step_signatures || workflow.step_signatures.length === 0) {
        document.getElementById('ghostgraph').innerHTML = '<p>No workflow sequence available.</p>';
        return;
    }

    const steps = workflow.step_signatures.map(sig => {
        const [tool, action] = sig.split(':');
        return { tool, action };
    });

    let html = '<div class="graph-nodes">';

    steps.forEach((step, idx) => {
        const category = categorizeStep(step.tool);
        html += `
            <div class="graph-node ${category}">
                <span class="node-tool">${escapeHtml(step.tool)}</span>
                <span class="node-action">${escapeHtml(step.action)}</span>
            </div>
        `;

        if (idx < steps.length - 1) {
            html += '<div class="graph-arrow">↓</div>';
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

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', loadWorkflowDetail);
