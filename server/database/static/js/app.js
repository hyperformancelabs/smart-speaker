import { renderLogin, renderSignup } from './pages/AuthPage.js';
import { loadDashboard } from './pages/DashboardPage.js';

if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
        navigator.serviceWorker.register("/static/js/sw.js").catch(() => {
            // PWA là tiện ích bổ sung, không chặn app nếu đăng ký thất bại.
        });
    });
}

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
