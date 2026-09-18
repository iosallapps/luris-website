"""Check the site before every push. Exits non-zero on any failure.

    python3 _tools/validate.py

It reads the site's own files (never a copy of their values) and fails on:
  - a word from the claims register's "never" list in visible text, alt text, ARIA
    labels, meta tags or JSON-LD of the marketing pages, or in the meta and JSON-LD of
    the legal pages (the legal text itself may name purchases, it states nothing is sold);
  - an em dash or en dash anywhere (the owner's rule);
  - placeholders (idXXXXXXXXXX, meta.description, TODO, lorem);
  - a missing <html lang>, <title>, description, canonical or OG image, or a duplicate title;
  - an App Store link, Smart App Banner or downloadUrl that does not match the state in
    _tools/release.json (none before release; campaign codes on every link after);
  - an <img> without width, height or alt, or any image file that does not exist;
  - any script, stylesheet, font or image loaded from another origin, or any script
    other than JSON-LD; JSON-LD that does not parse, or that carries offers or ratings;
  - an internal link or #fragment that does not resolve;
  - the Apple logo anywhere;
  - a sitemap that misses an indexable page or lists the 404 page.
"""
import html
import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
ORIGIN = "https://lurisapp.com"
PAGES = ["index.html", "support.html", "privacy.html", "terms.html", "404.html"]
MARKETING = {"index.html", "support.html", "404.html"}

# the claims register's "never" list (website brief, section 2 and 7.9)
NEVER = [
    (r"\bfree\b", re.I), (r"\bprices?\b|\bpricing\b", re.I), (r"\bsubscri", re.I), (r"\bpremium\b", re.I),
    (r"\btrials?\b", re.I), (r"\bPro\b", 0), (r"\bfriends?\b", re.I), (r"\bcycling\b|\bcyclists?\b", re.I),
    (r"\bhiking\b|\bhikes?\b", re.I), (r"heart rate", re.I), (r"#1\b", 0), (r"\bbest\b", re.I),
    (r"\bawards?\b|award-winning", re.I), (r"\bratings?\b|\bstars?\b", re.I), (r"\breviews?\b", re.I),
    (r"\bAndroid\b", re.I), (r"Google Play", re.I), (r"\bcoach", re.I), (r"\bAI\b", 0),
    (r"personali[sz]ed", re.I), (r"Data Not Collected", re.I), (r"testimonial", re.I),
    (r"\bmillions?\b", re.I), (r"\bpurchas", re.I),
]
DASHES = ["—", "–", "&mdash;", "&ndash;", "&#8212;", "&#8211;", "&#x2014;", "&#x2013;"]
PLACEHOLDERS = ["idXXXXXXXXXX", "meta.description", "TODO", "lorem ipsum", "FIXME"]

failures = []


def fail(page, message):
    failures.append(f"{page}: {message}")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []          # (tag, attrs dict)
        self.text = []
        self.ids = set()
        self.scripts = []       # (type, body)
        self._script = None
        self._skip = 0
        self.title = None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "script":
            self._script = [attrs.get("type", ""), ""]
        if tag in ("style",):
            self._skip += 1
        if tag == "title":
            self._in_title = True
            self.title = ""

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append(tuple(self._script))
            self._script = None
        if tag == "style":
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._script is not None:
            self._script[1] += data
        elif self._in_title:
            self.title += data
        elif not self._skip:
            self.text.append(data)


def parse(page):
    with open(os.path.join(SITE, page), encoding="utf-8") as handle:
        raw = handle.read()
    parsed = Page()
    parsed.feed(raw)
    return raw, parsed


def meta(parsed, key, value):
    for tag, attrs in parsed.tags:
        if tag == "meta" and attrs.get(key) == value:
            return attrs.get("content")
    return None


def local_path(url, page):
    """Map a same-site URL to a file path, or None for another origin."""
    parts = urlparse(url)
    if parts.scheme in ("http", "https"):
        if f"{parts.scheme}://{parts.netloc}" != ORIGIN:
            return None
        path = parts.path
    elif parts.scheme or url.startswith("//"):
        return None
    else:
        path = parts.path
        if not path.startswith("/"):
            path = "/" + os.path.join(os.path.dirname(page), path)
    path = path or "/"
    if path.endswith("/"):
        path += "index.html"
    return os.path.join(SITE, path.lstrip("/"))


