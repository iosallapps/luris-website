"""Build the shared parts of every page on lurisapp.com.

    python3 _tools/build_pages.py                  rebuild the shared regions of every page
    python3 _tools/build_pages.py release [--pt N] release day: switch "Coming soon" to
                                                   the live App Store links, then rebuild
                                                   (see _tools/release-day.md)

The pages are plain HTML files edited by hand. Each one carries marked regions,

    <!-- build:NAME -->  ...  <!-- /build:NAME -->

and this script rewrites what is between the markers, so the header, footer, icon
sprite, <head> basics, SEO tags, JSON-LD, the download call to action and the Apple
trademark credit are identical on every page and change in one place. Everything
outside the markers (the page content, the legal text) is never touched.

Regions: head, meta, sprite, header, footer (every page); hero-cta, final-cta,
jsonld (home page only). It also writes sitemap.xml, with each page's lastmod taken
from git (today for a page that differs from the last commit).

State lives in _tools/release.json: {"released": false, "provider_token": ""}.
Before release the site links to nothing on the App Store (the product page returns
404 until Apple publishes it). After `release`, every placement links to the product
page with its own campaign code, the Smart App Banner is added to every page, a QR
code appears for desktop visitors and the JSON-LD gains downloadUrl and sameAs.

No dependencies beyond Python 3.9. The QR code uses segno, vendored in _tools/vendor.
"""
import datetime
import hashlib
import html
import json
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
STATE_FILE = os.path.join(HERE, "release.json")

ORIGIN = "https://lurisapp.com"
APP_ID = "6813596103"
APP_NAME = "Luris: Step & Activity Tracker"   # the App Store Connect name
CONTACT = "iosallapps@gmail.com"
DEVELOPER = "Cirjan Darius"
YEAR = 2026
OG_IMAGE = {"path": "/og-image.jpg", "width": 1200, "height": 630,
            "alt": "Luris on two iPhones, the Home tab with today's steps ring and a run drawn on the "
                   "map, over a runner at dusk, beside the words Everything you need to move more."}

LANGUAGES = ["en", "ar", "bn", "ca", "zh-Hans", "zh-Hant", "hr", "cs", "da", "nl", "fi", "fr", "de", "el", "gu", "he", "hi", "hu", "id", "it", "ja", "kn", "ko", "ms", "ml", "mr", "nb", "or", "pl", "pt-BR", "pt-PT", "pa", "ro", "ru", "sk", "sl", "es", "sv", "ta", "te", "th", "tr", "uk", "ur", "vi"]

PAGES = {
    "index.html": {
        "path": "/", "nav": None, "og_type": "website",
        "title": f"{APP_NAME} for iPhone",
        "description": "Luris counts your steps from Apple Health, maps your walks, runs and bike rides "
                       "with GPS and builds a six-week plan from 873 exercises. No account needed.",
        "social": "Steps, GPS walks, runs and rides, a six-week plan and progress you can see, built on "
                  "Apple Health.",
    },
    "support.html": {
        "path": "/support.html", "nav": "support", "og_type": "website",
        "title": "Luris Support: Help and Questions",
        "description": "Get help with Luris: contact the developer, and answers about Apple Health, "
                       "GPS walks, runs and rides, the Game Center leaderboard, units, supported iPhones "
                       "and deleting your data.",
        "social": "Contact the developer and find answers about Apple Health, GPS walks, runs and rides, "
                  "the leaderboard and your data.",
    },
    "privacy.html": {
        "path": "/privacy.html", "nav": None, "og_type": "article",
        "title": "Luris Privacy Policy",
        "description": "How Luris handles your data: health data stays on your iPhone. Ads, analytics and "
                       "crash reports from Google, purchases through RevenueCat, and what goes to Apple.",
        "social": "Health data stays on your iPhone. What goes to Apple, and nothing to the developer.",
    },
    "terms.html": {
        "path": "/terms.html", "nav": None, "og_type": "article",
        "title": "Luris Terms of Use",
        "description": "The terms for using Luris, the fitness tracker for iPhone: your licence, the "
                       "health and fitness disclaimer, safety on walks, runs and rides and the leaderboard "
                       "rules.",
        "social": "Your licence, the health and fitness disclaimer, safety on walks, runs and rides and "
                  "the leaderboard rules.",
    },
    "404.html": {
        "path": None, "nav": None, "og_type": None, "robots": "noindex",
        "title": "Page not found | Luris",
        "description": "This page does not exist or has moved.",
    },
}

