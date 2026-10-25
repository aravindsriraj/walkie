// Usage: node render.mjs jobs.json   where jobs = [{ out, props }]
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

// Remotion's bundled chrome-headless-shell hangs on recent macOS; prefer the installed Chrome.
const SYSTEM_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browserExecutable = process.env.STEPCAST_CHROME ?? (existsSync(SYSTEM_CHROME) ? SYSTEM_CHROME : null);

const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const serveUrl = await bundle({ entryPoint: path.resolve("src/index.ts") });

for (const { out, props } of jobs) {
  const opts = { serveUrl, inputProps: props, browserExecutable };
  const composition = await selectComposition({ ...opts, id: "StepClip" });
  await renderMedia({ ...opts, composition, codec: "h264", outputLocation: out });
  console.log("rendered", out);
}
