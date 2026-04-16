(function () {
  const bootstrap = window.ASSISTANT_LAB_BOOTSTRAP || {};
  const storageKeys = {
    deviceId: "assistantLab.deviceId",
    sessionState: "assistantLab.sessionState",
    conversationLog: "assistantLab.conversationLog",
  };

  const els = {
    healthBadge: document.getElementById("healthBadge"),
    healthMeta: document.getElementById("healthMeta"),
    refreshHealthBtn: document.getElementById("refreshHealthBtn"),
    userIdInput: document.getElementById("userIdInput"),
    nfcTagInput: document.getElementById("nfcTagInput"),
    deviceIdInput: document.getElementById("deviceIdInput"),
    resetSessionBtn: document.getElementById("resetSessionBtn"),
    refreshSessionsBtn: document.getElementById("refreshSessionsBtn"),
    smokeTestBtn: document.getElementById("smokeTestBtn"),
    autoplayCheckbox: document.getElementById("autoplayCheckbox"),
    sessionKeyValue: document.getElementById("sessionKeyValue"),
    pendingValue: document.getElementById("pendingValue"),
    textInput: document.getElementById("textInput"),
    sendTextBtn: document.getElementById("sendTextBtn"),
    clearComposerBtn: document.getElementById("clearComposerBtn"),
    recordBtn: document.getElementById("recordBtn"),
    audioFileInput: document.getElementById("audioFileInput"),
    sendFileBtn: document.getElementById("sendFileBtn"),
    recordingHint: document.getElementById("recordingHint"),
    selectedFileMeta: document.getElementById("selectedFileMeta"),
    playbackSummary: document.getElementById("playbackSummary"),
    playbackQueue: document.getElementById("playbackQueue"),
    playSequenceBtn: document.getElementById("playSequenceBtn"),
    wsHostInput: document.getElementById("wsHostInput"),
    wsPortInput: document.getElementById("wsPortInput"),
    wsPathInput: document.getElementById("wsPathInput"),
    firstUtteranceStateSelect: document.getElementById("firstUtteranceStateSelect"),
    startCaptureBtn: document.getElementById("startCaptureBtn"),
    refreshCaptureBtn: document.getElementById("refreshCaptureBtn"),
    stopCaptureBtn: document.getElementById("stopCaptureBtn"),
    conversationLog: document.getElementById("conversationLog"),
    responseJson: document.getElementById("responseJson"),
    sessionsJson: document.getElementById("sessionsJson"),
    captureJson: document.getElementById("captureJson"),
    toast: document.getElementById("toast"),
  };

  const state = {
    sessionState: loadJson(storageKeys.sessionState, {}),
    conversationLog: loadJson(storageKeys.conversationLog, []),
    playbackSequence: [],
    mediaRecorder: null,
    mediaStream: null,
    mediaChunks: [],
    selectedFile: null,
  };

  hydrateInputs();
  renderConversationLog();
  renderJson(els.responseJson, {});
  renderJson(els.sessionsJson, {});
  renderJson(els.captureJson, {});
  updateSessionMeta({}, null);
  attachEvents();
  refreshHealth();
  refreshSessions();
  refreshCaptureStatus();

  function hydrateInputs() {
    els.userIdInput.value = bootstrap.defaultUserId || "";
    els.nfcTagInput.value = bootstrap.defaultNfcTagId || "";
    els.deviceIdInput.value =
      localStorage.getItem(storageKeys.deviceId) ||
      bootstrap.defaultDeviceId ||
      createDeviceId();
    localStorage.setItem(storageKeys.deviceId, els.deviceIdInput.value);
    els.wsHostInput.value = bootstrap.defaultWsHost || "";
    els.wsPortInput.value = String(bootstrap.defaultWsPort || 81);
    els.wsPathInput.value = bootstrap.defaultWsPath || "/";
  }

  function attachEvents() {
    els.refreshHealthBtn.addEventListener("click", refreshHealth);
    els.refreshSessionsBtn.addEventListener("click", refreshSessions);
    els.resetSessionBtn.addEventListener("click", resetSession);
    els.smokeTestBtn.addEventListener("click", runSmokeTest);
    els.sendTextBtn.addEventListener("click", sendTextTurn);
    els.clearComposerBtn.addEventListener("click", () => {
      els.textInput.value = "";
      els.textInput.focus();
    });
    els.playSequenceBtn.addEventListener("click", () => playSequence(state.playbackSequence));
    els.recordBtn.addEventListener("click", toggleRecording);
    els.audioFileInput.addEventListener("change", onAudioFileSelected);
    els.sendFileBtn.addEventListener("click", sendSelectedFile);
    els.startCaptureBtn.addEventListener("click", startCapture);
    els.refreshCaptureBtn.addEventListener("click", refreshCaptureStatus);
    els.stopCaptureBtn.addEventListener("click", stopCapture);
    els.deviceIdInput.addEventListener("change", () => {
      localStorage.setItem(storageKeys.deviceId, els.deviceIdInput.value.trim());
    });
    els.textInput.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
        event.preventDefault();
        sendTextTurn();
      }
    });
  }

  function createDeviceId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return `browser-${window.crypto.randomUUID()}`;
    }
    return `browser-${Date.now()}`;
  }

  function loadJson(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      return parsed ?? fallback;
    } catch (_error) {
      return fallback;
    }
  }

  function persistState() {
    localStorage.setItem(storageKeys.sessionState, JSON.stringify(state.sessionState || {}));
    localStorage.setItem(storageKeys.conversationLog, JSON.stringify(state.conversationLog || []));
  }

  function buildIdentityPayload() {
    return {
      user_id: els.userIdInput.value.trim(),
      nfc_tag_id: els.nfcTagInput.value.trim(),
      device_id: els.deviceIdInput.value.trim(),
    };
  }

  function buildTurnPayload() {
    return {
      ...buildIdentityPayload(),
      session_state: state.sessionState || {},
    };
  }

  async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch (_error) {
      payload = { error: text || `HTTP ${response.status}` };
    }
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with status ${response.status}`);
    }
    return payload;
  }

  async function refreshHealth() {
    try {
      const payload = await fetchJson("/health");
      els.healthBadge.textContent = payload.status || "ok";
      els.healthBadge.className = "badge badge-ok";
      els.healthMeta.textContent = `${payload.service || "backend"} | ${payload.public_base_url || ""}`.trim();
    } catch (error) {
      els.healthBadge.textContent = "error";
      els.healthBadge.className = "badge badge-error";
      els.healthMeta.textContent = error.message;
      showToast(error.message, true);
    }
  }

  async function refreshSessions() {
    try {
      const payload = await fetchJson("/api/dev/sessions");
      renderJson(els.sessionsJson, payload);
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function refreshCaptureStatus() {
    try {
      const payload = await fetchJson("/api/audio/status");
      renderJson(els.captureJson, payload);
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function resetSession() {
    try {
      await fetchJson("/api/dev/session/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildIdentityPayload()),
      });
      state.sessionState = {};
      state.conversationLog = [];
      state.playbackSequence = [];
      persistState();
      renderConversationLog();
      renderPlayback({});
      renderJson(els.responseJson, {});
      updateSessionMeta({}, null);
      await refreshSessions();
      showToast("Đã reset session trên cả client và backend.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function runSmokeTest() {
    try {
      const payload = await fetchJson("/api/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...buildIdentityPayload(),
          session_state: state.sessionState || {},
        }),
      });
      renderJson(els.responseJson, payload);
      if (payload.output) {
        consumeAssistantResult(payload.output, payload.input || "Smoke test", "text");
      }
      await refreshSessions();
      showToast("Smoke test hoàn tất.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  async function sendTextTurn() {
    const text = els.textInput.value.trim();
    if (!text) {
      showToast("Nhập nội dung trước khi gửi text turn.", true);
      return;
    }

    toggleBusy(els.sendTextBtn, true, "Đang gửi...");
    try {
      const payload = await fetchJson("/api/dev/assistant-turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...buildTurnPayload(),
          text_input: text,
        }),
      });
      consumeAssistantResult(payload, text, "text");
      renderJson(els.responseJson, payload);
      await refreshSessions();
    } catch (error) {
      showToast(error.message, true);
    } finally {
      toggleBusy(els.sendTextBtn, false, "Gửi text turn");
    }
  }

  async function sendSelectedFile() {
    if (!state.selectedFile) {
      showToast("Chưa có file audio nào được chọn.", true);
      return;
    }
    await sendAudioFormData(state.selectedFile, state.selectedFile.name);
  }

  async function sendAudioBlob(blob, filename) {
    const ext = inferExtension(blob.type);
    const file = new File([blob], filename || `browser-recording${ext}`, { type: blob.type || "audio/webm" });
    await sendAudioFormData(file, file.name);
  }

  async function sendAudioFormData(file, filename) {
    toggleBusy(els.sendFileBtn, true, "Đang upload...");
    try {
      const formData = new FormData();
      const turnPayload = buildTurnPayload();
      formData.append("audio", file, filename);
      formData.append("user_id", turnPayload.user_id);
      formData.append("nfc_tag_id", turnPayload.nfc_tag_id);
      formData.append("device_id", turnPayload.device_id);
      formData.append("session_state", JSON.stringify(turnPayload.session_state || {}));

      const payload = await fetchJson("/api/dev/assistant-turn", {
        method: "POST",
        body: formData,
      });
      const transcriptText =
        (payload.transcription && payload.transcription.text) ||
        (payload.input && payload.input.text) ||
        filename;
      consumeAssistantResult(payload, transcriptText, "audio");
      renderJson(els.responseJson, payload);
      await refreshSessions();
      showToast("Audio turn đã được xử lý.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      toggleBusy(els.sendFileBtn, false, "Upload file");
    }
  }

  function consumeAssistantResult(payload, userText, mode) {
    state.sessionState = payload.session_state || {};
    persistState();
    updateSessionMeta(payload, payload.session_key || null);
    appendConversation("user", mode === "audio" ? `Audio transcript: ${userText}` : userText);
    appendConversation("assistant", payload.tts_text || "(Assistant không trả về tts_text)");
    renderPlayback(payload);
    if (els.autoplayCheckbox.checked) {
      playSequence(state.playbackSequence).catch((error) => {
        showToast(`Không tự phát được audio: ${error.message}`, true);
      });
    }
  }

  function appendConversation(role, text) {
    const cleaned = String(text || "").trim();
    if (!cleaned) return;
    state.conversationLog.push({ role, text: cleaned, timestamp: new Date().toISOString() });
    state.conversationLog = state.conversationLog.slice(-24);
    persistState();
    renderConversationLog();
  }

  function renderConversationLog() {
    const items = state.conversationLog || [];
    if (!items.length) {
      els.conversationLog.innerHTML = '<div class="message"><span class="message-role">system</span><p class="message-text">Chưa có turn nào trong session hiện tại.</p></div>';
      return;
    }

    els.conversationLog.innerHTML = items
      .map(
        (item) => `
          <div class="message message-${escapeHtml(item.role)}">
            <span class="message-role">${escapeHtml(item.role)}</span>
            <p class="message-text">${escapeHtml(item.text)}</p>
          </div>
        `,
      )
      .join("");
  }

  function updateSessionMeta(payload, sessionKey) {
    const route = payload.route || {};
    const dialog = payload.dialog || {};
    els.sessionKeyValue.textContent = sessionKey || route.group || "-";
    els.pendingValue.textContent = dialog.pending_question || "Không có pending";
  }

  function renderPlayback(payload) {
    const playbackSequence = Array.isArray(payload.playback_sequence) ? payload.playback_sequence : [];
    state.playbackSequence = playbackSequence;

    if (!playbackSequence.length) {
      els.playbackSummary.textContent = "Turn này không có asset playback nào được server trả về.";
      els.playbackQueue.innerHTML = "";
      return;
    }

    els.playbackSummary.textContent = `Server đã trả về ${playbackSequence.length} mục playback theo đúng thứ tự phát cho thiết bị.`;
    els.playbackQueue.innerHTML = playbackSequence
      .map(
        (item, index) => `
          <article class="playback-card">
            <h3>${index + 1}. ${escapeHtml(item.kind || "audio")}</h3>
            <p>${escapeHtml(item.label || item.url || "")}</p>
            <audio controls preload="none" src="${encodeURI(item.url || "")}"></audio>
          </article>
        `,
      )
      .join("");
  }

  async function playSequence(sequence) {
    if (!Array.isArray(sequence) || !sequence.length) {
      showToast("Không có playback sequence để phát.", true);
      return;
    }

    for (const item of sequence) {
      await playAudioItem(item);
    }
  }

  function playAudioItem(item) {
    return new Promise((resolve, reject) => {
      const audio = new Audio(item.url);
      audio.addEventListener("ended", () => resolve(), { once: true });
      audio.addEventListener("error", () => reject(new Error(`Không phát được ${item.label || item.url}`)), {
        once: true,
      });
      audio
        .play()
        .then(() => undefined)
        .catch(reject);
    });
  }

  async function startCapture() {
    const wsHost = els.wsHostInput.value.trim();
    if (!wsHost) {
      showToast("Nhập WS Host của ESP trước khi start capture.", true);
      return;
    }

    toggleBusy(els.startCaptureBtn, true, "Đang start...");
    try {
      const payload = await fetchJson("/api/audio/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...buildIdentityPayload(),
          ws_host: wsHost,
          ws_port: Number(els.wsPortInput.value || 81),
          ws_path: els.wsPathInput.value.trim() || "/",
          first_utterance_state: els.firstUtteranceStateSelect.value,
        }),
      });
      renderJson(els.captureJson, payload);
      showToast("Đã gửi lệnh start capture.");
    } catch (error) {
      showToast(error.message, true);
    } finally {
      toggleBusy(els.startCaptureBtn, false, "Start capture");
    }
  }

  async function stopCapture() {
    try {
      const payload = await fetchJson("/api/audio/stop", { method: "POST" });
      renderJson(els.captureJson, payload);
      showToast("Đã gửi lệnh stop capture.");
    } catch (error) {
      showToast(error.message, true);
    }
  }

  function onAudioFileSelected() {
    state.selectedFile = els.audioFileInput.files && els.audioFileInput.files[0] ? els.audioFileInput.files[0] : null;
    if (!state.selectedFile) {
      els.selectedFileMeta.textContent = "Chưa chọn file.";
      return;
    }
    els.selectedFileMeta.textContent = `${state.selectedFile.name} | ${(state.selectedFile.size / 1024).toFixed(1)} KB | ${state.selectedFile.type || "unknown"}`;
  }

  async function toggleRecording() {
    if (state.mediaRecorder && state.mediaRecorder.state === "recording") {
      state.mediaRecorder.stop();
      updateRecordUi(false);
      return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showToast("Browser này không hỗ trợ getUserMedia.", true);
      return;
    }

    try {
      state.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.mediaChunks = [];
      const mimeType = pickMimeType();
      state.mediaRecorder = mimeType ? new MediaRecorder(state.mediaStream, { mimeType }) : new MediaRecorder(state.mediaStream);
      state.mediaRecorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size) {
          state.mediaChunks.push(event.data);
        }
      });
      state.mediaRecorder.addEventListener("stop", async () => {
        const blob = new Blob(state.mediaChunks, { type: state.mediaRecorder.mimeType || "audio/webm" });
        stopMediaTracks();
        if (blob.size) {
          await sendAudioBlob(blob, `browser-recording${inferExtension(blob.type)}`);
        }
      });
      state.mediaRecorder.start();
      updateRecordUi(true);
      showToast("Đang ghi âm. Nhấn lại để dừng và gửi lên server.");
    } catch (error) {
      stopMediaTracks();
      showToast(`Không mở được microphone: ${error.message}`, true);
    }
  }

  function updateRecordUi(isRecording) {
    els.recordBtn.textContent = isRecording ? "Dừng ghi âm và gửi" : "Bắt đầu ghi âm";
    els.recordingHint.textContent = isRecording
      ? "Đang ghi âm từ browser. Khi dừng, file sẽ được upload ngay lên server."
      : "Browser sẽ thu audio và gửi lên endpoint debug để test STT server.";
  }

  function stopMediaTracks() {
    if (state.mediaStream) {
      state.mediaStream.getTracks().forEach((track) => track.stop());
    }
    state.mediaStream = null;
  }

  function pickMimeType() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ];
    for (const candidate of candidates) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(candidate)) {
        return candidate;
      }
    }
    return "";
  }

  function inferExtension(mimeType) {
    const normalized = String(mimeType || "").toLowerCase();
    if (normalized.includes("ogg")) return ".ogg";
    if (normalized.includes("mp4") || normalized.includes("m4a")) return ".m4a";
    if (normalized.includes("wav")) return ".wav";
    return ".webm";
  }

  function renderJson(element, payload) {
    element.textContent = JSON.stringify(payload || {}, null, 2);
  }

  function toggleBusy(element, busy, label) {
    element.disabled = busy;
    element.textContent = label;
  }

  function showToast(message, isError = false) {
    els.toast.textContent = message;
    els.toast.style.background = isError ? "rgba(114, 27, 17, 0.96)" : "rgba(11, 24, 35, 0.92)";
    els.toast.classList.add("toast-visible");
    window.clearTimeout(showToast._timer);
    showToast._timer = window.setTimeout(() => {
      els.toast.classList.remove("toast-visible");
    }, 2600);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }
})();
