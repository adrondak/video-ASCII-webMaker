// ASCII Film player: loads manifest.json, the webfont and film.ascf (all
// relative to this page, so it works at a domain root or in a subfolder) and
// plays the glyph animation on a Canvas.
//
// Timing: when the film has audio, the <audio> element is the master clock;
// otherwise a performance.now() clock is. requestAnimationFrame only schedules
// drawing — the frame shown is always floor(time * fps), so a late frame is
// skipped rather than slowing the film down.

import { AscfDecoder, supportsDecompression } from "./decoder.js";
import { FIELD_DEFAULTS, GlyphField } from "./field.js";
import { AtlasRenderer } from "./renderer.js";

const FONT_FAMILY = "ASCIIFilmFont";
const HIDE_CONTROLS_MS = 2500;
const SEEK_STEP = 5;
// Light-on-dark only: swapping polarity would turn the picture into a negative.
const THEMES = [
  null, // the film's own theme from manifest.json
  { name: "Amber", foreground: "#ffb547", background: "#120b02" },
  { name: "Phosphor", foreground: "#5dff8a", background: "#020b05" },
  { name: "Ice", foreground: "#cfe6ff", background: "#050d18" },
];

const $ = (id) => document.getElementById(id);
const ui = {
  stage: $("stage"), canvas: $("film"), status: $("status"), big: $("big-play"),
  controls: $("controls"), play: $("play"), time: $("time"), seek: $("seek"),
  mute: $("mute"), volume: $("volume"), loop: $("loop"), theme: $("theme"),
  fullscreen: $("fullscreen"), desc: $("film-description"),
};

const store = {
  get(key) { try { return localStorage.getItem(`ascii-film:${key}`); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(`ascii-film:${key}`, value); } catch { /* private mode */ } },
};

// ------------------------------------------------------------------ manifest

const HEX = /^#[0-9a-f]{6}$/i;
const isRelative = (p) => typeof p === "string" && p.length > 0 && !/^[a-z][a-z0-9+.-]*:|^\/|\\|(^|\/)\.\.(\/|$)/i.test(p);
const posInt = (v) => Number.isInteger(v) && v > 0;
const posNum = (v) => typeof v === "number" && Number.isFinite(v) && v > 0;

export function validateManifest(m) {
  const fail = (msg) => { throw new Error(`manifest.json: ${msg}`); };
  if (!m || typeof m !== "object") fail("not an object");
  if (m.schemaVersion !== 1) fail(`unsupported schemaVersion ${m.schemaVersion}`);
  if (!isRelative(m.animation)) fail("animation must be a relative path");
  if (m.audio !== null && m.audio !== undefined && !isRelative(m.audio)) fail("audio must be null or a relative path");
  if (!posInt(m.columns) || !posInt(m.rows) || !posInt(m.frameCount)) fail("columns/rows/frameCount must be positive integers");
  if (!m.fps || !posInt(m.fps.numerator) || !posInt(m.fps.denominator)) fail("fps must be a positive rational");
  if (!posNum(m.durationSeconds)) fail("durationSeconds must be positive");
  const f = m.font || {};
  if (!isRelative(f.file)) fail("font.file must be a relative path");
  for (const k of ["size", "cellWidth", "cellHeight", "ascent", "lineHeight"]) if (!posNum(f[k])) fail(`font.${k} must be a positive number`);
  if (typeof f.descent !== "number" || f.descent < 0) fail("font.descent must be >= 0");
  if (!m.theme || !HEX.test(m.theme.foreground) || !HEX.test(m.theme.background)) fail("theme colours must be #rrggbb");
  const ix = m.interaction && typeof m.interaction === "object" ? m.interaction : {};
  const num = (v, lo, hi, d) => (typeof v === "number" && v >= lo && v <= hi ? v : d);
  const interaction = {
    lens: ix.lens !== undefined ? ix.lens === true : FIELD_DEFAULTS.lens,
    ripples: ix.ripples !== undefined ? ix.ripples === true : FIELD_DEFAULTS.ripples,
    lensRadius: num(ix.lensRadius, 1, 40, FIELD_DEFAULTS.lensRadius),
    lensStrength: num(ix.lensStrength, 0, 2.2, FIELD_DEFAULTS.lensStrength),
    rippleStrength: num(ix.rippleStrength, 0, 4, FIELD_DEFAULTS.rippleStrength),
  };
  return {
    ...m,
    title: typeof m.title === "string" ? m.title.slice(0, 200) : "ASCII Film",
    description: typeof m.description === "string" ? m.description.slice(0, 2000) : "",
    audio: m.audio || null,
    loop: m.loop !== false,
    autoplay: m.autoplay === "muted" ? "muted" : "off",
    interaction,
  };
}

