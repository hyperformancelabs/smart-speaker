import { AuthAPI } from "../services/api.js";
import { showToast } from "../services/utils.js";
import { loadDashboard } from "./DashboardPage.js";

function getSignupTagId() {
  const params = new URLSearchParams(window.location.search);
  return params.get("nfc_tag_id")?.trim() || "";
}

export function renderLogin() {
  const app = document.getElementById("app");
  app.innerHTML = `
        <div class="auth-layout">
            <div class="glass-panel auth-card">
                <div class="auth-header">
                    <img src="/static/image/logo.png" alt="Smart Speaker Logo" style="width: 64px; height: 64px; margin: 0 auto 1rem; display: block; object-fit: contain;">
                    <h2>Smart Speaker</h2>
                    <p>Đăng nhập để quản lý báo thức, timer và danh sách của bạn</p>
                </div>

                <form id="login-form" class="modern-form">
                    <div class="form-group">
                        <label><i class="fa-regular fa-user"></i> Tên đăng nhập</label>
                        <input type="text" id="username" placeholder="Nhập username" autocomplete="username">
                        <small id="username-error" class="text-danger" style="display: none; font-size: 0.85rem; margin-top: 4px;"></small>
                    </div>
                    <div class="form-group">
                        <label><i class="fa-solid fa-lock"></i> Mật khẩu</label>
                        <input type="password" id="password" placeholder="Nhập mật khẩu" autocomplete="current-password">
                        <small id="password-error" class="text-danger" style="display: none; font-size: 0.85rem; margin-top: 4px;"></small>
                    </div>
                    <small id="form-error" class="text-danger" style="display: none; font-size: 0.85rem; text-align: center; margin-top: 4px; margin-bottom: 8px; font-weight: bold;"></small>
                    <button type="submit" class="btn-secondary">Đăng nhập</button>
                </form>
            </div>
            
            <div class="ambient-glow glow-1"></div>
            <div class="ambient-glow glow-2"></div>
        </div>
    `;

  document
    .getElementById("login-form")
    .addEventListener("submit", handleEmailLogin);
}

export function renderSignup() {
  const nfcTagId = getSignupTagId();
  const app = document.getElementById("app");

  if (!nfcTagId) {
    app.innerHTML = `
        <div class="auth-layout">
            <div class="glass-panel auth-card">
                <div class="auth-header">
                    <img src="/static/image/logo.png" alt="Smart Speaker Logo" style="width: 64px; height: 64px; margin: 0 auto 1rem; display: block; object-fit: contain;">
                    <h2>Đăng ký qua NFC</h2>
                    <p>Thiếu mã thẻ NFC trên URL. Hãy mở lại trang từ mã QR mà thiết bị cung cấp.</p>
                </div>
                <div class="modern-form">
                    <a class="btn-primary glow-effect" href="/register">Mở trang đăng ký mặc định</a>
                    <button class="btn-ghost" id="link-login"><i class="fa-solid fa-arrow-left"></i> Quay lại đăng nhập</button>
                </div>
            </div>
            <div class="ambient-glow glow-1"></div>
            <div class="ambient-glow glow-3"></div>
        </div>
    `;

    document.getElementById("link-login").addEventListener("click", (e) => {
      e.preventDefault();
      window.history.replaceState({}, "", "/");
      renderLogin();
    });
    return;
  }

  app.innerHTML = `
        <div class="auth-layout">
            <div class="glass-panel auth-card">
                <div class="auth-header">
                    <img src="/static/image/logo.png" alt="Smart Speaker Logo" style="width: 64px; height: 64px; margin: 0 auto 1rem; display: block; object-fit: contain;">
                    <h2>Tạo Tài Khoản</h2>
                    <p class="text-success"><i class="fa-solid fa-wifi"></i> Nhận diện NFC thành công</p>
                </div>
                
                <form id="signup-form" class="modern-form mt-4">
                    <div class="form-group">
                        <label>Mã NFC</label>
                        <input type="text" id="reg-nfc" value="${nfcTagId}" readonly>
                    </div>
                    <div class="form-group">
                        <label>Họ và tên</label>
                        <input type="text" id="reg-name" placeholder="Ví dụ: Nguyễn Văn A" required>
                    </div>
                    <div class="form-group">
                        <label>username</label>
                        <input type="text" id="reg-username" placeholder="username" required>
                    </div>
                    <div class="form-group">
                        <label>Mật khẩu</label>
                        <input type="password" id="reg-password" placeholder="Tạo mật khẩu mạnh" minlength="6" required>
                    </div>
                    <button type="submit" class="btn-primary glow-effect">Đăng ký</button>
                </form>

                <div class="auth-footer mt-4">
                    <button class="btn-ghost" id="link-login"><i class="fa-solid fa-arrow-left"></i> Quay lại đăng nhập</button>
                </div>
            </div>
            <div class="ambient-glow glow-1"></div>
            <div class="ambient-glow glow-3"></div>
        </div>
    `;

  document.getElementById("link-login").addEventListener("click", (e) => {
    e.preventDefault();
    renderLogin();
  });

  document
    .getElementById("signup-form")
    .addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = {
        nfc_tag_id: nfcTagId,
        name: document.getElementById("reg-name").value.trim(),
        user_name: document.getElementById("reg-username").value.trim(),
        user_password: document.getElementById("reg-password").value,
      };

      try {
        await AuthAPI.signup(payload);
        showToast("Đăng ký thành công! Vui lòng đăng nhập.", "success");
        window.history.replaceState({}, "", "/");
        renderLogin();
      } catch (error) {
        showToast(error.message || "Không thể hoàn tất đăng ký.", "error");
      }
    });
}

async function handleEmailLogin(e) {
  e.preventDefault();

  const userErr = document.getElementById("username-error");
  const passErr = document.getElementById("password-error");
  const formErr = document.getElementById("form-error");
  const userInp = document.getElementById("username");
  const passInp = document.getElementById("password");

  // Đặt lại trạng thái ban đầu
  userErr.style.display = "none";
  passErr.style.display = "none";
  formErr.style.display = "none";
  userInp.style.borderColor = "var(--border-glass)";
  passInp.style.borderColor = "var(--border-glass)";

  const usernameInput = userInp.value.trim();
  const passwordInput = passInp.value;

  let hasError = false;

  if (!usernameInput) {
    userErr.innerText = "Vui lòng nhập tên đăng nhập.";
    userErr.style.display = "block";
    userInp.style.borderColor = "var(--danger)";
    hasError = true;
  }

  if (!passwordInput) {
    passErr.innerText = "Vui lòng nhập mật khẩu.";
    passErr.style.display = "block";
    passInp.style.borderColor = "var(--danger)";
    hasError = true;
  }

  if (hasError) return;

  const payload = {
    user_name: usernameInput,
    user_password: passwordInput,
  };

  try {
    const user = await AuthAPI.login(payload);
    localStorage.setItem("userId", user.user_id);
    localStorage.setItem("nfcTagId", user.nfc_tag_id);
    localStorage.setItem("userName", user.user_name || "");
    localStorage.setItem("displayName", user.name || "");
    showToast("Đăng nhập thành công!", "success");
    loadDashboard();
  } catch (error) {
    formErr.innerText =
      error.message || "Lỗi kết nối đến máy chủ. Vui lòng thử lại sau!";
    formErr.style.display = "block";
    userInp.style.borderColor = "var(--danger)";
    passInp.style.borderColor = "var(--danger)";
  }
}
