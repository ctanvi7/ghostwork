document.addEventListener('DOMContentLoaded', () => {
    const shell = document.getElementById('app-shell');
    const sidebar = document.getElementById('sidebar');
    const toggle = document.getElementById('sidebar-toggle');
    if (!shell || !sidebar || !toggle) return;
    const compact = window.matchMedia('(max-width: 1000px)');
    function update() {
        const expanded = compact.matches ? sidebar.classList.contains('is-open') : !shell.classList.contains('is-collapsed');
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.setAttribute('aria-label', expanded ? 'Collapse sidebar' : 'Expand sidebar');
    }
    if (!compact.matches && sessionStorage.getItem('ghostwork-sidebar-collapsed') === 'true') {
        shell.classList.add('is-collapsed');
    }
    toggle.addEventListener('click', () => {
        if (compact.matches) sidebar.classList.toggle('is-open');
        else {
            shell.classList.toggle('is-collapsed');
            sessionStorage.setItem('ghostwork-sidebar-collapsed', String(shell.classList.contains('is-collapsed')));
        }
        update();
    });
    compact.addEventListener('change', update);
    update();
});
