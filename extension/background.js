const DEFAULT_SERVER = "http://localhost:8000";
// Where Stepcast runs (Options page). The same address serves the API and the editor.
const server = async () => ((await chrome.storage.sync.get("server")).server || DEFAULT_SERVER).replace(/\/+$/, "");

// In-memory recording state, mirrored to storage.session in case the worker is restarted.
let rec = null; // { tabId, startedAt, events: [], error }
const loaded = chrome.storage.session.get("rec").then((s) => { rec = s.rec ?? null; });
const persist = () => chrome.storage.session.set({ rec });

async function ensureOffscreen() {
  if (await chrome.offscreen.hasDocument()) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA"],
    justification: "Record the tab for a help article",
  });
}

// Record at the page's own pixel size and shape. A fixed capture size (e.g. 4K 16:9) makes Chrome
// letterbox the page, which shifts every highlight and blur box away from its element.
async function captureSize(tabId) {
  const tab = await chrome.tabs.get(tabId);
  const v = (await chrome.tabs.sendMessage(tabId, { type: "viewport" }).catch(() => null)) ?? { w: tab.width, h: tab.height, dpr: 1 };
  const k = Math.min(1, 3840 / (v.w * v.dpr), 2160 / (v.h * v.dpr)); // cap at 4K
  const even = (n) => Math.max(2, Math.round(n / 2) * 2);
  return { width: even(v.w * v.dpr * k), height: even(v.h * v.dpr * k) };
}

async function start(tabId, mic) {
  const size = await captureSize(tabId);
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
  await ensureOffscreen();
  rec = { tabId, startedAt: null, events: [], recording: true, error: "", server: await server() };
  await persist();
  await chrome.runtime.sendMessage({ target: "offscreen", type: "start", streamId, mic, size, server: rec.server });
}

async function stop() {
  if (!rec?.recording) return;
  rec.recording = false;
  await persist();
  chrome.tabs.sendMessage(rec.tabId, { type: "recording", on: false }).catch(() => {});
  const startedAt = rec.startedAt ?? Date.now();
  const events = rec.events.map(({ ts, ...e }) => ({ ...e, t: Math.max(0, ts - startedAt) }));
  await chrome.runtime.sendMessage({ target: "offscreen", type: "stop", events });
}

async function finish(error, id) {
  if (rec) rec.error = error || "";
  await persist();
  if (id) chrome.tabs.create({ url: `${rec?.server || (await server())}/#/a/${id}` });
  if (await chrome.offscreen.hasDocument()) await chrome.offscreen.closeDocument();
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.target === "offscreen") return;
  loaded.then(async () => {
    switch (msg.type) {
      case "status":
        return reply({ recording: !!rec?.recording, startedAt: rec?.startedAt, error: rec?.error || "" });
      case "isRecording":
        return reply(!!rec?.recording && rec.startedAt !== null && sender.tab?.id === rec.tabId);
      case "start":
        try {
          await start(msg.tabId, msg.mic);
          reply({ ok: true });
        } catch (e) {
          await finish(String(e.message || e));
          reply({ ok: false, error: String(e.message || e) });
        }
        return;
      case "started": // offscreen recorder is running: tell the tab to start logging actions
        rec.startedAt = msg.startedAt;
        await persist();
        chrome.tabs.sendMessage(rec.tabId, { type: "recording", on: true }).catch(() => {});
        return;
      case "event":
        if (rec?.recording && sender.tab?.id === rec.tabId) {
          rec.events.push(msg.event);
          persist();
        }
        return;
      case "stop":
        await stop();
        return reply({ ok: true });
      case "uploaded":
        return finish("", msg.id);
      case "failed":
        if (rec) rec.recording = false;
        return finish(msg.error);
    }
  });
  return true; // async reply
});
