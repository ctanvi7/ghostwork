/**
 * Integrations page - load and render integration status
 */

async function loadIntegrations() {
    try {
        const res = await fetch('/api/integrations');
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        if (!data.configured || typeof data.configured !== 'object') {
            throw new Error('Invalid integrations response format');
        }
        renderIntegrations(data);

        document.getElementById('loading').style.display = 'none';
        document.getElementById('content').style.display = 'block';

    } catch (err) {
        console.error('Integrations load error:', err);
        document.getElementById('loading').style.display = 'none';
        document.getElementById('error').style.display = 'block';
    }
}

function renderIntegrations(data) {
    const gridEl = document.getElementById('integrations-grid');
    const configured = data.configured || {};

    const integrations = [
        { id: 'claude', name: 'Claude', icon: '🤖', description: 'AI reasoning for policy interpretation' },
        { id: 'freshdesk', name: 'Freshdesk', icon: '🎫', description: 'Ticket and customer data' },
        { id: 'supabase', name: 'Supabase', icon: '🗄️', description: 'Execution state and persistence' },
        { id: 'vobiz', name: 'Vobiz', icon: '📱', description: 'Voice-based approvals (Phase 11)' },
        { id: 'sarvam', name: 'Sarvam', icon: '🎤', description: 'Speech recognition & synthesis (Phase 11)' },
    ];

    gridEl.innerHTML = integrations.map(integration => {
        const isConfigured = configured[integration.id];
        const status = isConfigured ? 'Configured' : 'Not configured';
        const statusClass = isConfigured ? 'status-configured' : 'status-not-configured';

        return `
            <div class="integration-card">
                <div class="card-icon">${integration.icon}</div>
                <h3 class="card-title">${integration.name}</h3>
                <p class="card-description">${integration.description}</p>
                <span class="integration-status ${statusClass}">${status}</span>
                ${!isConfigured && integration.id === 'freshdesk' ?
                    '<p class="fallback-note">Demo fallback active</p>'
                    : ''}
            </div>
        `;
    }).join('');
}

document.addEventListener('DOMContentLoaded', function() {
    loadIntegrations();

    // Add retry button listener if it exists
    const retryBtn = document.getElementById('retry-btn');
    if (retryBtn) {
        retryBtn.addEventListener('click', function() {
            document.getElementById('error').style.display = 'none';
            loadIntegrations();
        });
    }
});
