import { showToast } from "../services/utils.js";
import { loadDashboard } from "./DashboardPage.js";
import { AuthAPI } from "../services/api.js";

export function renderLogin() {
  const app = document.getElementById("app");
  app.innerHTML = `
        <div class="auth-layout">
            <div class="glass-panel auth-card">
                <div class="auth-header">
                    <img src="image/logo.png" alt="Smart Room Logo" style="width: 64px; height: 64px; margin: 0 auto 1rem; display: block; object-fit: contain;">
                    <h2>Smart Room</h2>
                    <p>Hệ sinh thái nhà thông minh</p>
                </div>
                
                <div class="qr-login-section">
                    <button class="btn-primary glow-effect" id="btn-qr-login">
                        <i class="fa-solid fa-qrcode"></i> Đăng nhập QR (Dev Test)
                    </button>
                </div>

                <div class="divider">
                    <span>hoặc</span>
                </div>

                <form id="login-form" class="modern-form">
                    <div class="form-group">
                        <label><i class="fa-regular fa-envelope"></i> Email</label>
                        <input type="email" id="email" placeholder="Nhập địa chỉ email" required>
                    </div>
                    <div class="form-group">
                        <label><i class="fa-solid fa-lock"></i> Mật khẩu</label>
                        <input type="password" id="password" placeholder="Nhập mật khẩu" required>
                    </div>
                    <button type="submit" class="btn-secondary">Đăng nhập</button>
                </form>
                
                <div class="auth-footer">
                    <p>Chưa có tài khoản?</p>
                    <a href="#" id="link-signup" class="text-link">Đăng ký qua NFC</a>
                </div>
            </div>
            
            <!-- Trang trí viền sương mù mờ ảo -->
            <div class="ambient-glow glow-1"></div>
            <div class="ambient-glow glow-2"></div>
        </div>
    `;

  document
    .getElementById("btn-qr-login")
    .addEventListener("click", simulateQRLogin);
  document
    .getElementById("login-form")
    .addEventListener("submit", handleEmailLogin);
  document.getElementById("link-signup").addEventListener("click", (e) => {
    e.preventDefault();
    renderSignup();
  });
}

export function renderSignup() {
  const app = document.getElementById("app");
  app.innerHTML = `
        <div class="auth-layout">
            <div class="glass-panel auth-card">
                <div class="auth-header">
                    <img src="image/logo.png" alt="Smart Room Logo" style="width: 64px; height: 64px; margin: 0 auto 1rem; display: block; object-fit: contain;">
                    <h2>Tạo Tài Khoản</h2>
                    <p class="text-success"><i class="fa-solid fa-wifi"></i> Nhận diện NFC thành công</p>
                </div>
                
                <form id="signup-form" class="modern-form mt-4">
                    <div class="form-group">
                        <label>Họ và tên</label>
                        <input type="text" id="reg-name" placeholder="Ví dụ: Nguyễn Văn A" required>
                    </div>
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" id="reg-email" placeholder="Email của bạn" required>
                    </div>
                    <div class="form-group">
                        <label>Mật khẩu</label>
                        <input type="password" id="reg-password" placeholder="Tạo mật khẩu mạnh" required>
                    </div>
                    <button type="submit" class="btn-primary glow-effect">Huấn luyện & Đăng ký</button>
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
      const name = document.getElementById("reg-name").value;
      const userName = document.getElementById("reg-email").value; // Using email field as username
      const password = document.getElementById("reg-password").value;
      const urlParams = new URLSearchParams(window.location.search);
      const nfcTagId = urlParams.get('nfc_tag_id') || 'DEMO_NFC';
      
      try {
          await AuthAPI.signup({ name, user_name: userName, user_password: password, nfc_tag_id: nfcTagId });
          showToast("Đăng ký thành công! Vui lòng đăng nhập.", "success");
          renderLogin();
      } catch (err) {
          showToast("Lỗi đăng ký: " + err.message, "error");
      }
    });
}

async function handleEmailLogin(e) {
  e.preventDefault();
  const userName = document.getElementById("email").value; // form label is email but we use user_name
  const password = document.getElementById("password").value;
  try {
      const res = await AuthAPI.login({ user_name: userName, user_password: password });
      if (res.nfc_tag_id) {
          localStorage.setItem("userId", res.nfc_tag_id);
          loadDashboard();
      } else {
          showToast("Đăng nhập thất bại, sai tài khoản hoặc mật khẩu.", "error");
      }
  } catch (err) {
      showToast("Lỗi đăng nhập: " + err.message, "error");
  }
}

async function simulateQRLogin() {
  // Logic websocket/API poll từ QR
  localStorage.setItem("userId", "11111111-1111-1111-1111-111111111111");
  loadDashboard();
}
