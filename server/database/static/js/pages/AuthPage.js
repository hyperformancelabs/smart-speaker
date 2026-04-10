import { showToast } from "../services/utils.js";
import { loadDashboard } from "./DashboardPage.js";

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
                        <label><i class="fa-regular fa-user"></i> Tên đăng nhập</label>
                        <input type="text" id="username" placeholder="Nhập username">
                        <small id="username-error" class="text-danger" style="display: none; font-size: 0.85rem; margin-top: 4px;"></small>
                    </div>
                    <div class="form-group">
                        <label><i class="fa-solid fa-lock"></i> Mật khẩu</label>
                        <input type="password" id="password" placeholder="Nhập mật khẩu">
                        <small id="password-error" class="text-danger" style="display: none; font-size: 0.85rem; margin-top: 4px;"></small>
                    </div>
                    <small id="form-error" class="text-danger" style="display: none; font-size: 0.85rem; text-align: center; margin-top: 4px; margin-bottom: 8px; font-weight: bold;"></small>
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
                        <label>username</label>
                        <input type="text" id="reg-username" placeholder="username" required>
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
      // Gọi API Signup ở đây, giả lập thành công:
      showToast("Đăng ký thành công! Vui lòng đăng nhập.", "success");
      renderLogin();
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
    const res = await fetch(
      "https://hcibackend.up.railway.app/api/users/login",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );

    const data = await res.json().catch(() => ({}));

    if (res.ok) {
      // API hiện tại trả về { message: "...", user: { user_id: "..." } }
      const userIdToStore = data.user?.user_id || data.user_id || data.id;

      if (!userIdToStore) {
        showToast("Lỗi: Máy chủ không trả về ID người dùng!", "error");
        return;
      }

      localStorage.setItem("userId", userIdToStore);
      if (data.token) {
        localStorage.setItem("token", data.token);
      }
      showToast("Đăng nhập thành công!", "success");
      loadDashboard();
    } else {
      // API lỗi hoặc tài khoản sai
      formErr.innerText =
        data.message || data.error || "Tài khoản hoặc mật khẩu không đúng!";
      formErr.style.display = "block";
      userInp.style.borderColor = "var(--danger)";
      passInp.style.borderColor = "var(--danger)";
    }
  } catch (error) {
    formErr.innerText = "Lỗi kết nối đến máy chủ. Vui lòng thử lại sau!";
    formErr.style.display = "block";
  }
}

async function simulateQRLogin() {
  // Logic websocket/API poll từ QR
  localStorage.setItem("userId", "11111111-1111-1111-1111-111111111111");
  loadDashboard();
}
