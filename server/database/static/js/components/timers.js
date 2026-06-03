import { TimerAPI } from "../services/api.js";
import { showToast } from "../services/utils.js";

let cachedTimers = null;
let currentSeconds = 0;
let currentInterval = null;
let currentLabel = "";

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

  // Chỉ vẽ khung UI một lần để không làm mất trạng thái đếm ngược khi SWR load ngầm
  if (!silent) {
    content.innerHTML = `
      <div class="timer-container" style="max-width: 800px; margin: 0 auto; width: 100%; padding-bottom: 2rem;">
        <h4 style="color: var(--text-muted); margin-bottom: 1rem; font-size: 0.9rem; letter-spacing: 1px; text-transform: uppercase;">Timer</h4>
        
        <!-- Các nút chọn nhanh -->
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
          <button class="btn-secondary" style="border-radius: var(--radius-sm);" onclick="window.setQuickTime(5)">5 min</button>
          <button class="btn-secondary" style="border-radius: var(--radius-sm);" onclick="window.setQuickTime(10)">10 min</button>
          <button class="btn-secondary" style="border-radius: var(--radius-sm);" onclick="window.setQuickTime(25)">25 min</button>
          <button class="btn-secondary" style="border-radius: var(--radius-sm);" onclick="window.setQuickTime(60)">1 hr</button>
        </div>
        
        <!-- Form nhập tay -->
        <div style="display: flex; gap: 1rem; margin-bottom: 3rem; flex-wrap: wrap;">
          <input type="number" id="t-min" placeholder="Min" min="0" style="width: 80px; padding: 0.8rem; border: 1px solid var(--border-glass); border-radius: var(--radius-sm); outline: none; background: var(--bg-panel); color: var(--text-main);">
          <input type="number" id="t-sec" placeholder="Sec" min="0" max="59" style="width: 80px; padding: 0.8rem; border: 1px solid var(--border-glass); border-radius: var(--radius-sm); outline: none; background: var(--bg-panel); color: var(--text-main);">
          <input type="text" id="t-label" placeholder="Label (optional)" style="flex: 1; min-width: 150px; padding: 0.8rem; border: 1px solid var(--border-glass); border-radius: var(--radius-sm); outline: none; background: var(--bg-panel); color: var(--text-main);">
          <button class="btn-primary" onclick="window.startNewTimer()" style="background: transparent; border: 1px solid var(--success); color: var(--success); min-width: 100px; padding: 0.8rem;">Start</button>
        </div>

        <!-- Màn hình hiển thị đếm ngược -->
        <div style="text-align: center; margin-bottom: 4rem;">
          <div id="countdown-display" style="font-size: min(8rem, 25vw); font-weight: 700; font-family: monospace; font-variant-numeric: tabular-nums; line-height: 1; color: var(--text-main); transition: color 0.3s;">
            ${formatTime(currentSeconds)}
          </div>
          <div id="countdown-label" style="color: var(--text-muted); margin-top: 1rem; min-height: 1.5rem; font-size: 1.2rem;">
            ${currentLabel || "-"}
          </div>
        </div>

        <!-- Lịch sử -->
        <h4 style="color: var(--text-muted); margin-bottom: 1rem; font-size: 0.9rem; letter-spacing: 1px; text-transform: uppercase;">Bộ đếm đang chạy</h4>
        <div id="recent-timers-list">
          <!-- Inject by JS -->
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
        const encodedLabel = encodeURIComponent(t.label || "");
        return `
            <div style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 1.2rem 0; border-bottom: 1px solid var(--border-glass);">
                <div style="font-weight: 600; font-size: 1.1rem; color: var(--text-main); margin-left: 0.5rem; flex: 1;">${escapeHtml(t.label || "Timer")}</div>
                <div style="color: var(--text-muted); font-size: 1.1rem;">${formatTime(remaining)}</div>
                <div style="display: flex; gap: 0.5rem;">
                  <button class="btn-icon text-muted" onclick="window.quickStartFromHistory(${t.duration_seconds}, '${encodedLabel}')" title="Dùng lại">
                    <i class="fa-solid fa-rotate-right"></i>
                  </button>
                  <button class="btn-icon text-danger" onclick="window.cancelExistingTimer('${t.timer_id}')" title="Huỷ timer">
                    <i class="fa-regular fa-trash-can"></i>
                  </button>
                </div>
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

  // --- GLOBAL UI HANDLERS ---
  window.setQuickTime = (minutes) => {
    document.getElementById("t-min").value = minutes;
    document.getElementById("t-sec").value = "0";
  };
  
  window.quickStartFromHistory = (totalSec, encodedLabel) => {
      const label = decodeURIComponent(encodedLabel || "");
      const displayM = Math.floor(totalSec / 60);
      const displayS = totalSec % 60;
      document.getElementById("t-min").value = displayM > 0 ? displayM : "";
      document.getElementById("t-sec").value = displayS > 0 ? displayS : "";
      document.getElementById("t-label").value = label || "";
      window.startNewTimer();
  };

  window.startNewTimer = async () => {
    let min = parseInt(document.getElementById("t-min").value || 0);
    let sec = parseInt(document.getElementById("t-sec").value || 0);
    let label = document.getElementById("t-label").value.trim();
    let totalSec = min * 60 + sec;

    if (totalSec <= 0) {
      showToast("Vui lòng thiết lập thời gian!", "error");
      return;
    }

    // Trigger API lưu lịch sử ngầm
    TimerAPI.create({
      label: label || "",
      duration_seconds: totalSec,
      active: true,
    })
    .then(() => renderTimers(true)) // Refresh lại list ngầm
    .catch(console.error);

    // Xoá input UI
    document.getElementById("t-min").value = "";
    document.getElementById("t-sec").value = "";
    document.getElementById("t-label").value = "";

    // Xoá bộ đếm cũ nếu đang chạy
    if (currentInterval) clearInterval(currentInterval);

    currentSeconds = totalSec;
    currentLabel = label;
    
    const disp = document.getElementById("countdown-display");
    const lab = document.getElementById("countdown-label");
    
    if (disp) {
      disp.innerText = formatTime(currentSeconds);
      disp.style.color = "var(--text-main)"; // Reset màu text khi ấn start
    }
    if (lab) lab.innerText = currentLabel || "-";

    currentInterval = setInterval(() => {
      currentSeconds--;
      if (currentSeconds <= 0) {
        currentSeconds = 0;
        clearInterval(currentInterval);
        currentInterval = null;
        
        // Cảnh báo hết giờ
        if (disp) {
            disp.innerText = "00:00";
            disp.style.color = "var(--danger)";
        }
        showToast("Hẹn giờ đã kết thúc!", "success");
        return;
      }
      
      if (disp) disp.innerText = formatTime(currentSeconds);
    }, 1000);
  };

  window.cancelExistingTimer = async (timerId) => {
    try {
      await TimerAPI.delete(timerId);
      showToast("Đã huỷ timer.", "success");
      renderTimers(true);
    } catch (error) {
      showToast(error.message || "Không thể huỷ timer.", "error");
    }
  };
}
