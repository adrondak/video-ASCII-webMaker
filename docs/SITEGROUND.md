# Hosting on SiteGround (or any Apache shared host)

The publish folder is plain static files, so it runs on SiteGround's standard
hosting with no PHP, database, Node or build step. These steps also work for
cPanel hosts and most other Apache/Nginx shared hosting.

## What you upload

Everything **inside** `www/` (or your own `dist/<film>/`):

```text
index.html  player.css  player.js  decoder.js  renderer.js
film.ascf   manifest.json   font.woff2   FONT-LICENSE.txt   .htaccess
```

`.htaccess` is a hidden file. It is optional (the site works without it) but
it sets MIME types, avoids re-compressing the already-compressed film, and adds
sensible cache headers. Every directive in it is wrapped in `<IfModule>`, so it
cannot cause a 500 error if a module is missing.

## Option A — Site Tools File Manager (easiest)

1. Make a zip of the folder's contents:
   ```bash
   scripts/package-zip.sh www          # -> dist/www-site.zip (≈2.9 MB for the demo)
   ```
2. In SiteGround **Site Tools → Site → File Manager**, open `public_html/`
   (or create a subfolder such as `public_html/ocean/` to host it at
   `https://example.com/ocean/`).
3. Click **File Upload**, choose `www-site.zip`, then right-click the zip →
   **Extract**. Delete the zip afterwards.
4. Make sure `index.html` sits directly in the folder you chose (not in a
   nested `www/` folder).
5. Visit the URL. The film starts playing silently and loops.

If the folder already has an `index.php` or `index.html` from another site,
either use a subfolder or remove/rename the old index first.

## Option B — SFTP

SiteGround → **Site Tools → Devs → SSH Keys Manager** to create a key, then:

```bash
# host, port and user are shown in Site Tools → Devs → SSH Keys Manager → Manage → SSH Credentials
rsync -avz --delete -e "ssh -p 18765" www/ USER@HOST:www/YOURDOMAIN/public_html/ocean/
```

The trailing slash on `www/` copies the contents (including `.htaccess`).
Plain SFTP clients (FileZilla, Cyberduck, Transmit) work too — enable
"show hidden files" so `.htaccess` is uploaded.

## After uploading

* Open the page and wait for the first frame. If you see an error message,
  it names the file that failed (for example `HTTP 404` for `film.ascf`).
* SiteGround's **SuperCacher / Dynamic Cache** may serve an old copy after you
  replace the film. Purge it in **Site Tools → Speed → Caching** (or keep the
  `.htaccess`, which marks `manifest.json` and the scripts `no-cache`).
* HTTPS (Let's Encrypt) works unchanged — all paths are relative.
* The page makes no requests outside your domain (no CDNs, fonts or
  analytics), so there is nothing to allow-list.

## Updating the film

Re-encode, re-zip, and upload again, replacing **both** `film.ascf` and
`manifest.json` (the player refuses a mismatched pair). Purge the cache.

## Requirements on the visitor's side

A browser with `DecompressionStream` — Chrome/Edge 80+, Firefox 113+,
Safari 16.4+ (all 2023 or newer). Older browsers get a clear message instead
of a blank page.
