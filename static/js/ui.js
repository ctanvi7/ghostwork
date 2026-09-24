/**
 * Common UI utilities for GhostWork frontend
 */

const ui = (() => {
    function showError(title, error) {
        const message = error?.message || String(error);

        // Create alert element
        const alert = document.createElement('div');
        alert.className = 'alert alert-error';
        const closeBtn = document.createElement('button');
        closeBtn.className = 'alert-close';
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', () => alert.remove());

        const content = document.createElement('div');
        content.className = 'alert-content';
        content.innerHTML = `
            <strong>${escapeHtml(title)}</strong>
            <p>${escapeHtml(message)}</p>
        `;

        alert.appendChild(content);
        alert.appendChild(closeBtn);

        // Insert at top of main content
        const main = document.querySelector('.app-main');
        if (main) {
            main.insertBefore(alert, main.firstChild);
        } else {
            document.body.insertBefore(alert, document.body.firstChild);
        }

        // Auto-dismiss after 10 seconds
        setTimeout(() => {
            if (alert.parentElement) {
                alert.remove();
            }
        }, 10000);
    }

    function showSuccess(message) {
        // Create alert element
        const alert = document.createElement('div');
        alert.className = 'alert alert-success';
        const closeBtn = document.createElement('button');
        closeBtn.className = 'alert-close';
        closeBtn.textContent = '×';
        closeBtn.addEventListener('click', () => alert.remove());

        const content = document.createElement('div');
        content.className = 'alert-content';
        content.innerHTML = `<p>${escapeHtml(message)}</p>`;

        alert.appendChild(content);
        alert.appendChild(closeBtn);

        // Insert at top of main content
        const main = document.querySelector('.app-main');
        if (main) {
            main.insertBefore(alert, main.firstChild);
        } else {
            document.body.insertBefore(alert, document.body.firstChild);
        }

        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            if (alert.parentElement) {
                alert.remove();
            }
        }, 5000);
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    return {
        showError,
        showSuccess
    };
})();

/**
 * Helper to escape HTML in templates
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
