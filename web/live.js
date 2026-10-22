// ASCII Mirror: the webcam drawn live in glyphs.
//
// camera frame -> hidden sample canvas (grid x oversampling, optionally
// mirrored) -> LiveMapper (camera.js) -> AtlasRenderer, with the same lens and
// ripple physics as the film player. Nothing leaves the page.

import { LiveMapper, liveRows } from "./camera.js";
import { FIELD_DEFAULTS, GlyphField } from "./field.js";
import { wirePointer } from "./pointer.js";
import { AtlasRenderer } from "./renderer.js";

const FONT_FAMILY = "ASCIIFilmFont";
const HIDE_CONTROLS_MS = 2500;
const THEMES = [
  null, // the page's own theme from live.json
  { name: "Amber", foreground: "#ffb547", background: "#120b02" },
  { name: "Phosphor", foreground: "#5dff8a", background: "#020b05" },
  { name: "Ice", foreground: "#cfe6ff", background: "#050d18" },
];

const $ = (id) => document.getElementById(id);
const ui = {
  stage: $("stage"), canvas: $("film"), status: $("status"), panel: $("start-panel"),
  start: $("start"), video: $("camera"), controls: $("controls"), freeze: $("freeze"),
  mirror: $("mirror"), fewer: $("fewer"), more: $("more"), density: $("density"),
  rate: $("rate"), theme: $("theme"), fullscreen: $("fullscreen"), title: $("live-title"),
};

const store = {
  get(key) { try { return localStorage.getItem(`ascii-live:${key}`); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(`ascii-live:${key}`, value); } catch { /* private mode */ } },
};

const HEX = /^#[0-9a-f]{6}$/i;

export function validateLive(m) {
  const fail = (msg) => { throw new Error(`live.json: ${msg}`); };
  if (!m || m.schemaVersion !== 1 || m.kind !== "live") fail("not a live page manifest");
  if (!Array.isArray(m.glyphs) || !Array.isArray(m.coverage) || m.glyphs.length !== m.coverage.length || m.glyphs.length < 2) fail("glyph table and coverage must match");
  if (m.glyphs[0] !== " " || m.coverage[0] !== 0) fail("glyph 0 must be space with zero coverage");
  for (let k = 1; k < m.coverage.length; k++) if (!(m.coverage[k] >= m.coverage[k - 1])) fail("coverage must ascend");
  if (!Number.isInteger(m.columns) || m.columns < 20 || m.columns > 400) fail("columns out of range");
  const f = m.font || {};
  for (const k of ["size", "cellWidth", "cellHeight", "ascent", "lineHeight"]) if (!(f[k] > 0)) fail(`font.${k} must be positive`);
  if (typeof f.file !== "string" || /^[a-z]+:|^\/|\.\./i.test(f.file)) fail("font.file must be a relative path");
  if (!m.theme || !HEX.test(m.theme.foreground) || !HEX.test(m.theme.background)) fail("theme colours must be #rrggbb");
  const steps = (Array.isArray(m.columnSteps) ? m.columnSteps : [m.columns]).filter((c) => Number.isInteger(c) && c >= 20 && c <= 400);
  return { ...m, columnSteps: steps.length ? steps : [m.columns], interaction: { ...FIELD_DEFAULTS, ...(m.interaction || {}) } };
}

function setStatus(text, error = false) {
  ui.status.textContent = text;
  ui.status.classList.toggle("error", error);
}

function cameraError(err) {
  const name = err && err.name;
  if (name === "NotAllowedError" || name === "SecurityError") return "Camera access was blocked. Allow the camera for this site (address bar → site settings) and reload.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No camera was found on this device.";
  if (name === "NotReadableError" || name === "AbortError") return "The camera is busy — close other apps or tabs using it and try again.";
  return `Could not start the camera (${(err && err.message) || err}).`;
}

class LivePage {
  constructor(manifest) {
    this.m = manifest;
    this.mirrored = store.get("mirror") !== "0";
    this.frozen = false;
    this.columns = Number(store.get("columns")) || manifest.columns;
    if (!manifest.columnSteps.includes(this.columns)) this.columns = manifest.columns;
    this.themeIndex = Math.min(Number(store.get("theme")) || 0, THEMES.length - 1);
    this.sample = document.createElement("canvas");
    this.sctx = this.sample.getContext("2d", { willReadFrequently: true, alpha: false });
    this.buffers = null;
    this.flip = 0;
    this.renderer = null;
    this.field = null;
    this.fieldRaf = 0;
    this.frames = 0;
    this.rateFrames = 0;
    this.rateStart = performance.now();
    this.stats = { frames: 0, mapMs: 0, drawMs: 0 };
  }

