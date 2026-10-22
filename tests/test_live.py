import json

from encoder.cli import main


def test_live_site_is_separate_and_complete(tmp_path):
    out = tmp_path / "www-live"
    assert main(["live", "--output", str(out), "--columns", "120", "--title", "Mirror"]) == 0
    files = {p.name for p in out.iterdir()}
    assert {"index.html", "live.js", "camera.js", "renderer.js", "field.js", "pointer.js",
            "player.css", "live.json", "font.woff2", "FONT-LICENSE.txt", ".htaccess"} <= files
    assert "film.ascf" not in files and "manifest.json" not in files
    htaccess = (out / ".htaccess").read_text()
    assert "RewriteRule ^ https://" in htaccess and "camera=(self)" in htaccess
    m = json.loads((out / "live.json").read_text())
    assert m["kind"] == "live" and m["title"] == "Mirror" and m["columns"] == 120
    assert m["glyphs"][0] == " " and m["coverage"][0] == 0
    assert m["coverage"] == sorted(m["coverage"]) and len(m["glyphs"]) == len(m["coverage"])
    assert 120 in m["columnSteps"]
    assert m["mapping"]["inkLight"] is True


def test_live_refuses_film_folder(tmp_path, capsys):
    out = tmp_path / "site"
    out.mkdir()
    (out / "film.ascf").write_bytes(b"x")
    assert main(["live", "--output", str(out), "--force"]) == 2
    assert "own folder" in capsys.readouterr().err


def test_live_needs_force_for_nonempty(tmp_path, capsys):
    out = tmp_path / "site"
    out.mkdir()
    (out / "notes.txt").write_text("x")
    assert main(["live", "--output", str(out)]) == 2
    assert main(["live", "--output", str(out), "--force"]) == 0
