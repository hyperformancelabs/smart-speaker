import { MediaAPI } from "../services/api.js";
import { showToast, showConfirm } from "../services/utils.js";

export async function renderMedia() {
  const content = document.getElementById("main-content");

  content.innerHTML = `
    <div class="view-header">
      <h2><i class="fa-solid fa-clock-rotate-left" style="color: var(--primary);"></i> Media History</h2>
    </div>
    <div id="media-list" class="glass-panel content-loading" style="margin-top: 1rem;">
      <i class="fa-solid fa-circle-notch fa-spin"></i> Đang tải lịch sử media...
    </div>
  `;

  try {
    const items = await MediaAPI.getAll();
    renderMediaList(items);
  } catch {
    document.getElementById("media-list").innerHTML = `
      <div class="empty-state">
        <i class="fa-solid fa-circle-exclamation"></i>
        <p>Không thể tải lịch sử media.</p>
      </div>
    `;
  }
}

function formatRelativeTime(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now - date;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "Vừa xong";
  if (diffMin < 60) return `${diffMin} phút trước`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour} giờ trước`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay} ngày trước`;
  return date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function renderMediaList(items) {
  const container = document.getElementById("media-list");

  if (!items || items.length === 0) {
    container.className = "glass-panel empty-state";
    container.innerHTML = `
      <i class="fa-solid fa-music"></i>
      <p>Chưa có media nào được phát.</p>
    `;
    return;
  }

  container.className = "glass-panel";
  container.style.padding = "0";

  const listHtml = items
    .map(
      (item) => `
    <div class="media-history-item" data-id="${item.media_id}">
      <div class="media-history-info">
        <div class="media-history-title">${escapeHtml(item.title || item.query || "Unknown")}</div>
        <div class="media-history-meta">
          ${item.source ? `<span class="media-badge">${item.source}</span>` : ""}
          <span>${formatRelativeTime(item.last_played_at)}</span>
        </div>
      </div>
      <div class="media-history-actions">
        <button class="btn-icon btn-play-media" data-url="${escapeAttr(item.public_stream_url)}" title="Phát">
          <i class="fa-solid fa-play"></i>
        </button>
        <button class="btn-icon btn-delete-media text-danger" data-id="${item.media_id}" title="Xóa">
          <i class="fa-solid fa-trash-can"></i>
        </button>
      </div>
    </div>
  `
    )
    .join("");

  container.innerHTML = `<div class="media-history-list">${listHtml}</div>`;

  container.querySelectorAll(".btn-play-media").forEach((btn) => {
    btn.addEventListener("click", () => {
      const url = btn.dataset.url;
      if (url) window.open(url, "_blank");
    });
  });

  container.querySelectorAll(".btn-delete-media").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      showConfirm("Xóa mục này khỏi lịch sử media?", async () => {
        try {
          await MediaAPI.delete(id);
          showToast("Đã xóa khỏi lịch sử");
          renderMedia();
        } catch {
          showToast("Xóa thất bại", "error");
        }
      });
    });
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return (str || "").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
