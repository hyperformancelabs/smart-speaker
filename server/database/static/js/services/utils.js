export function getToastContainer() {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    return container;
}

export function showToast(message, type = 'success') {
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let icon = '<i class="fa-solid fa-circle-check"></i>';
    if(type === 'error') icon = '<i class="fa-solid fa-circle-exclamation"></i>';
    
    toast.innerHTML = `${icon} <span>${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('fade-out');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

export function showConfirm(message, onConfirm) {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
        <div class="confirm-modal panel">
            <p>${message}</p>
            <div class="confirm-actions">
                <button class="btn-secondary" id="btn-cancel">Hủy</button>
                <button class="btn-primary" id="btn-confirm">Xác nhận</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
    
    document.getElementById('btn-cancel').onclick = () => overlay.remove();
    document.getElementById('btn-confirm').onclick = () => {
        overlay.remove();
        onConfirm();
    };
}
