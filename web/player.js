// Checkpoint 04 player: load manifest, font and film; play on a wall clock; loop.
import { AscfDecoder, supportsDecompression } from "./decoder.js";
import { TextRenderer } from "./renderer.js";

const status = document.getElementById("status");

async function main() {
  if (!supportsDecompression()) throw new Error("This browser lacks DecompressionStream; please use a current Chrome, Firefox or Safari.");
  const manifest = await (await fetch("manifest.json")).json();
  document.title = manifest.title;
  const face = new FontFace("ASCIIFilmFont", `url(${manifest.font.file})`);
  document.fonts.add(await face.load());
  const decoder = new AscfDecoder(await (await fetch(manifest.animation)).arrayBuffer());
  const renderer = new TextRenderer(document.getElementById("film"), manifest, decoder.glyphs);
  renderer.resize();
  addEventListener("resize", () => renderer.resize());
  status.textContent = "";
  const t0 = performance.now();
  const tick = async () => {
    let t = (performance.now() - t0) / 1000;
    if (manifest.loop) t %= decoder.durationSeconds;
    renderer.draw(await decoder.frame(decoder.frameAt(t)));
    requestAnimationFrame(tick);
  };
  tick();
}

main().catch((err) => { status.textContent = `Error: ${err.message}`; });
