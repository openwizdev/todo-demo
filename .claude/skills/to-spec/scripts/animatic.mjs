#!/usr/bin/env node
// to-spec's steering video (#1339, J204): an animatic, adapted from Matt
// Pocock's `animatic` skill (storyboard, Playwright frames, voice, ffmpeg).
// One still frame per moment, held while its one spoken line plays.
//
//   node animatic.mjs check <storyboard.json> [--target 90]
//   node animatic.mjs build <storyboard.json> [-o spec.mp4] [--target 90] [--tts-command "<cmd>"] [--voice <name>]
//   node animatic.mjs link <https url>
//
// A storyboard is a JSON array of moments, {"say", "frame"}, in playback
// order. Frames are `title` (first, once), `user` (what changes for a user)
// and `codebase` (what changes in the code), each change with its build
// `step`: 1 first, never going back, never skipping. There is no graph,
// diagram, image or page frame, and no line or frame may name a graph or a
// bench: the graph stays on the spec as the agents' document.
//
// `build` checks first and renders nothing on a refusal. Then: frames ->
// PNG (playwright-core's Chromium: $OPENWIZ_CHROMIUM, else `chromium` on
// PATH), lines -> WAV (--tts-command, else espeak-ng, espeak or say), and
// ffmpeg stitches a constant 30 fps H.264/AAC MP4, verified with ffprobe,
// plus build/sheet.png, every frame in order. Frames, lines and the sheet land
// in `build/` beside the storyboard; the MP4 is staged beside its output, on
// the output's filesystem, and published only once verified, never over a file. playwright-core is read from the working folder's
// node_modules, else $ANIMATIC_HOME (default ~/.cache/animatic), where it is
// installed, pinned, on first use.
//
// --tts-command, as in Matt's: the line arrives on stdin and as {text}; {out}
// is a path with no extension, and the command writes {out}.wav (or .mp3,
// .aiff): it is converted to WAV here. Each moment needs its own new, audible
// take and a command that exits 0, or the build fails and names the moment.
//
// Exit 0: done, one short report on stdout. 1: refused or failed, one
// `animatic: <why>` line per reason on stderr. 2: bad arguments.

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

const WIDTH = 1280;
const HEIGHT = 720;
const HOLD = 0.4; // seconds each frame stays after its line
const PLAYWRIGHT = "playwright-core@1.64.1";
const HOME = process.env.ANIMATIC_HOME ?? path.join(os.homedir(), ".cache", "animatic");
const BANNED = /\b(bench(mark)?(s|ed|ing)?|graphs?)\b/i;
const TEXT_MAX = 70;

const fail = (reasons, code = 1) => {
  for (const r of [].concat(reasons)) console.error(`animatic: ${r}`);
  process.exit(code);
};

// ---- arguments ----
const [verb, ...rest] = process.argv.slice(2);
const flags = {};
const positional = [];
for (let i = 0; i < rest.length; i++) {
  const a = rest[i];
  if (a === "-o" || a.startsWith("--")) {
    const key = a === "-o" ? "out" : a.slice(2);
    if (!["out", "target", "tts-command", "voice"].includes(key) || i + 1 >= rest.length) fail(`unknown or empty flag ${a}`, 2);
    flags[key] = rest[++i];
  } else positional.push(a);
}
if (!["check", "build", "link"].includes(verb) || positional.length !== 1) {
  fail("usage: animatic.mjs check|build <storyboard.json> [-o spec.mp4] [--target 90] [--tts-command <cmd>] | link <url>", 2);
}
const target = flags.target === undefined ? 90 : Number(flags.target);
if (!Number.isFinite(target) || target < 0) fail("--target is seconds, 0 for none", 2);