  get theme() { return THEMES[this.themeIndex] || this.m.theme; }

  /** (Re)build mapper, renderer and field for the current column count. */
  build() {
    const v = ui.video;
    const f = this.m.font;
    const columns = this.columns;
    const rows = liveRows(columns, v.videoWidth || 1280, v.videoHeight || 720, f.cellWidth, f.cellHeight);
    this.mapper = new LiveMapper({ ...this.m.mapping, columns, rows, coverage: this.m.coverage });
    this.sample.width = this.mapper.sampleWidth;
    this.sample.height = this.mapper.sampleHeight;
    this.buffers = [new Uint8Array(columns * rows), new Uint8Array(columns * rows)];
    this.renderer = new AtlasRenderer(ui.canvas, { columns, rows, font: f }, this.m.glyphs, FONT_FAMILY);
    const ix = this.m.interaction;
    const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.field = (ix.lens || ix.ripples) && !reduceMotion ? new GlyphField(columns, rows, ix) : null;
    this.renderer.attachField(this.field);
    this.applyTheme(this.themeIndex);
    this.resize();
    ui.density.textContent = `${columns} cols`;
    ui.canvas.classList.toggle("lens-on", Boolean(this.field && ix.lens));
  }

  resize() {
    const r = ui.stage.getBoundingClientRect();
    this.renderer.resize(r.width, r.height, window.devicePixelRatio || 1);
    if (this.lastGrid) this.renderer.draw(this.lastGrid);
  }

  applyTheme(index) {
    this.themeIndex = (index + THEMES.length) % THEMES.length;
    store.set("theme", String(this.themeIndex));
    const t = this.theme;
    document.documentElement.style.setProperty("--film-bg", t.background);
    document.documentElement.style.setProperty("--film-fg", t.foreground);
    if (this.renderer) {
      this.renderer.setTheme(t.foreground, t.background);
      if (this.lastGrid) this.renderer.draw(this.lastGrid);
    }
    ui.theme.setAttribute("aria-label", `Colour theme: ${THEMES[this.themeIndex] ? THEMES[this.themeIndex].name : "Original"}`);
  }

  setColumns(direction) {
    const steps = this.m.columnSteps;
    const i = steps.indexOf(this.columns);
    const next = steps[Math.min(Math.max(i + direction, 0), steps.length - 1)];
    if (next === this.columns) return;
    this.columns = next;
    store.set("columns", String(next));
    this.lastGrid = null;
    this.build();
  }

  setMirror(on) {
    this.mirrored = on;
    store.set("mirror", on ? "1" : "0");
    ui.mirror.setAttribute("aria-pressed", String(on));
  }

  setFrozen(on) {
    this.frozen = on;
    ui.freeze.setAttribute("aria-pressed", String(on));
    ui.freeze.setAttribute("aria-label", on ? "Unfreeze" : "Freeze");
    document.body.classList.toggle("paused", on);
    document.body.classList.toggle("playing", !on);
  }

  wakeField() {
    if (!this.field || this.fieldRaf) return;
    this.fieldRaf = requestAnimationFrame((now) => {
      this.fieldRaf = 0;
      if (this.renderer.animate(now)) this.wakeField();
    });
  }

  /** Map and draw the camera's current frame. */
  process() {
    if (this.frozen || !this.mapper) return;
    const v = ui.video;
    const { sample, sctx, mapper } = this;
    const t0 = performance.now();
    sctx.setTransform(this.mirrored ? -1 : 1, 0, 0, 1, this.mirrored ? sample.width : 0, 0);
    sctx.drawImage(v, 0, 0, sample.width, sample.height);
    const pixels = sctx.getImageData(0, 0, sample.width, sample.height).data;
    const out = this.buffers[this.flip];
    this.flip ^= 1;
    mapper.map(pixels, out);
    const t1 = performance.now();
    this.renderer.draw(out);
    this.lastGrid = out;
    const t2 = performance.now();
    this.stats.frames++;
    this.stats.mapMs += t1 - t0;
    this.stats.drawMs += t2 - t1;
    this.rateFrames++;
    if (t2 - this.rateStart > 1000) {
      ui.rate.textContent = `${Math.round((this.rateFrames * 1000) / (t2 - this.rateStart))} fps`;
      this.rateFrames = 0;
      this.rateStart = t2;
    }
  }