def main():
    with open(os.path.join(HERE, "release.json")) as handle:
        state = json.load(handle)
    parsed_pages = {}
    titles = {}
    for page in PAGES:
        raw, parsed = parse(page)
        parsed_pages[page] = (raw, parsed)

    for page, (raw, parsed) in parsed_pages.items():
        # language, title, description, canonical, social image
        html_tag = next((a for t, a in parsed.tags if t == "html"), {})
        if not html_tag.get("lang"):
            fail(page, "<html> has no lang")
        if not parsed.title or not parsed.title.strip():
            fail(page, "no <title>")
        else:
            titles.setdefault(parsed.title.strip(), []).append(page)
        description = meta(parsed, "name", "description")
        if not description:
            fail(page, "no meta description")
        if page != "404.html":
            canonical = next((a.get("href") for t, a in parsed.tags if t == "link" and a.get("rel") == "canonical"), None)
            expected = ORIGIN + ("/" if page == "index.html" else "/" + page)
            if canonical != expected:
                fail(page, f"canonical is {canonical!r}, expected {expected}")
            image = meta(parsed, "property", "og:image")
            if not image or not os.path.exists(local_path(image, page) or ""):
                fail(page, f"og:image {image!r} missing or not a file on this site")
            if meta(parsed, "name", "twitter:card") != "summary_large_image":
                fail(page, "no twitter:card")

        # dashes and placeholders, anywhere in the file
        for dash in DASHES:
            if dash in raw:
                fail(page, f"contains a dash character {dash!r}")
        for placeholder in PLACEHOLDERS:
            if placeholder.lower() in raw.lower():
                fail(page, f"placeholder {placeholder!r}")

        # the claims register
        attrs_text = " ".join(a.get(k, "") for t, a in parsed.tags for k in ("alt", "aria-label", "title"))
        meta_text = " ".join(a.get("content", "") for t, a in parsed.tags if t == "meta")
        ld_text = " ".join(body for kind, body in parsed.scripts if kind == "application/ld+json")
        scopes = {"meta": meta_text + " " + (parsed.title or ""), "json-ld": ld_text}
        if page in MARKETING:
            scopes["text"] = html.unescape(" ".join(parsed.text)) + " " + attrs_text
        for scope, text in scopes.items():
            for pattern, flags in NEVER:
                hit = re.search(pattern, text, flags)
                if hit:
                    start = max(0, hit.start() - 40)
                    fail(page, f"never-word {hit.group(0)!r} in {scope}: ...{text[start:hit.end() + 40].strip()}...")

        # scripts: JSON-LD only, parseable, no offers or ratings
        for kind, body in parsed.scripts:
            if kind != "application/ld+json":
                fail(page, f"script of type {kind or 'javascript'!r}; the site ships no JavaScript")
                continue
            try:
                data = json.loads(body)
            except json.JSONDecodeError as error:
                fail(page, f"JSON-LD does not parse: {error}")
                continue
            blob = json.dumps(data)
            for key in ("offers", "aggregateRating", "review"):
                if f'"{key}"' in blob:
                    fail(page, f"JSON-LD carries {key}")
            has_download = '"downloadUrl"' in blob
            if has_download != bool(state["released"]):
                fail(page, f"JSON-LD downloadUrl present={has_download} but released={state['released']}")

        # release state
        banner = meta(parsed, "name", "apple-itunes-app")
        store_links = re.findall(r'href="(https://apps\.apple\.com[^"]*)"', raw)
        if state["released"]:
            if banner != "app-id=6813596103":
                fail(page, "no Smart App Banner after release")
            for link in store_links:
                link = html.unescape(link)
                if "ct=web-" not in link or (state.get("provider_token") and f"pt={state['provider_token']}" not in link):
                    fail(page, f"App Store link without campaign codes: {link}")
        else:
            if banner:
                fail(page, "Smart App Banner before release")
            if store_links:
                fail(page, f"App Store link before release (it would 404): {store_links[0]}")
        if "i-apple" in raw or "" in raw:
            fail(page, "the Apple logo is used")

        # images, sources and every loaded resource stay on this site
        for tag, attrs in parsed.tags:
            if tag == "img":
                for key in ("width", "height", "alt"):
                    if key not in attrs:
                        fail(page, f"<img src={attrs.get('src')!r}> has no {key}")
            urls = []
            if tag in ("img", "script", "source", "iframe", "video", "audio", "embed"):
                urls += [attrs.get("src")] if attrs.get("src") else []
                for key in ("srcset",):
                    if attrs.get(key):
                        urls += [part.strip().split(" ")[0] for part in attrs[key].split(",")]
            if tag == "link" and attrs.get("rel") in ("stylesheet", "icon", "apple-touch-icon", "preload", "manifest"):
                urls += [attrs["href"]] if attrs.get("href") else []
                if attrs.get("imagesrcset"):
                    urls += [part.strip().split(" ")[0] for part in attrs["imagesrcset"].split(",")]
            if tag == "use" and attrs.get("href") and not attrs["href"].startswith("#"):
                urls += [attrs["href"]]
            for url in urls:
                path = local_path(url, page)
                if path is None:
                    fail(page, f"loads {url} from another origin")
                elif not os.path.exists(path):
                    fail(page, f"missing file {url}")
            if tag == "use" and attrs.get("href", "").startswith("#") and attrs["href"][1:] not in parsed.ids:
                fail(page, f"<use> points at missing symbol {attrs['href']}")

        # links resolve, fragments included
        for tag, attrs in parsed.tags:
            if tag != "a" or "href" not in attrs:
                continue
            href = attrs["href"]
            if href.startswith(("mailto:", "tel:")):
                continue
            if href.startswith("#"):
                if href[1:] and href[1:] not in parsed.ids:
                    fail(page, f"link to missing #{href[1:]}")
                continue
            path = local_path(href, page)
            if path is None:
                continue    # another site: checked by the live link check, not here
            if not os.path.exists(path):
                fail(page, f"link to missing page {href}")
                continue
            fragment = urlparse(href).fragment
            if fragment:
                target = os.path.relpath(path, SITE)
                ids = parsed_pages[target][1].ids if target in parsed_pages else parse(target)[1].ids
                if fragment not in ids:
                    fail(page, f"link {href} points at a missing fragment")

    for title, pages in titles.items():
        if len(pages) > 1:
            fail(", ".join(pages), f"duplicate title {title!r}")

    with open(os.path.join(SITE, "sitemap.xml")) as handle:
        sitemap = handle.read()
    listed = set(re.findall(r"<loc>([^<]+)</loc>", sitemap))
    for page in PAGES:
        url = ORIGIN + ("/" if page == "index.html" else "/" + page)
        if page == "404.html":
            if url in listed:
                fail("sitemap.xml", "lists the 404 page")
        elif url not in listed:
            fail("sitemap.xml", f"misses {url}")

    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for line in failures:
            print(f"  {line}")
        sys.exit(1)
    print(f"PASS: {len(PAGES)} pages, release state: {'released' if state['released'] else 'coming soon'}")


if __name__ == "__main__":
    main()
