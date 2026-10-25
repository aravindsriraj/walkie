// Real-extension end-to-end test: loads extension/ into Chromium, records the demo app through tabCapture +
// the offscreen MediaRecorder (with narration), stops, and checks upload → article → editor tab.
// Needs the API (127.0.0.1:8000) and editor (localhost:5173) running. Run: npm install && npm test
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import { mkdtempSync, readFileSync } from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const EXT = path.join(ROOT, "extension");
const API = "http://127.0.0.1:8000";
const SITE_PORT = 8090;
const check = (ok, msg) => {
  if (!ok) throw new Error(`FAIL: ${msg}`);
  console.log(`ok - ${msg}`);
};

// Demo app on 127.0.0.1:8090 (sign in → new project dialog), plus the narration clip.
const site = http.createServer((req, res) => {
  const file = req.url === "/" ? "index.html" : path.basename(req.url);
  let body;
  try {
    body = readFileSync(path.join(ROOT, "e2e/site", file));
  } catch {
    return res.writeHead(404).end();
  }
  res.writeHead(200, { "Content-Type": file.endsWith(".mp3") ? "audio/mpeg" : "text/html" }).end(body);
}).listen(SITE_PORT, "127.0.0.1");

// Unpacked extension id = first 32 hex chars of sha256(path), mapped 0-f → a-p.
const id = [...crypto.createHash("sha256").update(EXT).digest("hex").slice(0, 32)]
  .map((c) => String.fromCharCode(97 + parseInt(c, 16))).join("");

const ctx = await chromium.launchPersistentContext(mkdtempSync(path.join(os.tmpdir(), "stepcast-e2e-")), {
  channel: "chromium",
  headless: true,
  viewport: null, // the real window size, as users have it
  args: [
    "--window-size=1280,860",
    `--disable-extensions-except=${EXT}`,
    `--load-extension=${EXT}`,
    `--allowlisted-extension-id=${id}`, // test switch: tab capture without clicking the toolbar icon
    "--autoplay-policy=no-user-gesture-required",
  ],
});
try {
  const sw = ctx.serviceWorkers()[0] ?? (await ctx.waitForEvent("serviceworker", { timeout: 15000 }));
  check(sw.url().startsWith(`chrome-extension://${id}/`), "extension loaded");

  const popup = await ctx.newPage(); // stands in for the popup: sends the same messages popup.js does
  await popup.goto(`chrome-extension://${id}/popup.html`);
  const page = await ctx.newPage();
  await page.goto(`http://127.0.0.1:${SITE_PORT}/`);
  await page.bringToFront();
  const send = (msg) => popup.evaluate((m) => chrome.runtime.sendMessage(m), msg);

  // Narration: swap only the microphone. The offscreen recorder's audio getUserMedia gets speech from an
  // AudioContext; merging, recording, upload and transcription run for real.
  await sw.evaluate(() => ensureOffscreen());
  const cdp = await ctx.newCDPSession(page);
  const off = (await cdp.send("Target.getTargets")).targetInfos.find((t) => t.url.endsWith("/offscreen.html"));
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId: off.targetId, flatten: false });
  const stubbed = new Promise((resolve) => cdp.on("Target.receivedMessageFromTarget", (e) => {
    const m = JSON.parse(e.message);
    if (m.id === 1) resolve(m.result?.result?.value);
  }));
  const stub = `(() => {
    const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (c) => {
      if (!c.audio || c.video) return real(c);
      const ac = new AudioContext();
      const buf = await ac.decodeAudioData(await (await fetch("http://127.0.0.1:${SITE_PORT}/speech.mp3")).arrayBuffer());
      const src = ac.createBufferSource(); src.buffer = buf;
      const dst = ac.createMediaStreamDestination(); src.connect(dst); src.start();
      return dst.stream;
    };
    return "stubbed";
  })()`;
  await cdp.send("Target.sendMessageToTarget", { sessionId, message: JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: stub } }) });
  check((await stubbed) === "stubbed", "microphone swapped for narration audio");

  const tabId = await sw.evaluate(async (port) => (await chrome.tabs.query({ url: `http://127.0.0.1:${port}/*` }))[0].id, SITE_PORT);
  check((await send({ type: "start", tabId, mic: true })).ok, "start accepted");
  let status;
  for (let i = 0; i < 40 && !status?.startedAt && !status?.error; i++) {
    await page.waitForTimeout(250);
    status = await send({ type: "status" });
  }
  check(status.recording && status.startedAt, `recording started ${status.error ? `(error: ${status.error})` : ""}`);

  const pause = () => page.waitForTimeout(900);
  await pause();
  await page.click("#email"); await page.keyboard.type("ada@acme.com", { delay: 40 }); await pause();
  await page.click("#password"); await page.keyboard.type("hunter2-secret", { delay: 40 }); await pause();
  await page.click("#signin"); await pause();
  await page.click("#new"); await pause();
  await page.click("#pname"); await page.keyboard.type("Q4 Launch", { delay: 40 }); await pause();
  await page.selectOption("#vis", "Team"); await pause();
  await page.click("#create"); await page.waitForTimeout(1200);

  const editorTab = ctx.waitForEvent("page", { predicate: (p) => p.url().includes("localhost:5173/#/a/"), timeout: 60000 });
  check((await send({ type: "stop" })).ok, "stop accepted");
  const articleId = (await editorTab).url().split("/").pop();
  check(/^[0-9a-f]{12}$/.test(articleId), `editor tab opened on the new article (${articleId})`);

  let a;
  for (let i = 0; i < 120 && a?.status !== "ready" && a?.status !== "failed"; i++) {
    await page.waitForTimeout(500);
    a = await (await fetch(`${API}/articles/${articleId}`)).json();
  }
  check(a.status === "ready", `article ready ${a.error ? `(error: ${a.error})` : ""}`);
  check(a.steps.length >= 5, `${a.steps.length} steps: ${a.steps.map((s) => s.text).join(" | ")}`);

  const events = await (await fetch(`${API}/files/${articleId}/events.json`)).json();
  check(events.filter((e) => e.kind !== "navigate").length === 10, "all 10 actions captured");
  check(!JSON.stringify(events).includes("hunter2"), "password never left the page");
  check(events.some((e) => e.redact.length > 0), "sensitive fields reported for blurring");

  const video = path.join(ROOT, "server/data", articleId, "video.webm");
  const probe = (args) => execFileSync("ffprobe", ["-v", "error", ...args, "-of", "csv=p=0", video]).toString().trim();
  const [w, h] = probe(["-select_streams", "v", "-show_entries", "stream=width,height"]).split(",").map(Number);
  const vp = events[0].viewport;
  check(Math.abs(w - vp.w * vp.dpr) <= 2 && Math.abs(h - vp.h * vp.dpr) <= 2,
    `recorded at the page's own size (${w}x${h} for a ${vp.w}x${vp.h}@${vp.dpr} page), so highlights line up`);
  check(probe(["-show_entries", "stream=codec_type"]).includes("audio"), "narration track recorded");
  console.log("\nall extension checks passed");
} finally {
  await ctx.close();
  site.close();
}
