# FastAlgo public site

A static copy of the app's home page (`frontend/src/pages/Home.tsx`) for
hosting on its own, without the app's log-in and installation links. It needs
no build step, no server and no external files: open `index.html` in a browser
to preview it.

## Contents

- `index.html` - the page. Styles, icons and the light/dark switch are inline.
- `assets/` - logo, favicon and touch icon, copied from
  `frontend/src/brand/assets/`.

## Hosting

Upload the contents of this folder as they are, with `index.html` at the root.

- **S3:** enable static website hosting on the bucket, set the index document to
  `index.html`, and upload `index.html` and `assets/`.
- **GitHub Pages:** publish this folder, or copy its contents to the root of the
  Pages branch.

`og:url` and `og:image` assume the page is served at
`https://fastalgo.tinycompute.site/`. Change both if it is hosted elsewhere, or
link previews will show no image.

## Keeping it in step with the app

This page is a hand-maintained copy. The product name, tagline, maker, support
link and contact email come from `frontend/src/brand/brand.ts`, the colours from
the "Ink and Pulse" tokens in `frontend/src/index.css`, and the copy and feature
counts from `Home.tsx`. Change those first, then mirror the change here.

`node scripts/brand-check.mjs` scans this page. The AGPL attribution line in its
footer is allowed, so any other upstream name or link is still reported.
