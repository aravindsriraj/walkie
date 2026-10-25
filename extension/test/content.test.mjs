import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
import { JSDOM } from "jsdom";

const { targetOf, elementLabel, isSensitive, redactRects, makeEvent } = createRequire(import.meta.url)("../content.js");

function page(html) {
  const dom = new JSDOM(`<body>${html}</body>`, { url: "https://app.test/settings" });
  const doc = dom.window.document;
  // jsdom has no layout: give every element a visible box.
  dom.window.Element.prototype.getBoundingClientRect = () => ({ left: 10, top: 20, width: 100, height: 30, right: 110, bottom: 50 });
  return doc;
}

test("password value is blanked and the field is redacted", () => {
  const doc = page('<input type="password" id="p" value="hunter2">');
  const el = doc.getElementById("p");
  assert.equal(isSensitive(el), true);
  const ev = makeEvent("input", el, { value: "" });
  assert.equal(ev.value, "");
  assert.ok(!JSON.stringify(ev).includes("hunter2"));
  assert.deepEqual(ev.redact, [{ x: 10, y: 20, w: 100, h: 30 }]);
});

test("labels prefer aria-label, then text, then placeholder", () => {
  const doc = page('<button id="a" aria-label="Close dialog">X</button><button id="b"> Save  changes </button><input id="c" placeholder="Search">');
  assert.equal(elementLabel(doc.getElementById("a")), "Close dialog");
  assert.equal(elementLabel(doc.getElementById("b")), "Save changes");
  assert.equal(elementLabel(doc.getElementById("c")), "Search");
});

test("label from <label for> and emails masked in labels", () => {
  const doc = page('<label for="n">Project name</label><input id="n"><a id="m">Invite ada@acme.com</a>');
  assert.equal(elementLabel(doc.getElementById("n")), "Project name");
  assert.equal(elementLabel(doc.getElementById("m")), "Invite •••");
});

test("targetOf climbs from inner span to the button", () => {
  const doc = page('<button id="b"><span id="s">Go</span></button>');
  assert.equal(targetOf(doc.getElementById("s")).id, "b");
});

test("redactRects finds email inputs and data-stepcast-redact, not plain fields", () => {
  const doc = page('<input type="email"><input id="plain" value="hello"><div data-stepcast-redact>secret</div><input value="x@y.io">');
  assert.equal(redactRects(doc).length, 3);
  assert.equal(isSensitive(doc.getElementById("plain")), false);
});

test("visible email text is redacted even outside form fields", () => {
  const doc = page('<header>Signed in as <b>ada@acme.com</b></header><p>No secrets here</p>');
  assert.equal(redactRects(doc).length, 1);
});
