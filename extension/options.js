const DEFAULT_SERVER = "http://localhost:8000";
const input = document.getElementById("server");
const result = document.getElementById("result");
const say = (text, ok) => { result.textContent = text; result.className = ok ? "ok" : "bad"; };
const value = () => (input.value.trim() || DEFAULT_SERVER).replace(/\/+$/, "");

chrome.storage.sync.get("server").then((s) => { input.value = s.server || DEFAULT_SERVER; });

document.getElementById("save").addEventListener("click", async () => {
  try {
    new URL(value());
  } catch {
    return say("That isn't a web address. It looks like http://localhost:8000.", false);
  }
  await chrome.storage.sync.set({ server: value() });
  say("Saved.", true);
});

document.getElementById("test").addEventListener("click", async () => {
  say("Checking…", true);
  try {
    const res = await fetch(`${value()}/languages`);
    if (!res.ok) throw new Error(String(res.status));
    say(`Connected to Walkie at ${value()}.`, true);
  } catch {
    say(`Can't reach Walkie at ${value()}. Check that it's running and the address is right.`, false);
  }
});
