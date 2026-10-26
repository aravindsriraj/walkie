// Records what the user clicks/types (labels + positions) while a Walkie recording is running.
// Sensitive values never leave the page: they're blanked here and their boxes are sent for blurring.
(() => {
  const INTERACTIVE =
    'button,a,input,select,textarea,summary,label,[role=button],[role=link],[role=menuitem],' +
    '[role=tab],[role=checkbox],[role=radio],[role=option],[role=switch],[contenteditable="true"]';
  const SENSITIVE_TYPES = new Set(["password", "email", "tel"]);
  const EMAIL = /[^\s@]+@[^\s@]+\.[^\s@]+/g;

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim().replace(EMAIL, "•••").slice(0, 80);
  const isField = (el) => ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);

  function targetOf(el) {
    if (el && el.nodeType !== 1) el = el.parentElement;
    return (el && el.closest(INTERACTIVE)) || el;
  }

  function isSensitive(el) {
    const ac = (el.getAttribute("autocomplete") || "").toLowerCase();
    EMAIL.lastIndex = 0;
    return (
      (el.tagName === "INPUT" && SENSITIVE_TYPES.has((el.type || "").toLowerCase())) ||
      /cc-|password|one-time-code/.test(ac) ||
      !!el.closest("[data-walkie-redact]") ||
      (isField(el) && EMAIL.test(el.value || ""))
    );
  }

  function elementLabel(el) {
    const doc = el.ownerDocument;
    const by = el.getAttribute("aria-labelledby");
    const labelled = by && by.split(/\s+/).map((id) => doc.getElementById(id)?.textContent || "").join(" ");
    const text = isField(el) ? "" : el.innerText || el.textContent;
    const buttonValue = el.tagName === "INPUT" && ["submit", "button"].includes(el.type) ? el.value : "";
    return (
      clean(
        el.getAttribute("aria-label") || labelled || el.labels?.[0]?.textContent || text || buttonValue ||
          el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("alt") || el.getAttribute("name"),
      ) || el.tagName.toLowerCase()
    );
  }

  const box = (r) => ({ x: r.left, y: r.top, w: r.width, h: r.height });

  // Elements whose visible text contains an email address (e.g. "Signed in as ada@acme.com").
  function emailTextElements(doc) {
    const walker = doc.createTreeWalker(doc.body || doc.documentElement, 4 /* NodeFilter.SHOW_TEXT */);
    const out = new Set();
    // ponytail: capped text-node scan per event; enough for app UIs, very long pages may miss some.
    for (let n = walker.nextNode(), i = 0; n && i < 5000; n = walker.nextNode(), i++) {
      EMAIL.lastIndex = 0;
      if (n.parentElement && EMAIL.test(n.nodeValue)) out.add(n.parentElement);
    }
    return [...out];
  }

  function redactRects(doc) {
    const win = doc.defaultView;
    const fields = [...doc.querySelectorAll("input,textarea,[data-walkie-redact]")].filter(isSensitive);
    return [...fields, ...emailTextElements(doc)]
      .map((el) => el.getBoundingClientRect())
      .filter((r) => r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < win.innerHeight && r.left < win.innerWidth)
      .map(box);
  }

  function fieldValue(el) {
    if (isSensitive(el)) return "";
    if (el.tagName === "SELECT") return clean(el.selectedOptions?.[0]?.textContent);
    return clean(el.value);
  }

  function makeEvent(kind, el, extra = {}) {
    const doc = el.ownerDocument;
    const win = doc.defaultView;
    return {
      ts: Date.now(),
      kind,
      url: win.location.href,
      viewport: { w: win.innerWidth, h: win.innerHeight, dpr: win.devicePixelRatio || 1 },
      rect: box(el.getBoundingClientRect()),
      label: elementLabel(el),
      tag: el.tagName.toLowerCase(),
      value: "",
      key: "",
      redact: redactRects(doc),
      ...extra,
    };
  }

  // Where to blur, with no action attached: sent when the page scrolls or changes, so the video stays blurred
  // between clicks, not just at them.
  function redactEvent(doc) {
    const win = doc.defaultView;
    return {
      ts: Date.now(), kind: "redact", url: win.location.href,
      viewport: { w: win.innerWidth, h: win.innerHeight, dpr: win.devicePixelRatio || 1 },
      rect: null, label: "", tag: "", value: "", key: "", redact: redactRects(doc),
    };
  }

  const near = (a, b) => Math.abs(a - b) < 1;
  const sameRects = (a, b) =>
    a.length === b.length && a.every((r, i) => near(r.x, b[i].x) && near(r.y, b[i].y) && near(r.w, b[i].w) && near(r.h, b[i].h));

  if (typeof module !== "undefined") {
    module.exports = { targetOf, elementLabel, isSensitive, redactRects, makeEvent, redactEvent, sameRects };
    return;
  }

  let recording = false;
  // `change` fires on blur, often at the next click. Stamp inputs at the last keystroke instead,
  // so the frame shows the typed value on the screen it was typed on.
  const lastTyped = new WeakMap();
  const send = (event) => chrome.runtime.sendMessage({ type: "event", event }).catch(() => {});

  let lastRedact = [];
  let redactTimer = 0;
  // At most every 500 ms, and only when the boxes moved, appeared or went away.
  function snapshotRedact() {
    if (!recording || redactTimer) return;
    redactTimer = setTimeout(() => {
      redactTimer = 0;
      if (!recording) return;
      const ev = redactEvent(document);
      if (sameRects(ev.redact, lastRedact)) return;
      lastRedact = ev.redact;
      send(ev);
    }, 500);
  }
  addEventListener("scroll", snapshotRedact, true);
  addEventListener("resize", snapshotRedact);
  new MutationObserver(snapshotRedact).observe(document.documentElement, { childList: true, subtree: true, characterData: true });

  function start() {
    recording = true;
    const first = makeEvent("navigate", document.documentElement);
    lastRedact = first.redact;
    send({ ...first, rect: null, label: document.title });
  }

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (msg.type === "recording") msg.on ? start() : (recording = false);
    if (msg.type === "viewport") reply({ w: innerWidth, h: innerHeight, dpr: devicePixelRatio || 1 });
  });
  chrome.runtime.sendMessage({ type: "isRecording" }).then((on) => on && start()).catch(() => {});

  document.addEventListener("click", (e) => {
    if (!recording || !e.isTrusted) return;
    const el = targetOf(e.target);
    if (el) send(makeEvent("click", el));
  }, true);

  document.addEventListener("input", (e) => {
    if (recording && isField(e.target)) lastTyped.set(e.target, { ts: Date.now(), rect: box(e.target.getBoundingClientRect()) });
  }, true);

  document.addEventListener("change", (e) => {
    const el = e.target;
    if (!recording || !isField(el) || ["checkbox", "radio"].includes(el.type)) return;
    send(makeEvent("input", el, { value: fieldValue(el), ...lastTyped.get(el) }));
  }, true);

  document.addEventListener("keydown", (e) => {
    if (!recording || e.key !== "Enter" || !e.isTrusted || !isField(e.target)) return;
    send(makeEvent("keydown", e.target, { key: "Enter" }));
  }, true);
})();
