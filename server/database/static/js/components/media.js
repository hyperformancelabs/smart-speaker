export function renderMedia() {
  const content = document.getElementById("main-content");
  content.innerHTML = `
        <div class="view-header">
            <h2><i class="fa-brands fa-youtube" style="color: #ff0000;"></i> Thư viện Video</h2>
        </div>
        <div class="glass-panel empty-state">
            <i class="fa-brands fa-youtube"></i>
            <p>Phần giao diện video đã được đưa vào, nhưng service database hiện tại chưa có API media tương ứng.</p>
            <p>Backend/media logic của project được giữ nguyên theo yêu cầu nên tab này đang ở trạng thái chờ tích hợp.</p>
        </div>
    `;
}