// ---- link ----
if (verb === "link") {
  const url = positional[0];
  let parts;
  try {
    parts = new URL(url);
  } catch {
    parts = null;
  }
  const raw = url.match(/^https:\/\/([^/?#]*)/);
  if (!parts || parts.protocol !== "https:" || !parts.hostname || parts.username || parts.password
      || !raw || raw[1].includes("@") || !/^[^:]+(:\d+)?$/.test(raw[1])
      || !/^https:\/\/[^\s\x00-\x1f\x7f<>()\\`]+$/.test(url)) {
    fail("use a verified HTTPS playback URL without credentials");
  }
  console.log(`[Watch the narrated spec](${url})`);
  process.exit(0);
}

// ---- check ----
const words = (s) => s.split(/\s+/).filter(Boolean).length;
const seconds = (say) => words(say) / 2.6 + 0.3 + HOLD; // about 155 words a minute

const check = (moments) => {
  const why = [];
  if (!Array.isArray(moments) || moments.length < 3 || moments.length > 24) return ["a storyboard is an array of 3 to 24 moments"];
  const keys = { title: ["type", "kicker", "headline", "sub"], user: ["type", "step", "headline", "points"], codebase: ["type", "step", "headline", "paths", "points"] };
  const needs = { title: ["headline"], user: ["step", "headline", "points"], codebase: ["step", "headline", "paths"] };
  let step = 0;
  const count = { user: 0, codebase: 0 };
  moments.forEach((m, i) => {
    const at = `moment ${i + 1}`;
    if (!m || typeof m !== "object" || Array.isArray(m)) return why.push(`${at}: a moment is an object`);
    const extra = Object.keys(m).filter((k) => !["say", "frame"].includes(k));
    if (extra.length) why.push(`${at}: only "say" and "frame"; not ${extra.join(", ")} (no own images or pages)`);
    if (typeof m.say !== "string" || !m.say.trim() || /[\r\n]/.test(m.say)) why.push(`${at}: needs one spoken line in "say"`);
    const f = m.frame;
    if (!f || typeof f !== "object" || !keys[f.type]) return why.push(`${at}: a frame is title, user or codebase`);
    const bad = Object.keys(f).filter((k) => !keys[f.type].includes(k));
    if (bad.length) why.push(`${at}: a ${f.type} frame has no ${bad.join(", ")}`);
    for (const k of needs[f.type]) if (f[k] === undefined) why.push(`${at}: a ${f.type} frame needs ${k}`);
    const texts = [m.say, f.kicker, f.headline, f.sub, ...(Array.isArray(f.points) ? f.points : []), ...(Array.isArray(f.paths) ? f.paths : [])];
    for (const k of ["points", "paths"]) {
      if (f[k] !== undefined && (!Array.isArray(f[k]) || f[k].length < 1 || f[k].length > 4 || !f[k].every((s) => typeof s === "string" && s.trim()))) {
        why.push(`${at}: ${k} is a list of 1 to 4 lines`);
      }
    }
    for (const k of ["kicker", "headline", "sub"]) if (f[k] !== undefined && (typeof f[k] !== "string" || !f[k].trim())) why.push(`${at}: ${k} is text`);
    if (texts.some((t) => typeof t === "string" && BANNED.test(t))) why.push(`${at}: no bench and no graph in the video; the graph stays on the spec`);
    if ([f.kicker, f.headline, f.sub, ...(f.points ?? []), ...(f.paths ?? [])].some((t) => typeof t === "string" && t.length > TEXT_MAX)) {
      why.push(`${at}: frame text is at most ${TEXT_MAX} characters`);
    }
    if (f.type === "title") {
      if (i !== 0) why.push(`${at}: the title is the first moment, once`);
      return;
    }
    if (i === 0) why.push("moment 1: the video opens on its title");
    count[f.type]++;
    if (!Number.isInteger(f.step) || f.step < 1) return why.push(`${at}: step is the build step, from 1`);
    if (f.step < step) why.push(`${at}: step ${f.step} after step ${step}; tell the changes in build order`);
    else if (f.step > step + 1) why.push(`${at}: step ${f.step} skips step ${step + 1}`);
    step = Math.max(step, f.step);
  });
  if (!why.length) {
    if (!count.user) why.push("show at least one change for a user");
    if (!count.codebase) why.push("show at least one change in the codebase");
    const total = moments.reduce((s, m) => s + seconds(m.say), 0);
    if (target && total > target * 1.1) why.push(`about ${Math.round(total)} s, over the ${target} s target; cut moments or lines`);
  }
  return why;
};

const file = path.resolve(positional[0]);
let moments;
try {
  moments = JSON.parse(fs.readFileSync(file, "utf8"));
} catch (e) {
  fail(`cannot read the storyboard: ${e.message}`, 2);
}
const refusals = check(moments);
if (refusals.length) fail(refusals);
const changes = moments.filter((m) => m.frame.type !== "title");
const summary = `storyboard ok: ${moments.length} moments; steps 1-${Math.max(...changes.map((m) => m.frame.step))}; `
  + `user ${changes.filter((m) => m.frame.type === "user").length}, codebase ${changes.filter((m) => m.frame.type === "codebase").length}`;
if (verb === "check") {
  console.log(summary);
  console.log(`about ${Math.round(moments.reduce((s, m) => s + seconds(m.say), 0))} s`);
  process.exit(0);
}

// ---- build ----
const out = path.resolve(flags.out ?? path.join(path.dirname(file), "spec.mp4"));
if (fs.existsSync(out)) fail(`${out} exists; give a new output path`);
if (!out.endsWith(".mp4")) fail("the output is an .mp4");
const which = (bin) => (process.env.PATH ?? "").split(path.delimiter).filter(Boolean).map((d) => path.join(d, bin))
  .find((f) => { try { fs.accessSync(f, fs.constants.X_OK); return fs.statSync(f).isFile(); } catch { return false; } }) ?? "";
const onPath = (bin) => Boolean(which(bin));
for (const bin of ["ffmpeg", "ffprobe"]) if (!onPath(bin)) fail(`${bin} is needed to stitch and verify the video`);
const browserPath = process.env.OPENWIZ_CHROMIUM || which("chromium");
if (!browserPath) fail("no Chromium: set OPENWIZ_CHROMIUM or put chromium on PATH");
const engine = flags["tts-command"] ? null : ["espeak-ng", "espeak", "say"].find(onPath);
if (!flags["tts-command"] && !engine) fail("no voice: pass --tts-command, or install espeak-ng");

const loadPlaywright = () => {
  for (const base of [process.cwd(), HOME]) {
    try {
      return createRequire(path.join(base, "noop.js"))("playwright-core");
    } catch {}
  }
  fs.mkdirSync(HOME, { recursive: true });
  const r = spawnSync("npm", ["install", "--no-save", "--ignore-scripts", "--package-lock=false", "--prefix", HOME, PLAYWRIGHT], { stdio: "ignore" });
  if (r.status !== 0) fail(`cannot install ${PLAYWRIGHT} into ${HOME}`);
  return createRequire(path.join(HOME, "noop.js"))("playwright-core");
};

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const CSS = `*{box-sizing:border-box;margin:0}body{width:${WIDTH}px;height:${HEIGHT}px;background:#0f1115;color:#f2f2f0;
font:32px/1.35 system-ui,-apple-system,"DejaVu Sans",sans-serif;padding:84px 96px;display:flex;flex-direction:column;justify-content:center}
.kicker{font-size:24px;letter-spacing:.08em;text-transform:uppercase;color:#9aa3ad;margin-bottom:22px}
.kicker b{color:#ffd166;font-weight:600}h1{font-size:64px;line-height:1.1;margin-bottom:34px}
.sub{font-size:30px;color:#c8cdd2}ul{list-style:none;padding:0}li{margin:12px 0;padding-left:34px;position:relative}
li:before{content:"";position:absolute;left:0;top:.5em;width:14px;height:14px;border-radius:3px;background:#ffd166}
.code li{font:28px/1.4 ui-monospace,"DejaVu Sans Mono",monospace;color:#9ee6b0}.code li:before{background:#4fb477}
.user h1{color:#fff}.codebase .kicker b{color:#4fb477}`;
const page = (f) => {
  const list = (items, cls = "") => (items?.length ? `<ul class="${cls}">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>` : "");
  const kicker = f.type === "title" ? esc(f.kicker ?? "Spec")
    : `<b>Step ${f.step}</b> · ${f.type === "user" ? "What changes for you" : "What changes in the code"}`;
  const body = f.type === "title" ? (f.sub ? `<p class="sub">${esc(f.sub)}</p>` : "")
    : f.type === "user" ? list(f.points) : list(f.paths, "code") + list(f.points);
  return `<!doctype html><meta charset="utf-8"><style>${CSS}</style><body class="${f.type}"><div class="kicker">${kicker}</div><h1>${esc(f.headline)}</h1>${body}</body>`;
};

const run = (cmd, args, opts = {}) => {
  const r = spawnSync(cmd, args, { encoding: "utf8", ...opts });
  if (r.status !== 0) throw new Error(`${cmd} failed: ${(r.stderr || "").trim().split("\n").pop()}`);
  return r.stdout;
};
const duration = (f) => Number(run("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).trim());
const toWav = (src, wav) => run("ffmpeg", ["-nostdin", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", "48000", wav]);

const loudest = (f) => {
  const r = spawnSync("ffmpeg", ["-nostdin", "-i", f, "-af", "volumedetect", "-vn", "-f", "null", "-"], { encoding: "utf8" });
  return Number(((r.stderr ?? "").match(/max_volume: (-?[\d.]+) dB/) ?? [])[1]);
};

const voice = (text, wav) => {
  const base = wav.replace(/\.wav$/, ".src");
  const dir = path.dirname(base);
  const ours = () => fs.readdirSync(dir).filter((f) => f.startsWith(path.basename(base) + ".")).map((f) => path.join(dir, f));
  for (const f of [wav, ...ours()]) fs.rmSync(f, { force: true }); // only a take made now counts
  if (flags["tts-command"]) {
    const q = (s) => `'${s.replace(/'/g, `'\\''`)}'`;
    const cmd = flags["tts-command"].replaceAll("{out}", q(base)).replaceAll("{text}", q(text));
    const r = spawnSync("sh", ["-c", cmd], { input: text, stdio: ["pipe", "ignore", "pipe"], encoding: "utf8" });
    if (r.status !== 0) {
      for (const f of ours()) fs.rmSync(f, { force: true });
      const last = (r.stderr || "").trim().split("\n").pop();
      throw new Error(`the voice command failed (${r.error ? r.error.message : r.signal ?? `exit ${r.status}`})${last ? `: ${last}` : ""}`);
    }
  } else if (engine === "say") {
    run("say", [...(flags.voice ? ["-v", flags.voice] : []), "-o", `${base}.aiff`, text]);
  } else {
    run(engine, [...(flags.voice ? ["-v", flags.voice] : []), "-w", `${base}.wav`, text]);
  }
  const made = ours();
  const src = made.find((f) => fs.statSync(f).size > 0);
  try {
    if (!src) throw new Error(`the voice wrote nothing for "${text.slice(0, 60)}"`);
    toWav(src, wav);
  } finally {
    for (const f of made) fs.rmSync(f, { force: true });
  }
  const d = duration(wav);
  if (!(d > 0.2)) throw new Error(`the voice came back empty for "${text.slice(0, 60)}"`);
  if (!(loudest(wav) > -50)) throw new Error(`the voice is silent for "${text.slice(0, 60)}"`);
  return d;
};

const build = path.join(path.dirname(file), "build");
fs.mkdirSync(build, { recursive: true });
const pad = (i) => String(i + 1).padStart(2, "0");
const warnings = [];
try {
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch({ executablePath: browserPath });
  try {
    const tab = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT } });
    for (const [i, m] of moments.entries()) {
      await tab.setContent(page(m.frame));
      const overflow = await tab.evaluate(() => document.body.scrollHeight > innerHeight || document.body.scrollWidth > innerWidth);
      if (overflow) warnings.push(`moment ${i + 1}: the frame overflows; shorten or split it`);
      await tab.screenshot({ path: path.join(build, `frame-${pad(i)}.png`) });
    }
  } finally {
    await browser.close();
  }
  const voiced = [];
  const lengths = moments.map((m, i) => {
    try {
      return voice(m.say, path.join(build, `line-${pad(i)}.wav`)) + HOLD;
    } catch (e) {
      voiced.push(`moment ${i + 1}: ${e.message}`);
      return 0;
    }
  });
  if (voiced.length) fail(voiced);

  const args = ["-nostdin", "-v", "error"];
  const filters = [];
  moments.forEach((_, i) => {
    args.push("-loop", "1", "-framerate", "30", "-i", path.join(build, `frame-${pad(i)}.png`), "-i", path.join(build, `line-${pad(i)}.wav`));
    filters.push(`[${2 * i}:v]trim=duration=${lengths[i].toFixed(3)},fps=30,format=yuv420p,setsar=1[v${i}]`,
      `[${2 * i + 1}:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur=${lengths[i].toFixed(3)},atrim=duration=${lengths[i].toFixed(3)}[a${i}]`);
  });
  filters.push(`${moments.map((_, i) => `[v${i}][a${i}]`).join("")}concat=n=${moments.length}:v=1:a=1[v][a]`);
  const total = lengths.reduce((a, b) => a + b, 0);
  run("ffmpeg", ["-nostdin", "-v", "error", "-y", "-framerate", "1", "-i", path.join(build, "frame-%02d.png"),
    "-vf", `scale=426:-1,tile=3x${Math.ceil(moments.length / 3)}`,
    "-frames:v", "1", path.join(build, "sheet.png")]);

  // Staged in a new folder of its own beside the output, on the output's
  // filesystem, so publishing is one link and cleanup removes only ours.
  const stage = fs.mkdtempSync(path.join(path.dirname(out), `.${path.basename(out, ".mp4")}.partial-`));
  const partial = path.join(stage, "spec.mp4");
  try {
    run("ffmpeg", [...args, "-filter_complex", filters.join(";"), "-map", "[v]", "-map", "[a]", "-r", "30",
      "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", partial]);
    const meta = JSON.parse(run("ffprobe", ["-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", partial]));
    const kinds = meta.streams.map((s) => s.codec_type).sort().join(",");
    if (kinds !== "audio,video") throw new Error(`the MP4 holds ${kinds}, not one video and one audio track`);
    if (Math.abs(Number(meta.format.duration) - total) > 0.25) throw new Error(`the MP4 runs ${meta.format.duration} s, not ${total.toFixed(2)} s`);
    if (!(loudest(partial) > -50)) throw new Error("the voice is not audible");
    fs.linkSync(partial, out); // never over a file that appeared meanwhile
  } finally {
    fs.rmSync(stage, { recursive: true, force: true });
  }
  let at = 0;
  const timeline = moments.map((m, i) => {
    const line = `  ${pad(i)}  ${at.toFixed(1).padStart(5)} s  ${m.frame.type === "title" ? "title   " : `${m.frame.type.padEnd(8)}`}${m.frame.step ? ` step ${m.frame.step}` : "       "}  ${m.say.slice(0, 60)}`;
    at += lengths[i];
    return line;
  });
  console.log(summary);
  console.log(timeline.join("\n"));
  console.log(`${path.basename(out)}: ${total.toFixed(1)} s, ${moments.length} moments, voice ${flags["tts-command"] ? "your command" : engine}; sheet build/sheet.png`);
  console.log(warnings.length ? warnings.map((w) => `WARN ${w}`).join("\n") : "no warnings");
} catch (e) {
  fail(e.message);
}
