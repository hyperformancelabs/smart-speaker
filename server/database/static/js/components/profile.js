import { ProfileAPI } from "../services/api.js";
import { showToast } from "../services/utils.js";

export async function renderProfile() {
  const content = document.getElementById("main-content");
  content.innerHTML = `
        <div class="view-header">
            <h2><i class="fa-regular fa-user"></i> Hồ sơ Cá nhân</h2>
        </div>
        <div class="glass-panel content-loading">
            <i class="fa-solid fa-circle-notch fa-spin"></i> Đang tải dữ liệu...
        </div>
    `;

  try {
    let user = { name: "", email: "", phone: "" };
    try {
      user = await ProfileAPI.get();
    } catch (e) {
      console.warn("Profile not found, using empty state. Error:", e.message);
    }

    content.innerHTML = `
            <div class="view-header">
                <h2><i class="fa-regular fa-user"></i> Hồ sơ Cá nhân</h2>
            </div>
            
            <div class="glass-panel" style="max-width: 800px; width: 100%; padding: 2.5rem 2rem; margin: 0 auto;">
                <div style="text-align: center; margin-bottom: 2rem;">
                    <div style="width: 100px; height: 100px; background: linear-gradient(135deg, var(--primary), var(--secondary)); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 3rem; margin: 0 auto 1rem; color: white;">
                        <i class="fa-solid fa-user-astronaut"></i>
                    </div>
                    <h3>Thông tin tài khoản</h3>
                    <p class="text-muted" style="font-size: 0.9rem;">(ID: ${localStorage.getItem("userId")})</p>
                </div>

                <form id="profile-form" class="modern-form">
                    <div class="form-group">
                        <label>Họ và tên</label>
                        <input type="text" id="prof-name" value="${user.name || ""}" placeholder="Nhập tên của bạn">
                    </div>
                    <div class="form-group">
                        <label>Email</label>
                        <input type="email" id="prof-email" value="${user.email || ""}" placeholder="Nhập email">
                    </div>
                    <div class="form-group">
                        <label>Số điện thoại</label>
                        <input type="tel" id="prof-phone" value="${user.phone || ""}" placeholder="Nhập SĐT">
                    </div>
                    
                    <button type="submit" class="btn-primary glow-effect" style="margin-top: 1rem; width: 100%;">
                        <i class="fa-solid fa-floppy-disk"></i> Lưu thay đổi
                    </button>
                    <p id="profile-msg" style="margin-top: 1rem; font-size: 0.9rem; text-align: center; height: 20px;"></p>
                </form>
            </div>
        `;

    document
      .getElementById("profile-form")
      .addEventListener("submit", async (e) => {
        e.preventDefault();
        const msgEl = document.getElementById("profile-msg");
        msgEl.textContent = "Đang lưu...";
        msgEl.style.color = "var(--text-muted)";

        try {
          await ProfileAPI.update({
            name: document.getElementById("prof-name").value,
            email: document.getElementById("prof-email").value,
            phone: document.getElementById("prof-phone").value,
          });
          msgEl.textContent = "";
          showToast("Đã lưu thay đổi thành công!", "success");
        } catch (err) {
          msgEl.textContent = "";
          showToast("Lỗi lưu thông tin: " + err.message, "error");
        }
      });
  } catch (error) {
    content.innerHTML = `
            <div class="view-header">
                <h2><i class="fa-regular fa-user"></i> Hồ sơ Cá nhân</h2>
            </div>
            <div class="error-state glass-panel text-danger">
                <i class="fa-solid fa-triangle-exclamation"></i>
                <p>Lỗi tải dữ liệu: ${error.message}</p>
            </div>
        `;
  }
}