async function fetchChecked(url, what) {
  let res;
  try {
    res = await fetch(url, { cache: "no-cache" });
  } catch {
    throw new Error(`could not download ${what} (${url}); check your connection`);
  }
  if (!res.ok) throw new Error(`could not download ${what} (${url}): HTTP ${res.status}`);
  return res;
}

async function fetchWithProgress(url, what, onProgress) {
  const res = await fetchChecked(url, what);
  const total = Number(res.headers.get("content-length")) || 0;
  if (!res.body || !total) return res.arrayBuffer();
  const reader = res.body.getReader();
  const chunks = [];
  let got = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    got += value.length;
    onProgress(Math.min(1, got / total));
  }
  const out = new Uint8Array(got);
  let p = 0;
  for (const c of chunks) { out.set(c, p); p += c.length; }
  return out.buffer;
}

// ------------------------------------------------------------------ clocks

class WallClock {
  constructor() { this.base = 0; this.startedAt = 0; this.playing = false; }
  now() { return this.playing ? this.base + (performance.now() - this.startedAt) / 1000 : this.base; }
  async play() { if (!this.playing) { this.startedAt = performance.now(); this.playing = true; } }
  pause() { this.base = this.now(); this.playing = false; }
  seek(t) { this.base = t; this.startedAt = performance.now(); }
  setLoop() {}
}

class AudioClock {
  constructor(audio) { this.audio = audio; }
  get playing() { return !this.audio.paused && !this.audio.ended; }
  now() { return this.audio.currentTime; }
  play() { return this.audio.play(); }
  pause() { this.audio.pause(); }
  seek(t) { this.audio.currentTime = t; }
  setLoop(on) { this.audio.loop = on; }
}

// ------------------------------------------------------------------ player

class Player {
  constructor(manifest, decoder, renderer, audio) {
    this.m = manifest;
    this.decoder = decoder;
    this.renderer = renderer;
    this.audio = audio;
    this.clock = audio ? new AudioClock(audio) : new WallClock();
    this.duration = decoder.durationSeconds;
    this.loop = manifest.loop; // the film decides; a visitor's toggle lasts one visit
    this.clock.setLoop(this.loop);
    this.shown = -1;
    this.pending = -1;
    this.inflight = false;
    this.raf = 0;
    this.ended = false;
    this.themeIndex = Math.min(Number(store.get("theme")) || 0, THEMES.length - 1);
    this.stats = { drawn: 0, framesShown: 0, skipped: 0 };
    this.field = renderer.field;
    this.fieldRaf = 0;
  }

  /** Keep the lens/ripple simulation running while anything moves. */
  wakeField() {
    if (!this.field || this.fieldRaf) return;
    this.fieldRaf = requestAnimationFrame((now) => {
      this.fieldRaf = 0;
      if (this.renderer.animate(now)) this.wakeField();
    });
  }

  setInteraction(on) {
    if (!this.field) return;
    this.field.setEnabled(on);
    ui.canvas.classList.toggle("lens-on", on && this.m.interaction.lens);
    this.wakeField();
  }

  get playing() { return this.clock.playing; }

  time() {
    let t = this.clock.now();
    if (!this.audio && t >= this.duration) {
      if (this.loop) { t %= this.duration; this.clock.seek(t); }
      else { this.clock.pause(); this.clock.seek(this.duration); this._ended(); t = this.duration; }
    }
    return Math.min(Math.max(t, 0), this.duration);
  }