# Content-Security-Policy as a meta tag (GitHub Pages cannot send headers). Same-origin
# only: no third-party request of any kind can happen, which is also why the site
# needs no cookie banner. JSON-LD is a data block, not a script, so it is not blocked.
CSP = ("default-src 'none'; img-src 'self' data:; style-src 'self'; font-src 'self'; connect-src 'self'; "
       "media-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; "
       "upgrade-insecure-requests")

# App Store campaign codes, one per placement (App Analytics > Acquisition > Campaigns).
CAMPAIGNS = ("web-header", "web-hero", "web-final", "web-footer", "web-qr", "web-support")

# Apple's trademark list (apple.com/legal/intellectual-property/trademark/appletmlist.html,
# checked 18 September 2026). The footer credits only the marks a page actually uses.
# Game Center, Sign in with Apple and Apple Maps are not on the list, so they get no credit.
REGISTERED_MARKS = ["Apple", "Apple Watch", "App Store", "Dynamic Island", "HealthKit", "iPad",
                    "iPhone", "Live Activities"]
UNREGISTERED_MARKS = ["Apple Health"]
MARK_PATTERNS = {
    "Apple": r"\bApple(?! Health\b| Watch\b)",
    "Apple Watch": r"\bApple Watch\b",
    "App Store": r"\bApp Store\b",
    "Dynamic Island": r"\bDynamic Island\b",
    "HealthKit": r"\bHealthKit\b",
    "iPad": r"\biPad\b",
    "iPhone": r"\biPhone\b",
    "Live Activities": r"\bLive Activit(y|ies)\b",
    "Apple Health": r"\bApple Health\b",
}


# ---------------------------------------------------------------- state and links

def load_state():
    with open(STATE_FILE) as handle:
        return json.load(handle)


def store_link(state, campaign):
    assert campaign in CAMPAIGNS, campaign
    query = []
    if state.get("provider_token"):
        query.append(f"pt={state['provider_token']}")
    query += [f"ct={campaign}", "mt=8"]
    return f"https://apps.apple.com/app/id{APP_ID}?" + "&".join(query)


def esc(text):
    return html.escape(text, quote=True)


# ---------------------------------------------------------------- fragments

