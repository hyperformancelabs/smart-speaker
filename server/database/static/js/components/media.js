import { MediaAPI } from "../services/api.js";

let cachedMedia = null;

function getYouTubeId(url) {
  if (!url) return null;
  const match = url.match(
    /(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))((\w|-){11})/,
  );
  return match ? match[1] : null;
}

export async function renderMedia(silent = false) {
  const content = document.getElementById("main-content");

  const buildUI = (mediaList) => {
    let html = `
            <div class="view-header">
                <h2><i class="fa-brands fa-youtube" style="color: #ff0000;"></i> Thư viện Video</h2>
            </div>
            <div class="media-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1.5rem;">
        `;

    if (!mediaList || mediaList.length === 0) {
      html += `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <i class="fa-brands fa-youtube" style="font-size: 3rem;"></i>
                    <p>Chưa có video nào trong thư viện.</p>
                </div>
            `;
    } else {
      mediaList.forEach((item) => {
        const ytId = getYouTubeId(item.url);
        const thumbUrl = ytId
          ? `https://img.youtube.com/vi/${ytId}/hqdefault.jpg`
          : "https://via.placeholder.com/600x400?text=No+Video";

        html += `
                    <div class="media-card glass-panel" style="overflow: hidden; display: flex; flex-direction: column; cursor: pointer; transition: transform 0.2s;" onmouseover="this.style.transform='translateY(-5px)'; this.querySelector('.play-btn').style.transform='scale(1.1)'; this.querySelector('.play-btn').style.color='#ff0000';" onmouseout="this.style.transform='translateY(0)'; this.querySelector('.play-btn').style.transform='scale(1)'; this.querySelector('.play-btn').style.color='white';" onclick="window.openYouTubeModal('${ytId || ""}')">
                        
                        <div style="height: 180px; position: relative; background: #000; display: flex; align-items: center; justify-content: center;">
                            <img src="${thumbUrl}" alt="Thumbnail" style="width: 100%; height: 100%; object-fit: cover; opacity: 0.8;">
                            <div class="play-btn" style="position: absolute; font-size: 3.5rem; color: white; transition: all 0.2s; text-shadow: 0 4px 10px rgba(0,0,0,0.5);">
                                <i class="fa-brands fa-youtube"></i>
                            </div>
                        </div>
                        
                        <div style="padding: 1.2rem 1rem; flex: 1; background: var(--bg-panel);">
                            <h4 style="font-size: 1.1rem; color: var(--text-main); font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 0.5rem;" title="${item.title || item.name || "Video Youtube"}">
                                ${item.title || item.name || "Video Youtube"}
                            </h4>
                            <p style="font-size: 0.9rem; color: var(--text-muted);"><i class="fa-regular fa-user" style="margin-right: 4px;"></i> ${item.artist || item.author || "Không rõ nguồn"}</p>
                        </div>
                    </div>
                `;
      });
    }

    html += `
            </div>
            
            <!-- Video Modal Overlay -->
            <div id="yt-modal" class="confirm-overlay" style="display: none; padding: 1rem; z-index: 100000; background: rgba(0,0,0,0.9);">
               <div style="width: 100%; max-width: 900px; position: relative; animation: popIn 0.3s ease forwards;">
                  <button onclick="window.closeYouTubeModal()" style="position: absolute; top: -45px; right: 0; background: transparent; color: white; border: none; font-size: 2.2rem; cursor: pointer; opacity: 0.8;" onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.8'"><i class="fa-solid fa-xmark"></i></button>
                  <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; border-radius: 8px; background: #000; box-shadow: 0 10px 40px rgba(0,0,0,0.5);">
                      <iframe id="yt-iframe" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0;" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
                  </div>
               </div>
            </div>
        `;
    content.innerHTML = html;
  };

  if (!silent && !cachedMedia) {
    content.innerHTML = `
            <div class="view-header">
                <h2><i class="fa-brands fa-youtube" style="color: #ff0000;"></i> Thư viện Video</h2>
            </div>
            <div class="glass-panel content-loading">
                <i class="fa-solid fa-circle-notch fa-spin"></i> Đang tải danh sách...
            </div>
        `;
  } else if (!silent && cachedMedia) {
    buildUI(cachedMedia);
  }

  try {
    const mediaList = await MediaAPI.getAll();
    if (JSON.stringify(mediaList) !== JSON.stringify(cachedMedia)) {
      cachedMedia = mediaList;
      buildUI(mediaList);
    }
  } catch (error) {
    if (!cachedMedia) {
      content.innerHTML = `
                <div class="view-header">
                    <h2><i class="fa-brands fa-youtube" style="color: #ff0000;"></i> Thư viện Video</h2>
                </div>
                <div class="error-state glass-panel text-danger">
                    <i class="fa-solid fa-triangle-exclamation"></i>
                    <p>Lỗi kết nối Youtube Data: ${error.message}</p>
                </div>
            `;
    }
  }

  // Global Event Handlers for UI Modal
  window.openYouTubeModal = (ytId) => {
    if (!ytId) {
      showToast("Video này không có link Youtube hợp lệ!", "error");
      return;
    }
    document.getElementById("yt-modal").style.display = "flex";
    // Auto play when modal opens
    document.getElementById("yt-iframe").src =
      `https://www.youtube.com/embed/${ytId}?autoplay=1`;
  };

  window.closeYouTubeModal = () => {
    document.getElementById("yt-modal").style.display = "none";
    // Stop video buffer
    document.getElementById("yt-iframe").src = "";
  };
}