  async play() {
    if (this.ended) { this.ended = false; this.clock.seek(0); this.renderer.invalidate(); }
    try {
      await this.clock.play();
    } catch (err) {
      // Autoplay with sound refused: wait for a user gesture.
      this._sync();
      return false;
    }
    this._sync();
    this._schedule();
    return true;
  }

  pause() {
    this.clock.pause();
    this._sync();
  }

  toggle() { return this.playing ? this.pause() : this.play(); }

  seek(t) {
    t = Math.min(Math.max(t, 0), Math.max(this.duration - 1e-6, 0));
    this.ended = false;
    this.clock.seek(t);
    this.renderer.invalidate();
    this.shown = -1;
    this._schedule();
    this._sync();
  }

  setLoop(on) {
    this.loop = on;
    this.clock.setLoop(on);
    this._sync();
  }

  applyTheme(index) {
    this.themeIndex = (index + THEMES.length) % THEMES.length;
    store.set("theme", String(this.themeIndex));
    const t = THEMES[this.themeIndex] || this.m.theme;
    document.documentElement.style.setProperty("--film-bg", t.background);
    document.documentElement.style.setProperty("--film-fg", t.foreground);
    this.renderer.setTheme(t.foreground, t.background);
    this.shown = -1;
    ui.theme.setAttribute("aria-label", `Colour theme: ${THEMES[this.themeIndex] ? THEMES[this.themeIndex].name : "Original"}`);
    this._schedule();
  }

  resize() {
    const r = ui.stage.getBoundingClientRect();
    this.renderer.resize(r.width, r.height, window.devicePixelRatio || 1);
    this.shown = -1;
    if (this.field) this.field.clearPointer();
    this._schedule();
  }

  _ended() {
    if (this.ended) return;
    this.ended = true;
    this._sync();
  }

  _schedule() {
    if (!this.raf) this.raf = requestAnimationFrame(() => this._tick());
  }

  _tick() {
    this.raf = 0;
    const t = this.time();
    const target = this.decoder.frameAt(t);
    if (target !== this.shown && !this.inflight) {
      if (this.pending !== -1 && target > this.pending + 1) this.stats.skipped += target - this.pending - 1;
      this.inflight = true;
      this.pending = target;
      this.decoder.frame(target).then((grid) => {
        this.stats.drawn += this.renderer.draw(grid);
        this.stats.framesShown++;
        this.shown = target;
      }).catch((err) => this.fail(err)).finally(() => { this.inflight = false; });
    }
    this._updateTime(t);
    if (this.playing || this.inflight || this.shown !== target) this._schedule();
  }

  _updateTime(t) {
    if (!ui.seek.matches(":active")) ui.seek.value = String(Math.round(t * 1000));
    ui.time.textContent = `${fmt(t)} / ${fmt(this.duration)}`;
  }

  _sync() {
    const playing = this.playing;
    document.body.classList.toggle("playing", playing);
    document.body.classList.toggle("paused", !playing);
    ui.play.setAttribute("aria-label", playing ? "Pause" : "Play");
    ui.play.dataset.state = playing ? "playing" : "paused";
    ui.big.hidden = playing;
    ui.loop.setAttribute("aria-pressed", String(this.loop));
    if (this.audio) {
      const muted = this.audio.muted || this.audio.volume === 0;
      ui.mute.setAttribute("aria-label", muted ? "Unmute" : "Mute");
      ui.mute.dataset.state = muted ? "muted" : "on";
    }
    this._updateTime(this.time());
  }

  fail(err) {
    console.error(err);
    try { this.clock.pause(); } catch { /* ignore */ }
    showError(err.message || String(err));
  }
}