ICONS = {
    # 24x24 line icons drawn for this site; currentColor, no Apple artwork
    "i-check": '<circle cx="12" cy="12" r="11" fill="currentColor" fill-opacity=".16"/>'
               '<path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
               'stroke-linejoin="round" d="m7.5 12.4 3 3 6-6.4"/>',
    "i-widget": '<g fill="none" stroke="currentColor" stroke-width="2"><rect x="3.5" y="3.5" width="7" '
                'height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" '
                'y="13.5" width="17" height="7" rx="2"/></g>',
    "i-live": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="6" '
              'y="2.5" width="12" height="19" rx="3.2"/><rect x="9" y="5.3" width="6" height="2.2" rx="1.1" '
              'fill="currentColor" stroke="none"/><path d="M9 15.5h6"/></g>',
    "i-ruler": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
               'stroke-linejoin="round"><path d="M3.6 16.2 16.2 3.6a1.4 1.4 0 0 1 2 0l2.2 2.2a1.4 1.4 0 0 1 0 2L7.8 20.4'
               'a1.4 1.4 0 0 1-2 0l-2.2-2.2a1.4 1.4 0 0 1 0-2z"/><path d="m7.4 12.4 2 2M10.4 9.4l1.4 1.4M13.4 6.4l2 2"/></g>',
    "i-globe": '<g fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/>'
               '<path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></g>',
    "i-watch": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round">'
               '<rect x="6" y="6" width="12" height="12" rx="3.4"/><path d="M8.5 6 9.3 2.5h5.4L15.5 6M8.5 18l.8 3.5h5.4l.8-3.5"/></g>',
    "i-user": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" '
              'cy="8" r="4"/><path d="M4.5 20.5a7.5 7.5 0 0 1 15 0"/></g>',
    "i-phone": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
               'stroke-linejoin="round"><rect x="6" y="2.5" width="12" height="19" rx="3"/>'
               '<path d="M10.2 12.2h3.6v3.3h-3.6zM10.9 12.2v-1.1a1.1 1.1 0 0 1 2.2 0v1.1"/></g>',
    "i-out": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
             'stroke-linejoin="round"><path d="M14 4h6v6M20 4l-8.5 8.5"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 '
             '1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/></g>',
    "i-clock": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle '
               'cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/></g>',
    "i-mail": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><rect x="3" '
              'y="5" width="18" height="14" rx="2.5"/><path d="m3.8 6.5 8.2 6.3 8.2-6.3"/></g>',
}


ICONS.update({
    "i-heart": '<path fill="currentColor" d="M12 20.6s-7.9-4.7-9.4-9.7C1.5 7.3 3.8 4 7.2 4c2 0 3.6 1.1 4.8 2.8C13.2 5.1 '
               '14.8 4 16.8 4c3.4 0 5.7 3.3 4.6 6.9-1.5 5-9.4 9.7-9.4 9.7z"/>',
    "i-route": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               '<circle cx="6" cy="18" r="2.4"/><circle cx="18" cy="6" r="2.4"/>'
               '<path d="M8.4 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.6"/></g>',
    "i-lock": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
              '<rect x="4.5" y="10.5" width="15" height="10.5" rx="2.6"/><path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7"/></g>',
    "i-trash": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               '<path d="M4 6.5h16M9.5 6.5V4.8c0-.7.5-1.3 1.3-1.3h2.4c.8 0 1.3.6 1.3 1.3v1.7M6.2 6.5l.9 12.6c.1 1 .9 '
               '1.9 2 1.9h5.8c1.1 0 1.9-.8 2-1.9l.9-12.6M10 10.5v6.5M14 10.5v6.5"/></g>',
    "i-shield": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M12 2.8 4.5 5.6v5.8c0 4.8 3.2 8.4 7.5 9.8 4.3-1.4 7.5-5 7.5-9.8V5.6z"/>'
                '<path d="m8.8 12 2.3 2.3 4.2-4.6"/></g>',
    "i-ad": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            '<rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="m6.5 15.5 2.4-7 2.4 7M7.3 13.3h3.2M14 '
            '8.5v7h1.6a3.5 3.5 0 0 0 0-7z"/></g>',
    "i-chart": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
               '<path d="M3.5 20.5h17"/><path d="m4.5 15.5 5-5 3.5 3.5 6.5-7"/><path d="M15.5 7h4v4"/></g>',
    "i-card": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
              '<rect x="5" y="2.5" width="14" height="19" rx="2.6"/><path d="m5 16 4.2-4.2a1.6 1.6 0 0 1 2.3 0L19 19"/>'
              '<circle cx="14.5" cy="8" r="1.8"/></g>',
    "i-spark": '<path fill="currentColor" d="M12 2.5c.5 4.6 2.9 7 7.5 7.5v.1c-4.6.5-7 2.9-7.5 7.5h-.1c-.5-4.6-2.9-7-7.4-7.5v-.1'
               'c4.5-.5 6.9-2.9 7.4-7.5zM19 15.5c.2 1.9 1.1 2.8 3 3-1.9.2-2.8 1.1-3 3-.2-1.9-1.1-2.8-3-3 1.9-.2 2.8-1.1 3-3z"/>',
    "i-card-user": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                   '<rect x="2.5" y="4.5" width="19" height="15" rx="3"/><circle cx="12" cy="10.5" r="2.8"/>'
                   '<path d="M7 17.5a5.6 5.6 0 0 1 10 0"/></g>',
    "i-trophy": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M7.5 3.5h9v6a4.5 4.5 0 0 1-9 0z"/><path d="M7.5 5.5H4.5v1.5a3 3 0 0 0 3 3M16.5 5.5h3v1.5a3 3 0 0 1-3 3"/>'
                '<path d="M12 14v3.5M8.5 20.5h7M9.5 17.5h5"/></g>',
    "i-plus": '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 5v14M5 12h14"/>',
    "i-arrow": '<path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
               'd="M5 12h14m-5.5-5.5L19 12l-5.5 5.5"/>',
    "i-dumbbell": '<g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                  '<path d="M8 12h8M3.5 9.5v5M20.5 9.5v5"/><rect x="5.5" y="7" width="3" height="10" rx="1.2"/>'
                  '<rect x="15.5" y="7" width="3" height="10" rx="1.2"/></g>',
})


