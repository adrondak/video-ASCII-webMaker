# Fonts

The encoder calibrates glyph ink coverage against a local TTF/OTF, and the
player draws with the matching webfont. Both files must be the **same font**,
and it must be legally redistributable because it is copied into every
publish directory.

| File | Use |
|---|---|
| `DejaVuSansMono.ttf` | Default calibration font (encoder) |
| `DejaVuSansMono.woff2` | Default webfont (copied into the publish dir) |
| `DejaVuSansMono-Bold.ttf` / `.woff2` | Heavier alternative for denser tones |
| `LICENSE-DejaVu.txt` | Bitstream Vera / DejaVu license, shipped with every film |

The WOFF2 files are lossless conversions of the TTFs, produced with:

```bash
python -c "from fontTools.ttLib import TTFont; f=TTFont('DejaVuSansMono.ttf'); f.flavor='woff2'; f.save('DejaVuSansMono.woff2')"
```

## Using another font

Pass `--font path/to/Font.ttf`. The encoder looks for `Font.woff2` next to it
(falling back to shipping the TTF itself) and for a license file named
`LICENSE*` or `Font.LICENSE*` in the same directory. The font must be
fixed-pitch; proportional fonts are rejected unless
`--allow-proportional-font` is given. Do not publish fonts you are not allowed
to redistribute.
