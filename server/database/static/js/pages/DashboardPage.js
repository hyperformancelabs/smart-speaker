import { renderAlarms } from "../components/alarms.js";
import { renderLists } from "../components/lists.js";
import { renderMedia } from "../components/media.js";
import { renderProfile } from "../components/profile.js";
import { renderTimers } from "../components/timers.js";
import { showConfirm } from "../services/utils.js";
import {
  AlarmAPI,
  ListAPI,
  MediaAPI,
  ProfileAPI,
  TimerAPI,
} from "../services/api.js";

function clearSession() {
  localStorage.removeItem("userId");
  localStorage.removeItem("nfcTagId");
  localStorage.removeItem("userName");
  localStorage.removeItem("displayName");
}

export function loadDashboard() {
  const app = document.getElementById("app");
  app.innerHTML = `
        <div class="dashboard-layout">
            <!-- Mobile Header cho màn hình nhỏ -->
                <div class="mobile-header">
                <div style="display: flex; align-items: center; gap: 1rem;">
                    <button id="mobile-menu-btn" class="btn-icon" style="color: var(--primary);">
                        <i class="fa-solid fa-bars"></i>
                    </button>
                    <h2 style="font-size: 1.2rem; margin:0;">Smart Speaker</h2>
                </div>
                <img src="/static/image/logo.png" alt="Logo" style="width: 32px; height: 32px; object-fit: contain;">
            </div>

            <!-- Overlay làm mờ background khi mở menu trên điện thoại -->
            <div class="sidebar-overlay" id="sidebar-overlay"></div>

            <aside class="sidebar glass-panel" id="sidebar">
                <div class="sidebar-header">
                    <img src="/static/image/logo.png" alt="Smart Speaker Logo" style="width: 40px; height: 40px; border-radius: var(--radius-sm); object-fit: contain; cursor: pointer;" id="logo-btn">
                    <h2>Smart Speaker</h2>
                </div>
                
                <ul class="nav-menu">
                    <li id="menu-overview" class="nav-item active">
                        <i class="fa-solid fa-chart-pie"></i> <span>Tổng quan</span>
                    </li>
                    <li id="menu-alarms" class="nav-item">
                        <i class="fa-regular fa-clock"></i> <span>Báo thức</span>
                    </li>
                    <li id="menu-timers" class="nav-item">
                        <i class="fa-solid fa-hourglass-half"></i> <span>Hẹn giờ</span>
                    </li>
                    <li id="menu-lists" class="nav-item">
                        <i class="fa-regular fa-note-sticky"></i> <span>Ghi chú</span>
                    </li>
                    <li id="menu-media" class="nav-item">
                        <i class="fa-brands fa-youtube"></i> <span>Media</span>
                    </li>
                    <li id="menu-profile" class="nav-item">
                        <i class="fa-regular fa-user"></i> <span>Cá nhân</span>
                    </li>
                </ul>
                
                <div class="sidebar-footer">
                    <button id="btn-logout" class="btn-ghost text-danger">
                        <i class="fa-solid fa-arrow-right-from-bracket"></i> <span>Đăng xuất</span>
                    </button>
                </div>
            </aside>
            
            <main class="main-content" id="main-content">
                <!-- Nội dung sẽ được nạp ở renderOverview() -->
            </main>
            
            <div class="ambient-glow glow-1"></div>
            <div class="ambient-glow glow-2" style="bottom: -10%; right: -10%; top: auto; left: auto;"></div>
        </div>
    `;

  document.getElementById("btn-logout").addEventListener("click", () => {
    showConfirm("Bạn có chắc chắn muốn đăng xuất tài khoản này không?", () => {
      clearSession();
      window.location.reload();
    });
  });

  // Logic Đóng / Mở menu trên mobile
  const sidebar = document.getElementById("sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  const mobileMenuBtn = document.getElementById("mobile-menu-btn");

  mobileMenuBtn.addEventListener("click", () => {
    sidebar.classList.add("open");
    overlay.classList.add("open");
  });

  overlay.addEventListener("click", () => {
    sidebar.classList.remove("open");
    overlay.classList.remove("open");
  });

  const menus = [
    { id: "menu-overview", render: renderOverview },
    { id: "menu-alarms", render: renderAlarms },
    { id: "menu-timers", render: renderTimers },
    { id: "menu-lists", render: renderLists },
    { id: "menu-media", render: renderMedia },
    { id: "menu-profile", render: renderProfile },
  ];

  menus.forEach((menu) => {
    const el = document.getElementById(menu.id);
    if (el) {
      el.addEventListener("click", () => {
        document
          .querySelectorAll(".nav-item")
          .forEach((nav) => nav.classList.remove("active"));
        el.classList.add("active");
        menu.render();
        if (sidebar.classList.contains("open")) {
          sidebar.classList.remove("open");
          overlay.classList.remove("open");
        }
      });
    }
  });

  // Mặc định load Overview
  renderOverview();

  // Logo Click cũng về Overview
  document.getElementById("logo-btn").addEventListener("click", () => {
    document
      .querySelectorAll(".nav-item")
      .forEach((nav) => nav.classList.remove("active"));
    document.getElementById("menu-overview").classList.add("active");
    renderOverview();
    if (sidebar.classList.contains("open")) {
      sidebar.classList.remove("open");
      overlay.classList.remove("open");
    }
  });
}

let cachedOverview = null;

async function renderOverview(silent = false) {
  const content = document.getElementById("main-content");

  const buildUI = (data) => {
    const { profile, activeAlarms, activeTimers, totalNotes, totalMedia } =
      data;
    content.innerHTML = `
            <div class="welcome-banner glass-panel" style="margin-bottom: 2rem;">
                <h3>Chào mừng ${profile.name || profile.user_name || "Người dùng"} quay lại!</h3>
                <p>Khám phá nhanh trạng thái thiết bị và dữ liệu cá nhân của bạn.</p>
            </div>
            
            <div class="stats-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem;">
                <div class="glass-panel" style="padding: 1.5rem; display: flex; align-items: center; gap: 1.5rem;">
                    <div style="font-size: 2.5rem; color: var(--primary);"><i class="fa-regular fa-clock"></i></div>
                    <div>
                        <div style="font-size: 1.8rem; font-weight: bold; color: var(--text-main);">${activeAlarms}</div>
                        <div style="color: var(--text-muted); font-size: 0.95rem;">Báo thức đang bật</div>
                    </div>
                </div>
                <div class="glass-panel" style="padding: 1.5rem; display: flex; align-items: center; gap: 1.5rem;">
                    <div style="font-size: 2.5rem; color: var(--secondary);"><i class="fa-solid fa-hourglass-half"></i></div>
                    <div>
                        <div style="font-size: 1.8rem; font-weight: bold; color: var(--text-main);">${activeTimers}</div>
                        <div style="color: var(--text-muted); font-size: 0.95rem;">Hẹn giờ đang chạy</div>
                    </div>
                </div>
                <div class="glass-panel" style="padding: 1.5rem; display: flex; align-items: center; gap: 1.5rem;">
                    <div style="font-size: 2.5rem; color: var(--success);"><i class="fa-regular fa-note-sticky"></i></div>
                    <div>
                        <div style="font-size: 1.8rem; font-weight: bold; color: var(--text-main);">${totalNotes}</div>
                        <div style="color: var(--text-muted); font-size: 0.95rem;">Ghi chú cần làm</div>
                    </div>
                </div>
                <div class="glass-panel" style="padding: 1.5rem; display: flex; align-items: center; gap: 1.5rem;">
                    <div style="font-size: 2.5rem; color: var(--primary);"><i class="fa-brands fa-youtube" style="color: #ff0000;"></i></div>
                    <div>
                        <div style="font-size: 1.8rem; font-weight: bold; color: var(--text-main);">${totalMedia}</div>
                        <div style="color: var(--text-muted); font-size: 0.95rem;">Media history</div>
                    </div>
                </div>
            </div>
        `;
  };

  if (!silent && !cachedOverview) {
    content.innerHTML = `
            <div class="glass-panel content-loading" style="margin-top: 2rem;">
                <i class="fa-solid fa-circle-notch fa-spin"></i> Đang tải dữ liệu tổng quan...
            </div>
        `;
  } else if (!silent && cachedOverview) {
    buildUI(cachedOverview);
  }

  try {
    const [profile, alarms, timers, lists, media] = await Promise.all([
      ProfileAPI.get().catch(() => ({ name: "Người dùng" })),
      AlarmAPI.getAll().catch(() => []),
      TimerAPI.getAll().catch(() => []),
      ListAPI.getAll().catch(() => []),
      MediaAPI.getAll().catch(() => []),
    ]);

    const newData = {
      profile,
      activeAlarms: alarms.filter((a) => a.enabled).length,
      activeTimers: timers.filter((t) => t.active).length,
      totalNotes: lists.reduce(
        (sum, list) => sum + (list.items ? list.items.length : 0),
        0,
      ),
      totalMedia: media.length,
    };

    if (JSON.stringify(newData) !== JSON.stringify(cachedOverview)) {
      cachedOverview = newData;
      buildUI(newData);
    }
  } catch (e) {
    if (!cachedOverview) {
      content.innerHTML = `
                <div class="welcome-banner glass-panel">
                    <h3>Chào mừng quay lại! ✨</h3>
                    <p>Chọn một chức năng trên thanh menu bên trái để bắt đầu quản lý không gian của bạn.</p>
                </div>
            `;
    }
  }
}