def laurel_branch():
    """One gold laurel branch (the left one; CSS mirrors it for the right), drawn here so the
    site needs no icon font. Leaves sit in pairs along an arc, smaller toward the tip."""
    leaf = "M0 0C4-3.8 4.2-11.2 0-16.5C-4.2-11.2-4-3.8 0 0Z"
    cx, cy, radius = 58, 50, 40
    start, end = 116, 232

    def point(degrees):
        rad = math.radians(degrees)
        return cx + radius * math.cos(rad), cy + radius * math.sin(rad)

    (x0, y0), (x1, y1) = point(start), point(end)
    parts = [f'<path d="M{x0:.1f} {y0:.1f}A{radius} {radius} 0 0 1 {x1:.1f} {y1:.1f}" fill="none" '
             'stroke="url(#laurel-gold)" stroke-width="2.4" stroke-linecap="round"/>']
    count = 6
    for i in range(count):
        t = i / (count - 1)
        degrees = start + 6 + t * (end - start - 22)
        x, y = point(degrees)
        heading = degrees + 90 + 180 - 90                  # leaf axis along the stem, toward the tip
        scale = 1.2 - 0.4 * t
        for side in (-34, 40):
            parts.append(f'<path d="{leaf}" transform="translate({x:.1f} {y:.1f}) rotate({heading + side:.1f}) '
                         f'scale({scale:.2f})"/>')
    parts.append(f'<path d="{leaf}" transform="translate({x1:.1f} {y1:.1f}) rotate(-6) scale(.78)"/>')
    return f'<g fill="url(#laurel-gold)">{"".join(parts)}</g>'


def sprite():
    with open(os.path.join(HERE, "fragments", "wordmark.svg")) as handle:
        wordmark = handle.read().strip()
    symbols = "\n".join(f'        <symbol id="{name}" viewBox="0 0 24 24">{body}</symbol>'
                        for name, body in ICONS.items())
    return (
        '    <svg class="sprite" aria-hidden="true" focusable="false">\n'
        '        <defs>\n'
        '        <linearGradient id="laurel-gold" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" stop-color="#FFE08A"/><stop offset=".55" stop-color="#F5B83D"/>'
        '<stop offset="1" stop-color="#D98A1C"/></linearGradient>\n'
        f'        {wordmark}\n{symbols}\n'
        f'        <symbol id="laurel" viewBox="0 0 64 96">{laurel_branch()}</symbol>\n'
        '        </defs>\n'
        '    </svg>\n'
    )


def brand():
    return (
        '<a class="brand" href="/" aria-label="Luris home">'
        '<img src="/img/app-icon-128.webp" width="36" height="36" alt="">'
        '<svg class="wordmark" viewBox="0 0 6679 1493" aria-hidden="true" focusable="false">'
        '<use href="#wordmark"/></svg></a>'
    )


