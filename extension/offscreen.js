const API = "http://127.0.0.1:8000";
const MAX_MS = 10 * 60 * 1000;

let recorder = null;
let chunks = [];
let tracks = [];
let timer = null;

const tell = (msg) => chrome.runtime.sendMessage(msg);

async function start({ streamId, mic, size }) {
  const { width, height } = size;
  const video = await navigator.mediaDevices.getUserMedia({
    video: { mandatory: {
      chromeMediaSource: "tab", chromeMediaSourceId: streamId, maxFrameRate: 30,
      minWidth: width, maxWidth: width, minHeight: height, maxHeight: height,
    } },
  });
  tracks = video.getVideoTracks();
  if (mic) {
    try {
      tracks.push(...(await navigator.mediaDevices.getUserMedia({ audio: true })).getAudioTracks());
    } catch {
      // Mic not granted yet (see permission.html): record without narration.
    }
  }
  const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9") ? "video/webm;codecs=vp9" : "video/webm";
  chunks = [];
  recorder = new MediaRecorder(new MediaStream(tracks), { mimeType, videoBitsPerSecond: 6_000_000 });
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstart = () => tell({ type: "started", startedAt: Date.now() });
  recorder.start(1000);
  timer = setTimeout(() => tell({ type: "stop" }), MAX_MS);
}

function stop(events) {
  clearTimeout(timer);
  recorder.onstop = async () => {
    tracks.forEach((t) => t.stop());
    try {
      const body = new FormData();
      body.append("video", new Blob(chunks, { type: "video/webm" }), "video.webm");
      body.append("events", JSON.stringify(events));
      const res = await fetch(`${API}/recordings`, { method: "POST", body });
      if (!res.ok) throw new Error(`Upload failed (${res.status}): ${await res.text()}`);
      tell({ type: "uploaded", id: (await res.json()).id });
    } catch (e) {
      tell({ type: "failed", error: `${e.message || e}. Is the Stepcast server running?` });
    }
  };
  recorder.stop();
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.target !== "offscreen") return;
  if (msg.type === "start") start(msg).catch((e) => tell({ type: "failed", error: String(e.message || e) }));
  if (msg.type === "stop") stop(msg.events);
});
