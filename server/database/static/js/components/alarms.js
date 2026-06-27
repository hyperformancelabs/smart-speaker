import { AlarmAPI } from '../services/api.js';
import { showToast, showConfirm } from '../services/utils.js';

let cachedAlarms = null;

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function getAlarmById(alarmId) {
    return (cachedAlarms || []).find((alarm) => (alarm.alarm_id || alarm.id) === alarmId);
}

function formatAlarmTime(alarm) {
    if (alarm.schedule_type === 'datetime' && alarm.scheduled_for) {
        return new Date(alarm.scheduled_for).toLocaleString('vi-VN', {
            hour: '2-digit',
            minute: '2-digit',
            day: '2-digit',
            month: '2-digit',
        });
    }
    if (alarm.schedule_type === 'relative' && Number.isFinite(alarm.offset_seconds)) {
        return `+${alarm.offset_seconds}s`;
    }
    return alarm.time ? alarm.time.substring(0, 5) : '--:--';
}

function repeatLabel(repeat) {
    if (repeat === 'daily') return 'Hàng ngày';
    if (repeat === 'weekly') return 'Hàng tuần';
    return '1 lần';
}

export async function renderAlarms(silent = false) {
    const content = document.getElementById('main-content');

    const buildUI = (alarms) => {
        let html = `
            <div class="view-header">
                <h2><i class="fa-regular fa-clock"></i> Quản lý Báo thức</h2>
                <span class="view-only-badge">View only</span>
            </div>
            <div class="alarms-grid">
        `;

        if (alarms.length === 0) {
            html += `
                <div class="empty-state">
                    <i class="fa-regular fa-bell-slash"></i>
                    <p>Chưa có báo thức nào được thiết lập.</p>
                </div>
            `;
        } else {
            alarms.forEach(alarm => {
                const aId = alarm.alarm_id || alarm._id || alarm.id;
                
                html += `
                    <div class="alarm-card glass-panel ${alarm.enabled ? 'active' : ''}">
                        <div class="alarm-info">
                            <h3 class="alarm-time">${escapeHtml(formatAlarmTime(alarm))}</h3>
                            <p class="alarm-label">${escapeHtml(alarm.label)} - ${escapeHtml(repeatLabel(alarm.repeat))}</p>
                        </div>
                    </div>
                `;
            });
        }
        html += `</div>
        `;
        content.innerHTML = html;
    };

    if (!silent && !cachedAlarms) {
        content.innerHTML = `
            <div class="view-header">
                <h2><i class="fa-regular fa-clock"></i> Quản lý Báo thức</h2>
            </div>
            <div class="glass-panel content-loading">
                <i class="fa-solid fa-circle-notch fa-spin"></i> Đang tải dữ liệu...
            </div>
        `;
    } else if (!silent && cachedAlarms) {
        buildUI(cachedAlarms);
    }

    try {
        const alarms = await AlarmAPI.getAll();
        
        if (JSON.stringify(alarms) !== JSON.stringify(cachedAlarms)) {
            cachedAlarms = alarms;
            buildUI(alarms);
        }
    } catch (error) {
        if (!cachedAlarms) {
            content.innerHTML = `
                <div class="view-header">
                    <h2><i class="fa-regular fa-clock"></i> Quản lý Báo thức</h2>
                </div>
                <div class="error-state glass-panel text-danger">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                    <p>Lỗi tải dữ liệu: ${error.message}</p>
                </div>
            `;
        }
    }
}