def header(state, nav):
    current = ' aria-current="page"' if nav == "support" else ""
    campaign = "web-support" if nav == "support" else "web-header"
    if state["released"]:
        cta = (f'<a class="btn btn-primary btn-small" href="{esc(store_link(state, campaign))}" '
               'aria-label="Get Luris on the App Store">Get Luris</a>')
    else:
        cta = '<span class="soon-chip"><span class="pulse" aria-hidden="true"></span>Coming soon</span>'
    return (
        '    <header class="site-header">\n'
        '        <div class="container bar">\n'
        f'            {brand()}\n'
        '            <nav class="nav" aria-label="Primary">\n'
        '                <a class="nav-wide" href="/#features">Features</a>\n'
        '                <a class="nav-wide" href="/#privacy">Privacy</a>\n'
        '                <a class="nav-wide" href="/#pro">Luris Pro</a>\n'
        '                <a class="nav-wide" href="/#questions">Questions</a>\n'
        f'                <a href="/support.html"{current}>Support</a>\n'
        f'                {cta}\n'
        '            </nav>\n'
        '        </div>\n'
        '    </header>\n'
    )


def qr_tile(state):
    sys.path.insert(0, os.path.join(HERE, "vendor"))
    import segno  # noqa: E402  (vendored)

    code = segno.make(store_link(state, "web-qr"), error="m", micro=False)
    matrix = [list(row) for row in code.matrix]
    size = len(matrix)
    quiet = 4
    path = []
    for y, row in enumerate(matrix):
        x = 0
        while x < size:
            if row[x]:
                start = x
                while x < size and row[x]:
                    x += 1
                path.append(f"M{start + quiet} {y + quiet}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    box = size + 2 * quiet
    return (
        '<div class="qr-tile">'
        f'<svg class="qr" viewBox="0 0 {box} {box}" role="img" '
        'aria-label="QR code that opens Luris on the App Store" shape-rendering="crispEdges">'
        f'<rect width="{box}" height="{box}" fill="#fff"/>'
        f'<path fill="#000" d="{"".join(path)}"/></svg>'
        '<p>Scan with your iPhone camera</p></div>'
    )


def soon_pill():
    return ('<p class="soon"><svg aria-hidden="true" focusable="false"><use href="#i-clock"/></svg>'
            'Coming soon to the App Store</p>')


def store_state(state, campaign, indent, button):
    pad = " " * indent
    if not state["released"]:
        return (
            f'{pad}<div class="store-state">\n'
            f'{pad}    {soon_pill()}\n'
            f'{pad}    <p class="requirement">For iPhone with iOS 26.2 or later.</p>\n'
            f'{pad}</div>\n'
        )
    if button:
        link = (f'<a class="btn btn-primary btn-large" href="{esc(store_link(state, campaign))}">'
                'Get Luris on the App Store</a>')
    else:
        # Apple's official badge, unaltered, 50 px tall
        link = (f'<a class="store-badge" href="{esc(store_link(state, campaign))}">'
                '<img src="/img/badges/app-store-black-en-us.svg" width="150" height="50" '
                'alt="Download on the App Store"></a>')
    return (
        f'{pad}<div class="store-state">\n'
        f'{pad}    <div class="store-row">\n'
        f'{pad}        {link}\n'
        f'{pad}        {qr_tile(state)}\n'
        f'{pad}    </div>\n'
        f'{pad}    <p class="requirement">Requires iPhone with iOS 26.2 or later.</p>\n'
        f'{pad}</div>\n'
    )


def hero_cta(state):
    return store_state(state, "web-hero", 20, button=False)


def final_cta(state):
    return store_state(state, "web-final", 20, button=True)


def footer(state, trademarks, nav=None):
    store = ""
    if state["released"]:
        campaign = "web-support" if nav == "support" else "web-footer"
        store = f'\n                        <li><a href="{esc(store_link(state, campaign))}">App Store</a></li>'
    return (
        '    <footer class="site-footer">\n'
        '        <div class="container">\n'
        '            <div class="footer-grid">\n'
        '                <div class="footer-brand">\n'
        f'                    {brand()}\n'
        '                    <p>Steps, GPS walks, runs and rides, workouts and progress for iPhone, built on '
        'Apple Health.</p>\n'
        '                </div>\n'
        '                <nav class="footer-col" aria-labelledby="footer-luris">\n'
        '                    <h2 id="footer-luris">Luris</h2>\n'
        '                    <ul>\n'
        '                        <li><a href="/#features">Features</a></li>\n'
        '                        <li><a href="/#privacy">Privacy</a></li>\n'
        '                        <li><a href="/#pro">Luris Pro</a></li>\n'
        f'                        <li><a href="/#questions">Questions</a></li>{store}\n'
        '                    </ul>\n'
        '                </nav>\n'
        '                <nav class="footer-col" aria-labelledby="footer-legal">\n'
        '                    <h2 id="footer-legal">Legal</h2>\n'
        '                    <ul>\n'
        '                        <li><a href="/privacy.html">Privacy Policy</a></li>\n'
        '                        <li><a href="/terms.html">Terms of Use</a></li>\n'
        '                        <li><a href="/privacy.html#consumer-health-data">Consumer Health Data Privacy</a></li>\n'
        '                    </ul>\n'
        '                </nav>\n'
        '                <nav class="footer-col" aria-labelledby="footer-support">\n'
        '                    <h2 id="footer-support">Support</h2>\n'
        '                    <ul>\n'
        '                        <li><a href="/support.html">Help and questions</a></li>\n'
        '                        <li><a href="/support.html#delete">Delete your data</a></li>\n'
        f'                        <li><a href="mailto:{CONTACT}">{CONTACT}</a></li>\n'
        '                    </ul>\n'
        '                </nav>\n'
        '                <section class="footer-col footer-dev" aria-labelledby="footer-dev">\n'
        '                    <h2 id="footer-dev">Developer</h2>\n'
        f'                    <p>{DEVELOPER}<br>Independent developer, Romania<br>'
        f'<a href="mailto:{CONTACT}">{CONTACT}</a></p>\n'
        '                </section>\n'
        '            </div>\n'
        '            <p class="footer-health">Luris is not a medical device and does not give medical advice. '
        'Check with a doctor before starting a new exercise programme. '
        '<a href="/terms.html#health">Read the health disclaimer</a>.</p>\n'
        '            <div class="footer-bottom">\n'
        f'                <span>&copy; {YEAR} {DEVELOPER}</span>\n'
        f'                <span class="trademarks">{trademarks}</span>\n'
        '            </div>\n'
        '            <svg class="footer-mark" viewBox="0 0 6679 1493" aria-hidden="true" focusable="false">'
        '<use href="#wordmark"/></svg>\n'
        '        </div>\n'
        '    </footer>\n'
    )


def css_version():
    with open(os.path.join(SITE, "styles.css"), "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:10]


def head(state):
    banner = ""
    if state["released"]:
        # Smart App Banner. No app-argument: Luris opens no URLs.
        banner = f'    <meta name="apple-itunes-app" content="app-id={APP_ID}">\n'
    return (
        f'    <meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '    <meta name="referrer" content="strict-origin-when-cross-origin">\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '    <meta name="color-scheme" content="dark">\n'
        '    <meta name="theme-color" content="#050A16">\n'
        f'{banner}'
        '    <link rel="icon" href="/favicon.ico" sizes="48x48">\n'
        '    <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">\n'
        '    <link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
        f'    <link rel="stylesheet" href="/styles.css?v={css_version()}">\n'
    )


def meta(page):
    info = PAGES[page]
    lines = [f'    <title>{esc(info["title"])}</title>',
             f'    <meta name="description" content="{esc(info["description"])}">']
    if info.get("robots"):
        lines.append(f'    <meta name="robots" content="{info["robots"]}">')
    if info["path"]:
        url = ORIGIN + info["path"]
        image = ORIGIN + OG_IMAGE["path"]
        lines += [
            f'    <link rel="canonical" href="{url}">',
            f'    <meta property="og:type" content="{info["og_type"]}">',
            '    <meta property="og:site_name" content="Luris">',
            '    <meta property="og:locale" content="en_US">',
            f'    <meta property="og:url" content="{url}">',
            f'    <meta property="og:title" content="{esc(info["title"])}">',
            f'    <meta property="og:description" content="{esc(info["social"])}">',
            f'    <meta property="og:image" content="{image}">',
            '    <meta property="og:image:type" content="image/jpeg">',
            f'    <meta property="og:image:width" content="{OG_IMAGE["width"]}">',
            f'    <meta property="og:image:height" content="{OG_IMAGE["height"]}">',
            f'    <meta property="og:image:alt" content="{esc(OG_IMAGE["alt"])}">',
            '    <meta name="twitter:card" content="summary_large_image">',
            f'    <meta name="twitter:title" content="{esc(info["title"])}">',
            f'    <meta name="twitter:description" content="{esc(info["social"])}">',
            f'    <meta name="twitter:image" content="{image}">',
            f'    <meta name="twitter:image:alt" content="{esc(OG_IMAGE["alt"])}">',
        ]
    return "\n".join(lines) + "\n"


def jsonld(state):
    app = {
        "@type": "MobileApplication",
        "@id": f"{ORIGIN}/#app",
        "name": "Luris",
        "alternateName": APP_NAME,
        "url": f"{ORIGIN}/",
        "description": PAGES["index.html"]["description"],
        "applicationCategory": "HealthApplication",
        "applicationSubCategory": "Step counter and GPS walk, run and ride tracker",
        "operatingSystem": "iOS 26.2 or later",
        "availableOnDevice": "iPhone",
        "inLanguage": LANGUAGES,
        "featureList": [
            "Steps and activity from Apple Health",
            "GPS walk, run and bike ride tracking with a map",
            "Six-week workout plan",
            "873 exercises with images",
            "Weight and body fat trend charts and progress photos",
            "49 achievements",
            "Weekly Game Center steps leaderboard",
            "Share Studio cards",
            "Home Screen and Lock Screen widget",
            "Live Activity",
        ],
        "image": f"{ORIGIN}/img/app-icon-512.png",
        "screenshot": [f"{ORIGIN}/img/screens/home-screen.jpg", f"{ORIGIN}/img/screens/route-screen.jpg"],
        "author": {"@id": f"{ORIGIN}/#developer"},
        "publisher": {"@id": f"{ORIGIN}/#developer"},
    }
    if state["released"]:
        app["downloadUrl"] = f"https://apps.apple.com/app/id{APP_ID}"
        app["sameAs"] = [f"https://apps.apple.com/app/id{APP_ID}"]
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "@id": f"{ORIGIN}/#website", "url": f"{ORIGIN}/", "name": "Luris",
             "inLanguage": "en"},
            {"@type": "Person", "@id": f"{ORIGIN}/#developer", "name": DEVELOPER,
             "email": f"mailto:{CONTACT}"},
            app,
        ],
    }
    body = json.dumps(graph, indent=2, ensure_ascii=False)
    body = "\n".join("    " + line for line in body.splitlines())
    return f'    <script type="application/ld+json">\n{body}\n    </script>\n'


