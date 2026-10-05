# dashazhukova.com — static mirror

Static archive of <https://dashazhukova.com/>, captured 2026-10-02.

- `site/` — the mirrored website. Serve it with any static host
  (`cd site && python3 -m http.server`). Pushes to `main` deploy it to
  GitHub Pages via `.github/workflows/pages.yml`.
- `tools/mirror.py` — the script that produced it (Python 3, no dependencies).
  Re-running it overwrites `site/` with a fresh capture. Deliberate edits to
  the captured pages live in its `EDITS` list; `python3 tools/mirror.py patch`
  re-applies them to the existing `site/` without re-crawling.

## Edits made to the archived pages

- Footer copyright year is set to the current year by a small inline script
  (falls back to the year of capture without JavaScript).

## Differences from the live site

- Internal URLs are rewritten to relative paths and Google Fonts are served
  locally from `_external/`, so the site works from any path on any static host.
- Search, RSS feeds and the WordPress API are not available (they need a server).
- Headings use an Adobe Fonts web kit loaded from Adobe's servers under the
  original site owner's account. If that kit is ever disabled the headings fall
  back to a default font.
