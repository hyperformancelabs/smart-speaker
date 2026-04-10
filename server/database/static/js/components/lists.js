import { ListAPI } from '../services/api.js';
import { showToast, showConfirm } from '../services/utils.js';

let cachedLists = null;

export async function renderLists(silent = false) {
    const content = document.getElementById('main-content');

    const buildUI = (lists) => {
        let html = `
            <div class="view-header" style="flex-wrap: wrap; gap: 1rem;">
                <h2><i class="fa-regular fa-note-sticky"></i> Ghi chú & Công việc</h2>
                <div style="display:flex; gap:0.5rem; flex-wrap: wrap;">
                    <input type="text" id="new-list-name" placeholder="Tên danh sách mới..." style="background: rgba(0,0,0,0.2); border: 1px solid var(--border-glass); border-radius: var(--radius-sm); color: white; padding: 0.8rem; width: 250px;">
                    <button id="btn-add-list" class="btn-primary glow-effect">
                        <i class="fa-solid fa-plus"></i> Tạo List
                    </button>
                </div>
            </div>
            <div class="lists-board" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1.5rem; align-items: stretch;">
        `;

        if (lists.length === 0) {
            html += `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <i class="fa-regular fa-folder-open"></i>
                    <p>Chưa có danh sách ghi chú nào. Hãy tạo một cái mới.</p>
                </div>
            `;
        } else {
            lists.forEach(list => {
                const lId = list.list_id || list._id || list.id;
                html += `
                    <div class="list-card glass-panel" style="padding: 1.5rem; display: flex; flex-direction: column; gap: 1rem; height: 100%;">
                        <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-glass); padding-bottom: 0.5rem;">
                            <h3 style="font-size: 1.2rem; font-weight: 600;">${list.list_name}</h3>
                            <div style="display: flex; gap: 0.25rem;">
                                <button class="btn-icon text-muted" onclick="window.editList('${lId}', '${list.list_name}')" title="Sửa tên Danh Sách" style="width: 30px; height: 30px; font-size: 0.9rem;">
                                    <i class="fa-solid fa-pen"></i>
                                </button>
                                <button class="btn-icon text-danger" onclick="window.deleteList('${lId}')" title="Xóa Danh Sách" style="width: 30px; height: 30px; font-size: 1rem;">
                                    <i class="fa-regular fa-trash-can"></i>
                                </button>
                            </div>
                        </div>
                        
                        <div class="notes-container" style="display: flex; flex-direction: column; gap: 0.5rem; flex: 1; max-height: 300px; overflow-y: auto;">
                `;
                
                if (!list.items || list.items.length === 0) {
                    html += `<p style="color: var(--text-muted); font-size: 0.9rem; text-align: center; margin: 1rem 0;">Danh sách trống</p>`;
                } else {
                    list.items.forEach(note => {
                        const nId = note.item_id || note._id || note.id;
                        html += `
                            <div class="note-item" style="display: flex; align-items: flex-start; justify-content: space-between; gap: 0.5rem; padding: 0.75rem; background: rgba(0,0,0,0.2); border-radius: var(--radius-sm);">
                                <label style="display: flex; gap: 0.8rem; cursor: pointer; align-items: flex-start; flex: 1;">
                                    <input type="checkbox" ${note.completed ? 'checked' : ''} onchange="window.toggleNoteStatus('${lId}', '${nId}', this.checked)" style="margin-top: 4px; accent-color: var(--primary); transform: scale(1.2);">
                                    <span style="font-size: 0.95rem; line-height: 1.4; ${note.completed ? 'text-decoration: line-through; opacity: 0.5;' : ''}">${note.content}</span>
                                </label>
                                <div style="display: flex; gap: 0.25rem; flex-shrink: 0;">
                                    <button class="btn-icon text-muted" onclick="window.editNote('${lId}', '${nId}', '${note.content}')" title="Sửa Note" style="width: 24px; height: 24px; font-size: 0.8rem;">
                                        <i class="fa-solid fa-pen"></i>
                                    </button>
                                    <button class="btn-icon text-danger" onclick="window.deleteNote('${lId}', '${nId}')" title="Xóa Note" style="width: 24px; height: 24px; font-size: 0.9rem;">
                                        <i class="fa-solid fa-xmark"></i>
                                    </button>
                                </div>
                            </div>
                        `;
                    });
                }
                
                html += `
                        </div>
                        
                        <div style="display: flex; gap: 0.5rem; margin-top: auto;">
                            <input type="text" id="note-input-${lId}" placeholder="Thêm ghi chú..." style="flex: 1; background: rgba(0,0,0,0.2); border: 1px solid var(--border-glass); border-radius: var(--radius-sm); color: white; padding: 0.6rem 0.8rem; font-size: 0.9rem;">
                            <button class="btn-primary" onclick="window.addNote('${lId}')" style="padding: 0.6rem 1rem; border-radius: var(--radius-sm);">
                                <i class="fa-solid fa-paper-plane"></i>
                            </button>
                        </div>
                    </div>
                `;
            });
        }
        
        html += `</div>
            <!-- Edit Modal cho Lists và Notes -->
            <div id="list-edit-modal" class="confirm-overlay" style="display: none;">
                <div class="glass-panel" style="padding: 2rem; max-width: 400px; width: 90%; position: relative; background: var(--bg-panel);">
                    <h3 id="list-edit-modal-title" style="margin-bottom: 1.5rem; font-size: 1.5rem;">Cập nhật</h3>
                    <form id="list-edit-form" class="modern-form">
                        <input type="hidden" id="list-edit-type">
                        <input type="hidden" id="list-edit-list-id">
                        <input type="hidden" id="list-edit-note-id">
                        <input type="hidden" id="list-edit-old-content">
                        <div class="form-group">
                            <label id="list-edit-modal-label">Nội dung mới</label>
                            <input type="text" id="list-edit-input" required>
                        </div>
                        <div style="display: flex; gap: 1rem; margin-top: 1rem;">
                            <button type="button" class="btn-secondary" style="flex: 1;" onclick="window.closeListEditModal()">Hủy</button>
                            <button type="submit" class="btn-primary" style="flex: 1;">Lưu</button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        content.innerHTML = html;

        const btnAddList = document.getElementById('btn-add-list');
        if (btnAddList) {
            btnAddList.addEventListener('click', async () => {
                const nameInp = document.getElementById('new-list-name').value;
                if (!nameInp.trim()) return;
                try {
                    await ListAPI.createList(nameInp);
                    renderLists(true);
                    showToast("Đã tạo danh sách mới", "success");
                } catch(e) { showToast("Lỗi khi tạo danh sách: " + e.message, "error"); }
            });
        }

        const editForm = document.getElementById('list-edit-form');
        if (editForm) {
            editForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const type = document.getElementById('list-edit-type').value;
                const listId = document.getElementById('list-edit-list-id').value;
                const noteId = document.getElementById('list-edit-note-id').value;
                const oldContent = document.getElementById('list-edit-old-content').value;
                const newContent = document.getElementById('list-edit-input').value;
                
                if (!newContent || newContent === oldContent) {
                    window.closeListEditModal();
                    return;
                }

                try {
                    if (type === 'list') {
                        const lists = await ListAPI.getAll();
                        const list = lists.find(l => (l.list_id || l._id || l.id) === listId);
                        await ListAPI.deleteList(listId);
                        const newList = await ListAPI.createList(newContent);
                        const nId = newList.list_id || newList._id || newList.id;
                        if (list && list.items) {
                            for (const item of list.items) {
                                await ListAPI.addNote(nId, item.content);
                            }
                        }
                        showToast("Đã đổi tên danh sách", "success");
                    } else if (type === 'note') {
                        await ListAPI.deleteNote(listId, noteId);
                        await ListAPI.addNote(listId, newContent);
                        showToast("Đã sửa ghi chú", "success");
                    }
                    window.closeListEditModal();
                    renderLists(true);
                } catch(e) {
                    showToast("Lỗi khi cập nhật!", "error");
                }
            });
        }
    };

    if (!silent && !cachedLists) {
        content.innerHTML = `
            <div class="view-header">
                <h2><i class="fa-regular fa-note-sticky"></i> Ghi chú & Công việc</h2>
            </div>
            <div class="glass-panel content-loading">
                <i class="fa-solid fa-circle-notch fa-spin"></i> Đang tải dữ liệu...
            </div>
        `;
    } else if (!silent && cachedLists) {
        buildUI(cachedLists);
    }

    try {
        const lists = await ListAPI.getAll();
        
        if (JSON.stringify(lists) !== JSON.stringify(cachedLists)) {
            cachedLists = lists;
            buildUI(lists);
        }
    } catch (error) {
        if (!cachedLists) {
            content.innerHTML = `
                <div class="view-header">
                    <h2><i class="fa-regular fa-note-sticky"></i> Ghi chú & Công việc</h2>
                </div>
                <div class="error-state glass-panel text-danger">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                    <p>Lỗi tải dữ liệu: ${error.message}</p>
                </div>
            `;
        }
    }
}

// Global functions
window.deleteList = async (listId) => {
    showConfirm("Bạn có chắc chắn muốn xóa danh sách này cùng các ghi chú bên trong?", async () => {
        try {
            await ListAPI.deleteList(listId);
            renderLists(true);
            showToast("Đã xóa danh sách", "success");
        } catch(e) { showToast("Lỗi xóa danh sách.", "error"); }
    });
}

window.addNote = async (listId) => {
    const input = document.getElementById(`note-input-${listId}`);
    if(!input || !input.value.trim()) return;
    try {
        await ListAPI.addNote(listId, input.value.trim());
        renderLists(true);
        showToast("Đã thêm ghi chú", "success");
    } catch(e) { showToast("Lỗi thêm note.", "error"); }
}

window.deleteNote = async (listId, noteId) => {
    try {
        await ListAPI.deleteNote(listId, noteId);
        renderLists(true);
        showToast("Đã xóa ghi chú", "success");
    } catch(e) { showToast("Lỗi xóa note.", "error"); }
}

window.toggleNoteStatus = async (listId, noteId, completed) => {
    try {
        await ListAPI.updateNoteCompleted(listId, noteId, completed);
        setTimeout(() => renderLists(true), 200);
        showToast("Đã cập nhật trạng thái", "success");
    } catch(e) { 
        showToast("Lỗi cập nhật trạng thái.", "error");
        renderLists(true);
    }
}

window.openEditModal = (type, listId, noteId, oldContent) => {
    document.getElementById('list-edit-modal').style.display = 'flex';
    document.getElementById('list-edit-type').value = type;
    document.getElementById('list-edit-list-id').value = listId;
    document.getElementById('list-edit-note-id').value = noteId || '';
    document.getElementById('list-edit-old-content').value = oldContent;
    document.getElementById('list-edit-input').value = oldContent;
    
    if(type === 'list') {
        document.getElementById('list-edit-modal-title').innerText = 'Sửa tên danh sách';
        document.getElementById('list-edit-modal-label').innerText = 'Tên danh sách mới';
    } else {
        document.getElementById('list-edit-modal-title').innerText = 'Sửa ghi chú';
        document.getElementById('list-edit-modal-label').innerText = 'Nội dung mới';
    }
};

window.closeListEditModal = () => {
    document.getElementById('list-edit-modal').style.display = 'none';
};

window.editList = async (listId, oldName) => {
    window.openEditModal('list', listId, null, oldName);
};

window.editNote = async (listId, noteId, oldContent) => {
    window.openEditModal('note', listId, noteId, oldContent);
};
