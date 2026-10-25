const toggle = document.getElementById("toggle");
const mic = document.getElementById("mic");
const status = document.getElementById("status");
let tick = null;

function show(s) {
  clearInterval(tick);
  toggle.textContent = s.recording ? "Stop & create article" : "Start recording";
  toggle.className = s.recording ? "stop" : "";
  mic.disabled = s.recording;
  status.className = s.error ? "error" : "";
  status.textContent = s.error;
  if (s.recording && s.startedAt) {
    const render = () => {
      const sec = Math.floor((Date.now() - s.startedAt) / 1000);
      status.textContent = `Recording ${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
    };
    render();
    tick = setInterval(render, 1000);
  }
}

const refresh = async () => show(await chrome.runtime.sendMessage({ type: "status" }));

toggle.addEventListener("click", async () => {
  const s = await chrome.runtime.sendMessage({ type: "status" });
  if (s.recording) {
    await chrome.runtime.sendMessage({ type: "stop" });
    status.textContent = "Uploading…";
    setTimeout(() => window.close(), 800);
    return;
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const res = await chrome.runtime.sendMessage({ type: "start", tabId: tab.id, mic: mic.checked });
  if (!res.ok) return show({ recording: false, error: res.error });
  setTimeout(refresh, 300);
});

chrome.storage.local.get("mic").then((s) => (mic.checked = !!s.mic));
mic.addEventListener("change", () => chrome.storage.local.set({ mic: mic.checked }));
refresh();
