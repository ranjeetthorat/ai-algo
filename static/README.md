# FastAlgo public site

A static copy of the app's home page (`frontend/src/pages/Home.tsx`) for
hosting on its own. In place of the app's log-in it offers the Windows desktop
download, and it adds a section on the supported brokers. It needs
no build step, no server and no external files: open `index.html` in a browser
to preview it.

## Contents

- `index.html` - the page. Styles, icons and the light/dark switch are inline.
- `site-config.js` - settings you may want to change without touching the page:
  the download link and the note under it, and the Telegram support link. A
  value left empty is hidden.
- `assets/` - logo, favicon and touch icon, copied from
  `frontend/src/brand/assets/`.

## Hosting

Upload the contents of this folder as they are, with `index.html` at the root.
Include `site-config.js`: without it the download button and the Telegram links
stay hidden.

**For each release**, `scripts/build_release.py` writes `latest.json` here and
fills in `downloadUrl` and `downloadNote` in `site-config.js`. Upload the new zip
from `release/` first, then this folder. Installed control panels read
`latest.json` from the site root to offer the update, so it must be uploaded
with the rest.

- **S3:** enable static website hosting on the bucket, set the index document to
  `index.html`, and upload `index.html` and `assets/`.
- **GitHub Pages:** publish this folder, or copy its contents to the root of the
  Pages branch.

`og:url` and `og:image` assume the page is served at
`https://fastalgo.tinycompute.site/`. Change both if it is hosted elsewhere, or
link previews will show no image.

## Keeping it in step with the app

This page is a hand-maintained copy. The product name, tagline, maker and support
link come from `frontend/src/brand/brand.ts`, the colours from the "Ink and Pulse"
tokens in `frontend/src/index.css`, and the copy and feature counts from
`Home.tsx`. The broker list mirrors `VALID_BROKERS` in `.sample.env`, without the
Dhan sandbox, and with the two 5paisa plugins shown once. Change those first, then mirror the change here. The
Telegram link lives in `site-config.js` and matches `supportTelegramUrl` in
`brand.ts`.

`node scripts/brand-check.mjs` scans this page. The AGPL attribution line in its
footer is allowed, so any other upstream name or link is still reported.
