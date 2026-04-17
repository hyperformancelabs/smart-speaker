import { renderLogin, renderSignup } from './pages/AuthPage.js';
import { loadDashboard } from './pages/DashboardPage.js';

document.addEventListener("DOMContentLoaded", () => {
    const nfcTagId = localStorage.getItem('nfcTagId');
    const urlParams = new URLSearchParams(window.location.search);

    if (urlParams.get('action') === 'signup' && urlParams.get('nfc_tag_id')) {
        renderSignup();
        return;
    }

    if (nfcTagId) {
        loadDashboard();
    } else {
        renderLogin();
    }
});
