async function loadIntegrations() {
    const loading = document.getElementById('loading');
    const error = document.getElementById('error');
    const content = document.getElementById('content');
    loading.classList.remove('hidden'); error.classList.add('hidden'); content.classList.add('hidden');
    try {
        const data = await api.getIntegrations();
        if (!data.configured || typeof data.configured !== 'object') throw new Error('Integration status is unavailable.');
        renderIntegrations(data);
        content.classList.remove('hidden');
    } catch (cause) { error.classList.remove('hidden'); ui.showError('Integrations unavailable', cause); }
    finally { loading.classList.add('hidden'); }
}

function renderIntegrations(data) {
    const configured = data.configured || {};
    const integrations = [
        {id:'freshdesk', name:'Freshdesk', description:'Ticket read, write-back and independent verification'},
        {id:'supabase', name:'Supabase', description:'Workflow, execution and approval records'},
        {id:'claude', name:'Claude', description:'Policy interpretation and response drafting'},
        {id:'vobiz', name:'Vobiz', description:'Outbound approval calls'},
        {id:'sarvam', name:'Sarvam', description:'Voice prompts and speech recognition'}
    ];
    document.getElementById('integrations-grid').innerHTML = integrations.map(integration => {
        const value = configured[integration.id];
        const ready = integration.id === 'freshdesk' ? value?.configured === true : value === true;
        const providerName = value?.provider === 'mcp' ? 'MCP' : value?.provider === 'rest' ? 'REST' : 'Unknown';
        const provider = integration.id === 'freshdesk' && value?.provider
            ? `<p class="fallback-note">Selected provider: ${providerName}</p>` : '';
        return `<article class="integration-card"><h3 class="card-title">${integration.name}</h3><p class="card-description">${integration.description}</p><span class="integration-status ${ready ? 'status-configured' : 'status-not-configured'}">${ready ? 'Configured' : 'Not configured'}</span>${provider}</article>`;
    }).join('');
}

document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('retry-btn').addEventListener('click', loadIntegrations);
    loadIntegrations();
});
