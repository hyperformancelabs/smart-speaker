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
                <button id="btn-add-alarm" class="btn-primary glow-effect">
                    <i class="fa-solid fa-plus"></i> Thêm mới
                </button>
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
                const canEdit = (alarm.schedule_type || 'time') === 'time';
                
                html += `
                    <div class="alarm-card glass-panel ${alarm.enabled ? 'active' : ''}">
                        <div class="alarm-info">
                            <h3 class="alarm-time">${escapeHtml(formatAlarmTime(alarm))}</h3>
                            <p class="alarm-label">${escapeHtml(alarm.label)} - ${escapeHtml(repeatLabel(alarm.repeat))}</p>
                        </div>
                        <div class="alarm-actions">
                            <label class="toggle-switch">
                                <input type="checkbox" ${alarm.enabled ? 'checked' : ''} 
                                       onchange="window.toggleAlarmStatus(this, '${aId}')">
                                <span class="slider"></span>
                            </label>
                            <button class="btn-icon text-muted" onclick="window.openAlarmModal('${aId}')" title="${canEdit ? 'Sửa' : 'Chỉ hỗ trợ sửa báo thức giờ cố định'}" ${canEdit ? '' : 'disabled'}>
                                <i class="fa-solid fa-pen"></i>
                            </button>
                            <button class="btn-icon text-danger" onclick="window.deleteAlarm('${aId}')" title="Xóa">
                                <i class="fa-regular fa-trash-can"></i>
                            </button>
                        </div>
                    </div>
                `;
            });
        }
        html += `</div>
            <!-- Bắt đầu mã nguồn Modal -->
            <div id="alarm-modal" class="confirm-overlay" style="display: none;">
                <div class="glass-panel" style="padding: 2rem; max-width: 400px; width: 90%; position: relative; background: var(--bg-panel);">
                    <h3 id="alarm-modal-title" style="margin-bottom: 1.5rem; font-size: 1.5rem;">Thêm Báo Thức</h3>
                    <form id="alarm-form" class="modern-form">
                        <input type="hidden" id="alarm-id-input">
                        <div class="form-group">
                            <label>Giờ (HH:mm)</label>
                            <input type="time" id="alarm-time-input" required>
                        </div>
                        <div class="form-group">
                            <label>Nhãn báo thức</label>
                            <input type="text" id="alarm-label-input" placeholder="Ví dụ: Thức dậy" required>
                        </div>
                        <div class="form-group">
                            <label>Lặp lại</label>
                            <select id="alarm-repeat-input" style="background: #ffffff; border: 1px solid var(--border-glass); padding: 1rem; border-radius: var(--radius-sm); font-family: var(--font-main);">
                                <option value="once">Chỉ một lần</option>
                                <option value="daily">Hàng ngày</option>
                            </select>
                        </div>
                        <div style="display: flex; gap: 1rem; margin-top: 1rem;">
                            <button type="button" class="btn-secondary" style="flex: 1;" onclick="window.closeAlarmModal()">Hủy</button>
                            <button type="submit" class="btn-primary" style="flex: 1;">Lưu</button>
                        </div>
                    </form>
                </div>
            </div>
            <!-- Kết thúc mã nguồn Modal -->
        `;
        content.innerHTML = html;

        document.getElementById('btn-add-alarm').addEventListener('click', () => {
            window.openAlarmModal();
        });
        
        document.getElementById('alarm-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            const editId = document.getElementById('alarm-id-input').value;
            const alTime = document.getElementById('alarm-time-input').value;
            const alLabel = document.getElementById('alarm-label-input').value.trim();
            const alRepeat = document.getElementById('alarm-repeat-input').value;
            const payload = {
                schedule_type: 'time',
                time: alTime,
                label: alLabel,
                repeat: alRepeat,
            };
            
            try {
                if (editId) {
                    await AlarmAPI.update(editId, payload);
                    showToast("Đã cập nhật báo thức", "success");
                } else {
                    await AlarmAPI.create(payload);
                    showToast("Đã thêm báo thức mới", "success");
                }
                window.closeAlarmModal();
                renderAlarms(true);
            } catch (error) {
                showToast("Lỗi lưu báo thức", "error");
            }
        });
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

window.openAlarmModal = (id = '') => {
    const alarm = id ? getAlarmById(id) : null;
    if (alarm && alarm.schedule_type && alarm.schedule_type !== 'time') {
        showToast("UI hiện tại chỉ hỗ trợ chỉnh báo thức giờ cố định.", "error");
        return;
    }

    document.getElementById('alarm-modal').style.display = 'flex';
    document.getElementById('alarm-modal-title').innerText = id ? 'Chỉnh sửa Báo thức' : 'Thêm Báo thức';
    document.getElementById('alarm-id-input').value = id;
    
    const shortTime = alarm?.time && alarm.time.length >= 5 ? alarm.time.substring(0, 5) : '07:00';
    document.getElementById('alarm-time-input').value = shortTime;
    document.getElementById('alarm-label-input').value = alarm?.label || '';
    document.getElementById('alarm-repeat-input').value = alarm?.repeat || 'once';
};

window.closeAlarmModal = () => {
    document.getElementById('alarm-modal').style.display = 'none';
};
window.toggleAlarmStatus = async (checkbox, id) => {
    try {
        const isEnabled = checkbox.checked;
        const card = checkbox.closest('.alarm-card');
        if(isEnabled) {
            card.classList.add('active');
        } else {
            card.classList.remove('active');
        }
        await AlarmAPI.updateStatus(id, isEnabled);
        showToast("Đã cập nhật báo thức", "success");
    } catch(e) { 
        showToast("Lỗi khi cập nhật trạng thái!", "error");
        checkbox.checked = !checkbox.checked;
        const card = checkbox.closest('.alarm-card');
        if(checkbox.checked) card.classList.add('active');
        else card.classList.remove('active');
    }
};

window.deleteAlarm = async (id) => {
    showConfirm("Bạn có chắc chắn muốn xóa báo thức này?", async () => {
        try {
            await AlarmAPI.delete(id);
            renderAlarms(true);
            showToast("Đã xóa báo thức.", "success");
        } catch(e) { showToast("Lỗi khi xóa!", "error"); }
    });
};
