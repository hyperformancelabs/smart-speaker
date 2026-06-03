import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL } from './config';

// ---------------------------------------------------------------------------
// Session helpers
// ---------------------------------------------------------------------------

async function getNfcTagId(): Promise<string> {
  const nfc = await AsyncStorage.getItem('nfcTagId');
  if (!nfc) throw new Error('No active user session');
  return encodeURIComponent(nfc);
}

// ---------------------------------------------------------------------------
// Mock Store for demo/mock mode
// ---------------------------------------------------------------------------
let mockProfile: UserProfile = {
  user_id: 'mock-user-id-123',
  nfc_tag_id: 'mock-nfc-tag-id-123',
  name: 'Người dùng thử nghiệm',
  user_name: 'demo_user',
};

let mockAlarms: Alarm[] = [
  {
    alarm_id: 'mock-alarm-1',
    time: '07:00:00',
    label: 'Thức dậy đi làm',
    repeat: 'daily',
    enabled: true,
    schedule_type: 'time',
    scheduled_for: null,
    offset_seconds: null,
  },
  {
    alarm_id: 'mock-alarm-2',
    time: '08:30:00',
    label: 'Họp Daily',
    repeat: 'once',
    enabled: false,
    schedule_type: 'time',
    scheduled_for: null,
    offset_seconds: null,
  },
  {
    alarm_id: 'mock-alarm-3',
    time: null,
    label: 'Nhắc nhở uống nước',
    repeat: 'once',
    enabled: true,
    schedule_type: 'relative',
    scheduled_for: null,
    offset_seconds: 3600,
  },
];

let mockTimers: Timer[] = [
  {
    timer_id: 'mock-timer-1',
    label: 'Luộc trứng',
    duration_seconds: 300,
    started_at: new Date().toISOString(),
    active: true,
  },
  {
    timer_id: 'mock-timer-2',
    label: 'Tập Planks',
    duration_seconds: 120,
    started_at: new Date().toISOString(),
    active: false,
  },
];

let mockLists: NoteList[] = [
  {
    list_id: 'mock-list-1',
    list_name: 'Việc cần làm hôm nay',
    items: [
      { item_id: 'mock-item-1', content: 'Thiết kế giao diện mobile', completed: true },
      { item_id: 'mock-item-2', content: 'Tích hợp Mock API', completed: false },
      { item_id: 'mock-item-3', content: 'Kiểm thử các màn hình', completed: false },
    ],
  },
  {
    list_id: 'mock-list-2',
    list_name: 'Danh sách đi siêu thị',
    items: [
      { item_id: 'mock-item-4', content: 'Sữa tươi', completed: false },
      { item_id: 'mock-item-5', content: 'Trứng gà', completed: true },
    ],
  },
];

let mockMedia: MediaItem[] = [
  {
    media_id: 'mock-media-1',
    title: 'Chúng Ta Của Tương Lai - Sơn Tùng M-TP',
    source: 'Youtube',
    public_stream_url: 'https://youtube.com',
    webpage_url: 'https://youtube.com',
    last_played_at: new Date().toISOString(),
    play_count: 5,
  },
  {
    media_id: 'mock-media-2',
    title: 'Nhạc lofi thư giãn học tập',
    source: 'SoundCloud',
    public_stream_url: 'https://soundcloud.com',
    webpage_url: 'https://soundcloud.com',
    last_played_at: new Date(Date.now() - 3600000).toISOString(),
    play_count: 12,
  },
];

async function isMockMode(): Promise<boolean> {
  try {
    const nfc = await AsyncStorage.getItem('nfcTagId');
    return nfc === 'mock-nfc-tag-id-123';
  } catch {
    return false;
  }
}


function buildDurationString(input: {
  duration?: string;
  duration_seconds?: number;
}): string {
  if (typeof input.duration === 'string' && input.duration.trim()) {
    return input.duration.trim();
  }

  const totalSeconds = Number(input.duration_seconds);
  if (!Number.isFinite(totalSeconds) || totalSeconds <= 0) return '';

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const parts: string[] = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (seconds || parts.length === 0) parts.push(`${seconds}s`);
  return parts.join('');
}

// ---------------------------------------------------------------------------
// Generic fetch wrapper
// ---------------------------------------------------------------------------

