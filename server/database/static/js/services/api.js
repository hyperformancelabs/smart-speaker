import { CONFIG } from './config.js';

// Lấy userId và token (giả lập) từ LocalStorage sau khi Login
const getUserId = () => localStorage.getItem('userId');
const getHeaders = () => ({
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${localStorage.getItem('token')}` // Nếu hệ thống dùng token
});

// Hàm fetch wrapper cơ bản
async function fetchAPI(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: getHeaders(),
    };
    if (body) options.body = JSON.stringify(body);

    const response = await fetch(`${CONFIG.API_BASE_URL}${endpoint}`, options);
    if (!response.ok) {
        throw new Error(`API Error: ${response.status}`);
    }
    return response.json();
}

// --- XUẤT CÁC API DỰA TRÊN CONTRACT ---

export const AuthAPI = {
    login: (data) => fetchAPI('/api/auth/login', 'POST', data),
    loginQR: (qrToken) => fetchAPI('/api/auth/login-qr', 'POST', { token: qrToken }),
    signup: (data) => fetchAPI('/api/users/register', 'POST', data)
};

export const AlarmAPI = {
    getAll: () => fetchAPI(`/api/users/${getUserId()}/alarms`),
    create: (data) => fetchAPI(`/api/users/${getUserId()}/alarms`, 'POST', data),
    updateStatus: (id, enabled) => fetchAPI(`/api/users/${getUserId()}/alarms/${id}`, 'PATCH', { repeat: enabled ? 'daily' : 'once' }), // Appending behavior to existing DB format
    delete: (id) => fetchAPI(`/api/users/${getUserId()}/alarms/${id}`, 'DELETE')
};

export const ProfileAPI = {
    get: () => fetchAPI(`/api/users/${getUserId()}`),
    updateField: (field, value) => fetchAPI(`/api/users/${getUserId()}/update`, 'PATCH', { field, value })
};

export const TimerAPI = {
    getAll: () => fetchAPI(`/api/users/${getUserId()}/timers`),
    create: (data) => fetchAPI(`/api/users/${getUserId()}/timers`, 'POST', data),
    delete: (id) => fetchAPI(`/api/users/${getUserId()}/timers/${id}`, 'DELETE')
};

export const ListAPI = {
    getAll: () => fetchAPI(`/api/users/${getUserId()}/lists`),
    createList: (list_name) => fetchAPI(`/api/users/${getUserId()}/lists`, 'POST', { list_name }),
    deleteList: (listId) => fetchAPI(`/api/users/${getUserId()}/lists/${listId}`, 'DELETE'),
    addNote: (listId, content) => fetchAPI(`/api/users/${getUserId()}/lists/${listId}/items`, 'POST', { item: content }),
    deleteNote: (listId, itemId) => fetchAPI(`/api/users/${getUserId()}/lists/${listId}/items/${itemId}`, 'DELETE')
};

export const MediaAPI = {
    getAll: () => fetchAPI(`/api/users/${getUserId()}/media`)
};