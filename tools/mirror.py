#!/usr/bin/env python3
"""Mirror https://dashazhukova.com/ into ./site as a static website.

Crawls every page reachable by links from the homepage, downloads the
assets they reference (including assets referenced from CSS), and rewrites
all URLs to relative paths so the result can be served from any static host.

Usage: python3 tools/mirror.py          # full re-capture
       python3 tools/mirror.py patch    # re-apply EDITS to the existing site/
"""
import datetime
import glob
import hashlib
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit, unquote

ORIGIN = "https://dashazhukova.com"
HOST = "dashazhukova.com"
# Staging hostname that is still hard-coded in the theme's generated CSS.
STAGING = re.compile(r"https?://prodzhukova\.wpengine\.com")
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com"}
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PAGE_DELAY = 10  # robots.txt asks for Crawl-delay: 10
ASSET_DELAY = 0.5
DYNAMIC_CSS = "wp-content/dynamic.css"

ASSET_EXT = re.compile(
    r"\.(css|js|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|otf|eot|mp4|webm|pdf|json|xml|txt)$", re.I)
SKIP_PAGE = re.compile(r"^/(wp-admin|wp-json|wp-login|xmlrpc|feed|comments)|/feed/?$")
# <link> tags that only make sense on a live WordPress install.
DROP_REL = {"pingback", "alternate", "edituri", "shortlink", "https://api.w.org/",
            "dns-prefetch", "profile", "wlwmanifest"}

YEAR_SCRIPT = ("<script>document.querySelectorAll('.copyright-year').forEach("
               "function(e){e.textContent=new Date().getFullYear()})</script>\n</body>")
# Deliberate changes to the captured HTML, applied to every page: (old, new).
EDITS = [
    # Footer year: keep it current without editing the archive each January.
    ("<span>Copyright 2020 | All Rights Reserved</span>",
     f'<span>Copyright <span class="copyright-year">{datetime.date.today().year}</span>'
     " | All Rights Reserved</span>"),
    ("</body>", YEAR_SCRIPT),
]

pages = {}      # normalised page url -> html text
assets = {}     # local path -> True (fetched) / False (failed)
failures = []


def fetch(url, delay):
    time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        if e.code == 404 and delay == PAGE_DELAY:
            return e.read(), e.headers.get("Content-Type", "")
        failures.append(f"{e.code} {url}")
    except Exception as e:  # noqa: BLE001
        failures.append(f"{e!r} {url}")
    return None, ""


def norm_page(url):
    """Canonical form of an internal page URL, or None if it isn't one."""
    s = urlsplit(url)
    if s.netloc != HOST or s.query or ASSET_EXT.search(s.path) or SKIP_PAGE.search(s.path):
        return None
    return ORIGIN + (s.path.rstrip("/") + "/" if s.path.strip("/") else "/")


def page_file(url):
    return (urlsplit(url).path.strip("/") + "/index.html").lstrip("/")


def asset_file(url):
    s = urlsplit(url)
    if s.netloc == HOST:
        if s.path.endswith("admin-ajax.php") and "dynamic_css" in s.query:
            return DYNAMIC_CSS
        return unquote(s.path).lstrip("/") if ASSET_EXT.search(s.path) else None
    if s.netloc == "fonts.googleapis.com":
        return f"_external/fonts.googleapis.com/{hashlib.sha1(url.encode()).hexdigest()[:12]}.css"
    if s.netloc == "fonts.gstatic.com":
        return "_external/fonts.gstatic.com/" + unquote(s.path).lstrip("/")
    return None


def rel(from_file, to_file):
    return os.path.relpath(to_file, os.path.dirname(from_file) or ".").replace(os.sep, "/")