# ---------------------------------------------------------------- assembly

REGION = re.compile(r"(<!-- build:([a-z0-9-]+) -->\n)(.*?)(^[ \t]*<!-- /build:\2 -->)", re.S | re.M)


def visible_text(markup):
    markup = re.sub(r"<script\b.*?</script>", " ", markup, flags=re.S)
    markup = re.sub(r"<(style|title)\b.*?</\1>", " ", markup, flags=re.S)
    alts = " ".join(re.findall(r'\balt="([^"]*)"', markup))
    labels = " ".join(re.findall(r'\baria-label="([^"]*)"', markup))
    body = markup.split("<body", 1)[-1]
    text = re.sub(r"<[^>]+>", " ", body)
    return html.unescape(f"{text} {alts} {labels}")


def trademark_credit(markup):
    text = visible_text(markup)
    registered = [m for m in REGISTERED_MARKS if re.search(MARK_PATTERNS[m], text)]
    unregistered = [m for m in UNREGISTERED_MARKS if re.search(MARK_PATTERNS[m], text)]

    def join(items):
        return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]

    parts = []
    if registered:
        verb = "is a trademark" if len(registered) == 1 else "are trademarks"
        parts.append(f"{join(registered)} {verb} of Apple Inc., registered in the U.S. and other countries.")
    if unregistered:
        verb = "is a trademark" if len(unregistered) == 1 else "are trademarks"
        parts.append(f"{join(unregistered)} {verb} of Apple Inc.")
    return " ".join(parts)


