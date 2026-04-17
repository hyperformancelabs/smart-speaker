import { CONFIG } from './config.js';

const getNfcTagId = () => localStorage.getItem('nfcTagId');
const encodeSessionNfcTagId = () => {
    const nfcTagId = getNfcTagId();
    if (!nfcTagId) {
        throw new Error('No active user session');
    }
    return encodeURIComponent(nfcTagId);
};

const buildDurationString = (input) => {
    if (typeof input?.duration === 'string' && input.duration.trim()) {
        return input.duration.trim();
    }

    const totalSeconds = Number(input?.duration_seconds);
    if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) {
        return '';
    }

    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const parts = [];

    if (hours) parts.push(`${hours}h`);
    if (minutes) parts.push(`${minutes}m`);
    if (seconds || parts.length === 0) parts.push(`${seconds}s`);
    return parts.join('');
};

async function fetchAPI(endpoint, method = 'GET', body = null) {
    const options = {
        method,
        headers: {},
    };

    if (body !== null) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
    }

    const response = await fetch(`${CONFIG.API_BASE_URL}${endpoint}`, options);
    const contentType = response.headers.get('content-type') || '';
    const payload = contentType.includes('application/json')
        ? await response.json().catch(() => ({}))
        : await response.text().catch(() => '');

    if (!response.ok) {
        const message = payload?.error || payload?.message || `API Error: ${response.status}`;
        const error = new Error(message);
        error.status = response.status;
        error.payload = payload;
        throw error;
    }

    return payload;
}

export const AuthAPI = {
    login: (data) => fetchAPI('/api/auth/login', 'POST', data),
    signup: (data) => fetchAPI('/api/users/register', 'POST', data)
};

export const AlarmAPI = {
    getAll: async () => (await fetchAPI(`/api/users/${encodeSessionNfcTagId()}/alarms`)).alarms || [],
    create: (data) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/alarms`, 'POST', data),
    update: (id, data) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/alarms/${id}`, 'PATCH', data),
    updateStatus: (id, enabled) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/alarms/${id}`, 'PATCH', { enabled }),
    delete: (id) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/alarms/${id}`, 'DELETE')
};

export const ProfileAPI = {
    get: () => fetchAPI(`/api/users/${encodeSessionNfcTagId()}`),
    updateField: (field, value, replace = false) =>
        fetchAPI(`/api/users/${encodeSessionNfcTagId()}/update`, 'PATCH', { field, value, replace })
};

export const TimerAPI = {
    getAll: async () => (await fetchAPI(`/api/users/${encodeSessionNfcTagId()}/timers`)).timers || [],
    create: (data) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/timers`, 'POST', {
        label: data?.label || 'Timer',
        duration: buildDurationString(data),
    }),
    delete: (id) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/timers/${id}`, 'DELETE')
};

export const ListAPI = {
    getAll: async () => (await fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists`)).lists || [],
    createList: (listName) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists`, 'POST', { list_name: listName }),
    renameList: (listId, listName) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists/${listId}`, 'PATCH', { list_name: listName }),
    deleteList: (listId) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists/${listId}`, 'DELETE'),
    addNote: (listId, content) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists/${listId}/items`, 'POST', { item: content }),
    updateNote: (listId, itemId, content) =>
        fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists/${listId}/items/${itemId}`, 'PATCH', { item: content }),
    updateNoteCompleted: (listId, itemId, completed) =>
        fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists/${listId}/items/${itemId}`, 'PATCH', { completed }),
    deleteNote: (listId, itemId) => fetchAPI(`/api/users/${encodeSessionNfcTagId()}/lists/${listId}/items/${itemId}`, 'DELETE')
};

export const MediaAPI = {
    getAll: async () => []
};
