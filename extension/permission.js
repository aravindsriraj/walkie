document.getElementById("go").addEventListener("click", async () => {
  const out = document.getElementById("out");
  try {
    (await navigator.mediaDevices.getUserMedia({ audio: true })).getTracks().forEach((t) => t.stop());
    out.textContent = "Microphone enabled. You can close this tab.";
  } catch (e) {
    out.textContent = `Microphone blocked: ${e.message}`;
  }
});
