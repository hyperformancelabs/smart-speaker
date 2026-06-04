import { TimerAPI } from "../services/api.js";

let cachedTimers = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatTime(totalSeconds) {
  if (totalSeconds <= 0) return "00:00";
  const m = Math.floor(totalSeconds / 60)
    .toString()
    .padStart(2, "0");
  const s = (totalSeconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function getRemainingSeconds(timer) {
  const startedAt = new Date(timer.started_at).getTime();
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  return Math.max(0, Number(timer.duration_seconds || 0) - elapsedSeconds);
}

export async function renderTimers(silent = false) {
  const content = document.getElementById("main-content");

  if (!silent) {
    content.innerHTML = `
      <div class="timer-container" style="max-width: 800px; margin: 0 auto; width: 100%; padding-bottom: 2rem;">
        <div class="view-header">
          <h2><i class="fa-solid fa-hourglass-half"></i> Timer</h2>
          <span class="view-only-badge">View only</span>
        </div>
        <div id="recent-timers-list">
          <div style="text-align: center; padding: 2rem; color: var(--text-muted);"><i class="fa-solid fa-circle-notch fa-spin"></i> Đang tải...</div>
        </div>
      </div>
    `;
  }

  // Hàm vẽ riêng phần list
  const buildList = (timers) => {
    const listEl = document.getElementById("recent-timers-list");
    if (!listEl) return;

    if (!timers || timers.length === 0) {
      listEl.innerHTML = '<p class="text-muted" style="text-align: center; padding: 2rem;">Chưa có lịch sử hẹn giờ.</p>';
      return;
    }

    // Sắp xếp mới nhất lên đầu
    const sorted = [...timers].sort((a, b) => new Date(b.started_at) - new Date(a.started_at));

    listEl.innerHTML = sorted
      .map((t) => {
        const remaining = getRemainingSeconds(t);
        return `
            <div class="timer-readonly-row" style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 1.2rem 0; border-bottom: 1px solid var(--border-glass);">
                <div style="font-weight: 600; font-size: 1.1rem; color: var(--text-main); margin-left: 0.5rem; flex: 1;">${escapeHtml(t.label || "Timer")}</div>
                <div style="color: var(--text-muted); font-size: 1.1rem;">${formatTime(remaining)}</div>
                <div class="view-only-badge">Active</div>
                </div>
        `;
      })
      .join("");
  };

  if (!silent && cachedTimers) {
    buildList(cachedTimers);
  }

  try {
    const timers = await TimerAPI.getAll();
    if (JSON.stringify(timers) !== JSON.stringify(cachedTimers)) {
      cachedTimers = timers;
      buildList(timers);
    }
  } catch (error) {
    if (!cachedTimers) {
      const listEl = document.getElementById("recent-timers-list");
      if(listEl) listEl.innerHTML = `<p class="text-danger" style="text-align: center;">Lỗi tải lịch sử: ${error.message}</p>`;
    }
  }

}