async function fetchAPI<T = any>(
  endpoint: string,
  method: string = 'GET',
  body: Record<string, any> | null = null,
): Promise<T> {
  const options: RequestInit = {
    method,
    headers: {} as Record<string, string>,
  };

  if (body !== null) {
    (options.headers as Record<string, string>)['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => '');

  if (!response.ok) {
    const message =
      (payload as any)?.error || (payload as any)?.message || `API Error: ${response.status}`;
    const error: any = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload as T;
}

// ---------------------------------------------------------------------------
// Auth API
// ---------------------------------------------------------------------------

export const AuthAPI = {
  login: (data: { user_name: string; user_password: string }) =>
    fetchAPI<{
      user_id: string;
      nfc_tag_id: string;
      user_name: string;
      name: string;
    }>('/api/auth/login', 'POST', data),

  signup: (data: {
    nfc_tag_id: string;
    name: string;
    user_name: string;
    user_password: string;
  }) => fetchAPI('/api/users/register', 'POST', data),
};

// ---------------------------------------------------------------------------
// Alarm API
// ---------------------------------------------------------------------------

export interface Alarm {
  alarm_id: string;
  time: string | null;
  label: string;
  repeat: string;
  enabled: boolean;
  schedule_type: string;
  scheduled_for: string | null;
  offset_seconds: number | null;
}

export const AlarmAPI = {
  getAll: async (): Promise<Alarm[]> => {
    if (await isMockMode()) return mockAlarms;
    const nfc = await getNfcTagId();
    const res = await fetchAPI<{ alarms: Alarm[] }>(`/api/users/${nfc}/alarms`);
    return res.alarms || [];
  },
  create: async (data: Record<string, any>) => {
    if (await isMockMode()) {
      const newAlarm: Alarm = {
        alarm_id: `mock-alarm-${Date.now()}`,
        time: data.time || null,
        label: data.label || 'Báo thức',
        repeat: data.repeat || 'once',
        enabled: true,
        schedule_type: data.schedule_type || 'time',
        scheduled_for: data.scheduled_for || null,
        offset_seconds: data.offset_seconds || null,
      };
      mockAlarms = [newAlarm, ...mockAlarms];
      return newAlarm;
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/alarms`, 'POST', data);
  },
  update: async (id: string, data: Record<string, any>) => {
    if (await isMockMode()) {
      mockAlarms = mockAlarms.map((a) =>
        a.alarm_id === id ? { ...a, ...data } : a
      );
      return mockAlarms.find((a) => a.alarm_id === id);
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/alarms/${id}`, 'PATCH', data);
  },
  updateStatus: async (id: string, enabled: boolean) => {
    if (await isMockMode()) {
      mockAlarms = mockAlarms.map((a) =>
        a.alarm_id === id ? { ...a, enabled } : a
      );
      return mockAlarms.find((a) => a.alarm_id === id);
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/alarms/${id}`, 'PATCH', { enabled });
  },
  delete: async (id: string) => {
    if (await isMockMode()) {
      mockAlarms = mockAlarms.filter((a) => a.alarm_id !== id);
      return { success: true };
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/alarms/${id}`, 'DELETE');
  },
};

// ---------------------------------------------------------------------------
// Timer API
// ---------------------------------------------------------------------------

export interface Timer {
  timer_id: string;
  label: string;
  duration_seconds: number;
  started_at: string;
  active: boolean;
}

export const TimerAPI = {
  getAll: async (): Promise<Timer[]> => {
    if (await isMockMode()) return mockTimers;
    const nfc = await getNfcTagId();
    const res = await fetchAPI<{ timers: Timer[] }>(`/api/users/${nfc}/timers`);
    return res.timers || [];
  },
  create: async (data: { label?: string; duration_seconds?: number; duration?: string }) => {
    if (await isMockMode()) {
      let secs = data.duration_seconds || 0;
      if (data.duration) {
        const match = data.duration.match(/^(\d+)(h|m|s)?$/);
        if (match) {
          const val = parseInt(match[1]);
          const unit = match[2];
          if (unit === 'h') secs = val * 3600;
          else if (unit === 'm') secs = val * 60;
          else secs = val;
        }
      }
      const newTimer: Timer = {
        timer_id: `mock-timer-${Date.now()}`,
        label: data.label || 'Timer',
        duration_seconds: secs,
        started_at: new Date().toISOString(),
        active: true,
      };
      mockTimers = [newTimer, ...mockTimers];
      return newTimer;
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/timers`, 'POST', {
      label: data.label || 'Timer',
      duration: buildDurationString(data),
    });
  },
  delete: async (id: string) => {
    if (await isMockMode()) {
      mockTimers = mockTimers.filter((t) => t.timer_id !== id);
      return { success: true };
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/timers/${id}`, 'DELETE');
  },
};

// ---------------------------------------------------------------------------
// List / Notes API
// ---------------------------------------------------------------------------

export interface NoteItem {
  item_id: string;
  content: string;
  completed: boolean;
}

export interface NoteList {
  list_id: string;
  list_name: string;
  items: NoteItem[];
}

export const ListAPI = {
  getAll: async (): Promise<NoteList[]> => {
    if (await isMockMode()) return mockLists;
    const nfc = await getNfcTagId();
    const res = await fetchAPI<{ lists: NoteList[] }>(`/api/users/${nfc}/lists`);
    return res.lists || [];
  },
  createList: async (listName: string) => {
    if (await isMockMode()) {
      const newList: NoteList = {
        list_id: `mock-list-${Date.now()}`,
        list_name: listName,
        items: [],
      };
      mockLists = [newList, ...mockLists];
      return newList;
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/lists`, 'POST', { list_name: listName });
  },
  renameList: async (listId: string, listName: string) => {
    if (await isMockMode()) {
      mockLists = mockLists.map((l) =>
        l.list_id === listId ? { ...l, list_name: listName } : l
      );
      return mockLists.find((l) => l.list_id === listId);
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/lists/${listId}`, 'PATCH', { list_name: listName });
  },
  deleteList: async (listId: string) => {
    if (await isMockMode()) {
      mockLists = mockLists.filter((l) => l.list_id !== listId);
      return { success: true };
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/lists/${listId}`, 'DELETE');
  },
  addNote: async (listId: string, content: string) => {
    if (await isMockMode()) {
      const newItem: NoteItem = {
        item_id: `mock-item-${Date.now()}`,
        content,
        completed: false,
      };
      mockLists = mockLists.map((l) =>
        l.list_id === listId ? { ...l, items: [...l.items, newItem] } : l
      );
      return newItem;
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/lists/${listId}/items`, 'POST', { item: content });
  },
  updateNote: async (listId: string, itemId: string, content: string) => {
    if (await isMockMode()) {
      mockLists = mockLists.map((l) => {
        if (l.list_id === listId) {
          return {
            ...l,
            items: l.items.map((i) =>
              i.item_id === itemId ? { ...i, content } : i
            ),
          };
        }
        return l;
      });
      return { success: true };
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/lists/${listId}/items/${itemId}`, 'PATCH', {
      item: content,
    });
  },
  updateNoteCompleted: async (listId: string, itemId: string, completed: boolean) => {
    if (await isMockMode()) {
      mockLists = mockLists.map((l) => {
        if (l.list_id === listId) {
          return {
            ...l,
            items: l.items.map((i) =>
              i.item_id === itemId ? { ...i, completed } : i
            ),
          };
        }
        return l;
      });
      return { success: true };
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/lists/${listId}/items/${itemId}`, 'PATCH', { completed });
  },
  deleteNote: async (listId: string, itemId: string) => {
    if (await isMockMode()) {
      mockLists = mockLists.map((l) => {
        if (l.list_id === listId) {
          return {
            ...l,
            items: l.items.filter((i) => i.item_id !== itemId),
          };
        }
        return l;
      });
      return { success: true };
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/lists/${listId}/items/${itemId}`, 'DELETE');
  },
};

// ---------------------------------------------------------------------------
// Media API
// ---------------------------------------------------------------------------

export interface MediaItem {
  media_id: string;
  title: string;
  source: string;
  public_stream_url: string;
  webpage_url: string;
  last_played_at: string;
  play_count: number;
}

export const MediaAPI = {
  getAll: async (): Promise<MediaItem[]> => {
    if (await isMockMode()) return mockMedia;
    const nfc = await getNfcTagId();
    const res = await fetchAPI<{ media_history: MediaItem[] }>(
      `/api/users/${nfc}/media-history`,
    );
    return res.media_history || [];
  },
  delete: async (id: string) => {
    if (await isMockMode()) {
      mockMedia = mockMedia.filter((m) => m.media_id !== id);
      return { success: true };
    }
    const nfc = await getNfcTagId();
    return fetchAPI(`/api/users/${nfc}/media-history/${id}`, 'DELETE');
  },
};

// ---------------------------------------------------------------------------
// Profile API
// ---------------------------------------------------------------------------

export interface UserProfile {
  user_id: string;
  nfc_tag_id: string;
  name: string;
  user_name: string;
}

export const ProfileAPI = {
  get: async (): Promise<UserProfile> => {
    if (await isMockMode()) return mockProfile;
    const nfc = await getNfcTagId();
    return fetchAPI<UserProfile>(`/api/users/${nfc}`);
  },
  updateField: async (field: string, value: any, replace = false) => {
    if (await isMockMode()) {
      if (field === 'name') mockProfile.name = value;
      if (field === 'user_name') mockProfile.user_name = value;
      return mockProfile;
    }
    const nfc = await getNfcTagId();
    return fetchAPI<UserProfile>(`/api/users/${nfc}/update`, 'PATCH', {
      field,
      value,
      replace,
    });
  },
};