def render(page, markup, state):
    info = PAGES[page]
    home = page == "index.html"
    fragments = {
        "head": head(state),
        "meta": meta(page),
        "sprite": sprite(),
        "header": header(state, info["nav"]),
        "footer": footer(state, "TRADEMARKS", info["nav"]),
    }
    if home:
        fragments.update({"hero-cta": hero_cta(state), "final-cta": final_cta(state), "jsonld": jsonld(state)})

    seen = set()

    def replace(match):
        name = match.group(2)
        if name not in fragments:
            sys.exit(f"{page}: unknown region {name!r}")
        seen.add(name)
        return match.group(1) + fragments[name] + match.group(4)

    out = REGION.sub(replace, markup)
    missing = set(fragments) - seen
    if missing:
        sys.exit(f"{page}: missing region(s) {', '.join(sorted(missing))}")
    # the credit names the marks the finished page uses, the credit line itself excluded
    return out.replace("TRADEMARKS", esc(trademark_credit(out.replace("TRADEMARKS", ""))))


def git_lastmod(page):
    path = os.path.join(SITE, page)
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", page], cwd=SITE).returncode != 0
    if changed:
        return datetime.date.today().isoformat()
    stamp = subprocess.run(["git", "log", "-1", "--format=%cs", "--", page], cwd=SITE,
                           capture_output=True, text=True).stdout.strip()
    return stamp or datetime.date.fromtimestamp(os.path.getmtime(path)).isoformat()


def write_sitemap():
    rows = []
    for page, info in PAGES.items():
        if info["path"]:
            rows.append(f"    <url><loc>{ORIGIN}{info['path']}</loc><lastmod>{git_lastmod(page)}</lastmod></url>")
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n")
    with open(os.path.join(SITE, "sitemap.xml"), "w") as handle:
        handle.write(body)


def build():
    state = load_state()
    for page in PAGES:
        path = os.path.join(SITE, page)
        with open(path, encoding="utf-8") as handle:
            markup = handle.read()
        out = render(page, markup, state)
        if out != markup:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(out)
            print(f"updated {page}")
    write_sitemap()
    print("released" if state["released"] else "pre-release: Coming soon, no App Store links")


def release(argv):
    state = load_state()
    token = ""
    if "--pt" in argv:
        token = argv[argv.index("--pt") + 1]
        if not re.fullmatch(r"\d{4,12}", token):
            sys.exit(f"--pt expects the numeric provider token from App Store Connect, got {token!r}")
    state.update({"released": True, "provider_token": token})
    with open(STATE_FILE, "w") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
    build()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "release":
        release(sys.argv[2:])
    elif len(sys.argv) > 1:
        sys.exit(__doc__)
    else:
        build()
