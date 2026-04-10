import { renderLogin, renderSignup } from './pages/AuthPage.js';
import { loadDashboard } from './pages/DashboardPage.js';

document.addEventListener("DOMContentLoaded", () => {
    const userId = localStorage.getItem('userId');
    const urlParams = new URLSearchParams(window.location.search);
    
    // Nếu từ NFC quét sang, URL có thể là ?action=signup
    if (urlParams.get('action') === 'signup') {
        renderSignup();
        return;
    }

    if (userId) {
        loadDashboard();
    } else {
        renderLogin();
    }
});