// Pointer -> glyph-field wiring shared by the film player and the live page.
//
// Events are taken from the whole stage so overlays (play button, status
// text) never block the lens; positions are converted to canvas device pixels.

/**
 * @param {HTMLElement} stage element that receives pointer events
 * @param {HTMLCanvasElement} canvas the glyph canvas
 * @param {() => import("./field.js").GlyphField | null} getField current field (may change)
 * @param {() => void} wake request animation frames for the field
 */
export function wirePointer(stage, canvas, getField, wake) {
  const toDevice = (e) => {
    const r = canvas.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) return null;
    return [(e.clientX - r.left) * (canvas.width / r.width), (e.clientY - r.top) * (canvas.height / r.height)];
  };
  const leave = () => {
    const field = getField();
    if (field) { field.clearPointer(); wake(); }
  };
  stage.addEventListener("pointermove", (e) => {
    const field = getField();
    if (!field) return;
    const p = toDevice(e);
    if (p) field.setPointer(...p); else field.clearPointer();
    wake();
  });
  stage.addEventListener("pointerdown", (e) => {
    const field = getField();
    const p = field && toDevice(e);
    if (!p) return;
    field.setPointer(...p);
    field.pulse(...p, 1.6);
    wake();
  });
  stage.addEventListener("pointerleave", leave);
  stage.addEventListener("pointercancel", leave);
}