def write(path, data):
    full = os.path.join(OUT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def get_asset(url):
    """Download an asset once; return its local path (or None if not mirrored)."""
    url = STAGING.sub(ORIGIN, url)
    if url.startswith("//"):
        url = "https:" + url
    path = asset_file(url)
    if path is None:
        return None
    if path not in assets:
        assets[path] = False
        data, ctype = fetch(url, ASSET_DELAY)
        if data is not None:
            if path.endswith(".css") or "text/css" in ctype:
                data = rewrite_css(data.decode("utf-8", "replace"), url, path)
            write(path, data)
            assets[path] = True
            print(f"  asset {path}")
    return path


def rewrite_css(text, base_url, from_file):
    def sub(m):
        raw = m.group("u").strip()
        if raw.startswith(("data:", "#", "about:")):
            return m.group(0)
        target = urljoin(base_url, STAGING.sub(ORIGIN, raw))
        frag = ""
        if "#" in target:
            target, frag = target.split("#", 1)
            frag = "#" + frag
        path = get_asset(target)
        if path is None:
            return m.group(0)
        return m.group(0).replace(m.group("u"), rel(from_file, path) + frag)

    text = re.sub(r"url\(\s*(?P<q>['\"]?)(?P<u>[^'\")]+)(?P=q)\s*\)", sub, text)
    return re.sub(r"@import\s+(?P<q>['\"])(?P<u>[^'\"]+)(?P=q)", sub, text)


URL_IN_TAG = re.compile(
    r"(?:https?:)?//(?:dashazhukova\.com|prodzhukova\.wpengine\.com|fonts\.googleapis\.com)"
    r"[^\"'\s<>)]*")


def rewrite_html(text, page_url):
    from_file = page_file(page_url)

    def sub_url(m):
        raw = m.group(0)
        url = html.unescape(STAGING.sub(ORIGIN, raw))
        if url.startswith("//"):
            url = "https:" + url
        frag = ""
        if "#" in url:
            url, frag = url.split("#", 1)
            frag = "#" + frag
        path = get_asset(url)
        if path:
            return rel(from_file, path) + frag
        page = norm_page(url)
        if page in pages:
            target = rel(from_file, page_file(page))
            return target[: -len("index.html")] or "./" if not frag else target[: -len("index.html")] + frag
        return raw

    def sub_tag(m):
        tag = m.group(0)
        name = m.group(1).lower()
        if name == "meta":
            return tag
        if name == "link":
            relm = re.search(r"rel=['\"]([^'\"]+)['\"]", tag, re.I)
            relv = relm.group(1).lower() if relm else ""
            if relv in DROP_REL:
                return ""
            if relv == "canonical":
                return tag
        return URL_IN_TAG.sub(sub_url, tag)

    text = re.sub(r"<([a-zA-Z][\w-]*)\b[^>]*>", sub_tag, text)
    # Inline <style> blocks may reference images/fonts too.
    text = re.sub(
        r"(<style\b[^>]*>)(.*?)(</style>)",
        lambda m: m.group(1) + rewrite_css(m.group(2), page_url, from_file) + m.group(3),
        text, flags=re.S | re.I)
    return apply_edits(text)


def apply_edits(text):
    for old, new in EDITS:
        text = text.replace(old, new)
    return text


def patch():
    """Re-apply EDITS to an existing capture (idempotent for already-edited pages)."""
    for path in glob.glob(os.path.join(OUT, "**", "*.html"), recursive=True):
        # newline="" keeps the captured pages' mixed CRLF/LF line endings intact.
        with open(path, encoding="utf-8", newline="") as f:
            orig = f.read()
        # Undo the year script so the "</body>" edit doesn't stack.
        new = apply_edits(orig.replace(YEAR_SCRIPT, "</body>"))
        if new != orig:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            print(f"patched {os.path.relpath(path, OUT)}")


def crawl():
    queue = [ORIGIN + "/"]
    while queue:
        url = queue.pop(0)
        if url in pages:
            continue
        print(f"page {url}")
        data, ctype = fetch(url, PAGE_DELAY if pages else 0)
        if data is None or "html" not in ctype:
            pages[url] = None
            continue
        text = data.decode("utf-8", "replace")
        pages[url] = text
        for href in re.findall(r"<a\b[^>]*\bhref=[\"']([^\"'#]+)", text, re.I):
            page = norm_page(urljoin(url, html.unescape(href)))
            if page and page not in pages and page not in queue:
                queue.append(page)


def main():
    crawl()
    for url, text in pages.items():
        if text is not None:
            write(page_file(url), rewrite_html(text, url))
    # A static-host friendly 404 page (GitHub Pages / Netlify convention).
    # Its links are relative to the site root, so it only renders correctly
    # for missing top-level paths.
    data, _ = fetch(ORIGIN + "/this-page-does-not-exist/", PAGE_DELAY)
    if data:
        text = rewrite_html(data.decode("utf-8", "replace"), ORIGIN + "/")
        with open(os.path.join(OUT, "404.html"), "w", encoding="utf-8") as f:
            f.write(text)
    print(f"\n{sum(t is not None for t in pages.values())} pages, "
          f"{sum(assets.values())} assets -> {OUT}")
    if failures:
        print("FAILED:")
        for f in failures:
            print("  " + f)
        sys.exit(1)


if __name__ == "__main__":
    patch() if sys.argv[1:] == ["patch"] else main()