const fmt = (s) => {
  s = Math.max(0, Math.floor(s + 1e-6));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

function showError(message) {
  ui.status.textContent = message;
  ui.status.classList.add("error");
  ui.big.hidden = true;
  document.body.classList.add("failed");
}

function setStatus(text) {
  ui.status.textContent = text;
}

// ------------------------------------------------------------------ controls

function wireControls(player) {
  const stage = ui.stage;
  let hideTimer = 0;
  const showControls = () => {
    document.body.classList.add("show-controls");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (player.playing && !ui.controls.matches(":hover, :focus-within")) document.body.classList.remove("show-controls");
    }, HIDE_CONTROLS_MS);
  };

  stage.addEventListener("pointermove", showControls);
  stage.addEventListener("pointerdown", showControls);
  ui.controls.addEventListener("focusin", showControls);
  ui.canvas.addEventListener("click", () => { player.toggle(); showControls(); });
  if (player.field) wireField(player);
  ui.canvas.addEventListener("dblclick", () => toggleFullscreen());
  ui.big.addEventListener("click", () => { player.play(); showControls(); });
  ui.play.addEventListener("click", () => { player.toggle(); showControls(); });
  ui.loop.addEventListener("click", () => player.setLoop(!player.loop));
  ui.theme.addEventListener("click", () => player.applyTheme(player.themeIndex + 1));

  ui.seek.max = String(Math.round(player.duration * 1000));
  ui.seek.step = String(Math.max(1, Math.round(1000 * player.m.fps.denominator / player.m.fps.numerator)));
  ui.seek.addEventListener("input", () => player.seek(Number(ui.seek.value) / 1000));

  if (player.audio) {
    const audio = player.audio;
    const savedVolume = Number(store.get("volume"));
    if (savedVolume >= 0 && savedVolume <= 1 && store.get("volume") !== null) audio.volume = savedVolume;
    ui.volume.value = String(audio.volume);
    ui.mute.addEventListener("click", () => {
      audio.muted = !audio.muted;
      if (!audio.muted && audio.volume === 0) audio.volume = 0.8;
      ui.volume.value = String(audio.volume);
      player._sync();
    });
    ui.volume.addEventListener("input", () => {
      audio.volume = Number(ui.volume.value);
      audio.muted = audio.volume === 0;
      store.set("volume", String(audio.volume));
      player._sync();
    });
    audio.addEventListener("ended", () => { if (!player.loop) player._ended(); });
    audio.addEventListener("waiting", () => document.body.classList.add("buffering"));
    audio.addEventListener("playing", () => { document.body.classList.remove("buffering"); player._sync(); player._schedule(); });
    audio.addEventListener("pause", () => player._sync());
    audio.addEventListener("seeked", () => { player.renderer.invalidate(); player.shown = -1; player._schedule(); });
  } else {
    ui.mute.hidden = true;
    ui.volume.hidden = true;
  }

  if (!fullscreenSupported()) ui.fullscreen.hidden = true;
  ui.fullscreen.addEventListener("click", () => toggleFullscreen());
  const onFs = () => {
    const on = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
    ui.fullscreen.setAttribute("aria-label", on ? "Exit full screen" : "Full screen");
    ui.fullscreen.dataset.state = on ? "on" : "off";
  };
  document.addEventListener("fullscreenchange", onFs);
  document.addEventListener("webkitfullscreenchange", onFs);

  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const onRange = e.target instanceof HTMLInputElement && e.target.type === "range";
    const onButton = e.target instanceof HTMLButtonElement;
    const frame = player.m.fps.denominator / player.m.fps.numerator;
    switch (e.key) {
      case " ":
      case "k":
      case "K":
        if (onButton && e.key === " ") return; // let the focused button handle Space
        e.preventDefault();
        player.toggle();
        break;
      case "ArrowLeft":
        if (onRange) return;
        e.preventDefault();
        player.seek(player.time() - (e.shiftKey ? frame : SEEK_STEP));
        break;
      case "ArrowRight":
        if (onRange) return;
        e.preventDefault();
        player.seek(player.time() + (e.shiftKey ? frame : SEEK_STEP));
        break;
      case "Home": player.seek(0); break;
      case "m": case "M": if (player.audio) ui.mute.click(); break;
      case "f": case "F": toggleFullscreen(); break;
      case "l": case "L": player.setLoop(!player.loop); break;
      case "t": case "T": player.applyTheme(player.themeIndex + 1); break;
      case "i": case "I": if (player.field) player.setInteraction(!player.field.enabled); break;
      default: return;
    }
    showControls();
  });

  // Resize + devicePixelRatio changes (zoom, moving between displays).
  new ResizeObserver(() => player.resize()).observe(stage);
  const watchDpr = () => {
    const mq = matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`);
    mq.addEventListener("change", () => { player.resize(); watchDpr(); }, { once: true });
  };
  watchDpr();

  // Background tabs may not run rAF; the clocks are time-based so nothing drifts.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { player.renderer.invalidate(); player.shown = -1; player._schedule(); }
  });
  ui.canvas.addEventListener("contextrestored", () => player.resize());
  showControls();
}

/**
 * Pointer -> lens position and ripples, in canvas device pixels. Events are
 * taken from the whole stage so overlays (the big play button, status text)
 * never block the lens.
 */
function wireField(player) {
  const canvas = ui.canvas;
  const field = player.field;
  const toDevice = (e) => {
    const r = canvas.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) return null;
    return [(e.clientX - r.left) * (canvas.width / r.width), (e.clientY - r.top) * (canvas.height / r.height)];
  };
  const leave = () => { field.clearPointer(); player.wakeField(); };
  ui.stage.addEventListener("pointermove", (e) => {
    const p = toDevice(e);
    if (p) field.setPointer(...p); else field.clearPointer();
    player.wakeField();
  });
  ui.stage.addEventListener("pointerdown", (e) => {
    const p = toDevice(e);
    if (!p) return;
    field.setPointer(...p);
    field.pulse(...p, 1.6);
    player.wakeField();
  });
  ui.stage.addEventListener("pointerleave", leave);
  ui.stage.addEventListener("pointercancel", leave);
  canvas.classList.toggle("lens-on", field.enabled && player.m.interaction.lens);
}

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

// ------------------------------------------------------------------ boot

async function main() {
  if (!supportsDecompression()) {
    throw new Error("This browser cannot play this film (it lacks DecompressionStream). Please use a current version of Chrome, Edge, Firefox or Safari.");
  }
  setStatus("Loading…");
  const manifest = validateManifest(await (await fetchChecked("manifest.json", "the film manifest")).json());
  document.title = manifest.title;
  ui.desc.textContent = manifest.description || `${manifest.title}: an animated film drawn entirely with text characters.`;
  ui.canvas.setAttribute("aria-label", ui.desc.textContent);
  document.documentElement.style.setProperty("--film-bg", manifest.theme.background);
  document.documentElement.style.setProperty("--film-fg", manifest.theme.foreground);

  const face = new FontFace(FONT_FAMILY, `url("${encodeURI(manifest.font.file)}") format("${manifest.font.file.endsWith(".woff2") ? "woff2" : "truetype"}")`);
  const fontLoad = face.load().then((f) => document.fonts.add(f)).catch(() => {
    throw new Error(`could not load the film's font (${manifest.font.file})`);
  });
  const buffer = await fetchWithProgress(manifest.animation, "the film", (p) => setStatus(`Loading… ${Math.round(p * 100)}%`));
  await fontLoad;
  const decoder = new AscfDecoder(buffer);
  if (decoder.columns !== manifest.columns || decoder.rows !== manifest.rows || decoder.frameCount !== manifest.frameCount) {
    throw new Error("film.ascf does not match manifest.json (re-upload both files)");
  }

  let audio = null;
  if (manifest.audio) {
    audio = new Audio();
    audio.preload = "auto";
    audio.src = manifest.audio;
  }

  const renderer = new AtlasRenderer(ui.canvas, manifest, decoder.glyphs, FONT_FAMILY);
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const ix = manifest.interaction;
  if ((ix.lens || ix.ripples) && !reduceMotion) renderer.attachField(new GlyphField(manifest.columns, manifest.rows, ix));
  const err = renderer.metricError();
  if (err > 0.02) console.warn(`ASCII Film: webfont advance differs from calibration by ${(err * 100).toFixed(1)}%`);

  const player = new Player(manifest, decoder, renderer, audio);
  window.asciiFilm = player; // handy for debugging and end-to-end tests
  player.applyTheme(player.themeIndex);
  player.resize();
  wireControls(player);
  setStatus("");

  if (manifest.autoplay === "muted" && !reduceMotion) {
    if (audio) audio.muted = true;
    await player.play();
  }
  player._sync();
  player._schedule();
  document.body.classList.add("ready");
}

main().catch((err) => showError(err.message || String(err)));