  run() {
    const v = ui.video;
    if (typeof v.requestVideoFrameCallback === "function") {
      const onFrame = () => { this.process(); v.requestVideoFrameCallback(onFrame); };
      v.requestVideoFrameCallback(onFrame);
    } else {
      let lastTime = -1;
      const tick = () => {
        if (v.currentTime !== lastTime) { lastTime = v.currentTime; this.process(); }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }
  }
}

// ------------------------------------------------------------------ controls

function fullscreenSupported() {
  return Boolean(document.fullscreenEnabled || document.webkitFullscreenEnabled);
}

function toggleFullscreen() {
  if (!fullscreenSupported()) return;
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    (document.exitFullscreen || document.webkitExitFullscreen).call(document);
  } else {
    const el = document.documentElement;
    (el.requestFullscreen || el.webkitRequestFullscreen).call(el);
  }
}

function wireControls(page) {
  let hideTimer = 0;
  const showControls = () => {
    document.body.classList.add("show-controls");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (!page.frozen && !ui.controls.matches(":hover, :focus-within")) document.body.classList.remove("show-controls");
    }, HIDE_CONTROLS_MS);
  };
  ui.stage.addEventListener("pointermove", showControls);
  ui.stage.addEventListener("pointerdown", showControls);
  ui.controls.addEventListener("focusin", showControls);
  wirePointer(ui.stage, ui.canvas, () => page.field, () => page.wakeField());
  ui.freeze.addEventListener("click", () => page.setFrozen(!page.frozen));
  ui.mirror.addEventListener("click", () => page.setMirror(!page.mirrored));
  ui.fewer.addEventListener("click", () => page.setColumns(-1));
  ui.more.addEventListener("click", () => page.setColumns(1));
  ui.theme.addEventListener("click", () => page.applyTheme(page.themeIndex + 1));
  if (!fullscreenSupported()) ui.fullscreen.hidden = true;
  ui.fullscreen.addEventListener("click", toggleFullscreen);
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target instanceof HTMLButtonElement && e.key === " ") return;
    switch (e.key) {
      case " ": case "k": case "K": e.preventDefault(); page.setFrozen(!page.frozen); break;
      case "m": case "M": page.setMirror(!page.mirrored); break;
      case "[": case "-": page.setColumns(-1); break;
      case "]": case "=": case "+": page.setColumns(1); break;
      case "t": case "T": page.applyTheme(page.themeIndex + 1); break;
      case "f": case "F": toggleFullscreen(); break;
      case "i": case "I":
        if (page.field) {
          page.field.setEnabled(!page.field.enabled);
          ui.canvas.classList.toggle("lens-on", page.field.enabled && page.m.interaction.lens);
          page.wakeField();
        }
        break;
      default: return;
    }
    showControls();
  });
  new ResizeObserver(() => page.resize()).observe(ui.stage);
  const watchDpr = () => {
    matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`)
      .addEventListener("change", () => { page.resize(); watchDpr(); }, { once: true });
  };
  watchDpr();
  showControls();
}

// ------------------------------------------------------------------ boot

async function startCamera(page) {
  ui.start.disabled = true;
  setStatus("Waiting for camera permission…");
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
  } catch (err) {
    ui.start.disabled = false;
    setStatus(cameraError(err), true);
    return;
  }
  const v = ui.video;
  v.srcObject = stream;
  await v.play().catch(() => {});
  if (!v.videoWidth) await new Promise((r) => v.addEventListener("loadedmetadata", r, { once: true }));
  addEventListener("pagehide", () => stream.getTracks().forEach((t) => t.stop()));
  ui.panel.hidden = true;
  setStatus("");
  page.build();
  page.setMirror(page.mirrored);
  page.setFrozen(false);
  wireControls(page);
  page.run();
  document.body.classList.add("ready");
}

async function main() {
  const res = await fetch("live.json", { cache: "no-cache" }).catch(() => null);
  if (!res || !res.ok) throw new Error(`could not load live.json${res ? ` (HTTP ${res.status})` : ""}`);
  const manifest = validateLive(await res.json());
  document.title = manifest.title || "ASCII Mirror";
  ui.title.textContent = manifest.title || "ASCII Mirror";
  if (manifest.description) ui.canvas.setAttribute("aria-label", manifest.description);
  if (!window.isSecureContext) throw new Error("The camera only works on https:// pages (or localhost).");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error("This browser cannot use a camera here.");
  const face = new FontFace(FONT_FAMILY, `url("${encodeURI(manifest.font.file)}")`);
  document.fonts.add(await face.load().catch(() => { throw new Error("could not load the font"); }));
  const page = new LivePage(manifest);
  page.applyTheme(page.themeIndex);
  window.asciiLive = page; // for debugging and end-to-end tests
  setStatus("");
  ui.panel.hidden = false;
  ui.start.addEventListener("click", () => startCamera(page));
  if (new URLSearchParams(location.search).has("autostart")) startCamera(page);
}

main().catch((err) => {
  setStatus(err.message || String(err), true);
  ui.panel.hidden = true;
});
