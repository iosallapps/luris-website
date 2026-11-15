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

Regions: head, meta, sprite, header, footer (every page); jsonld (every indexable page:
the app, site and FAQ graph on the home pages, a BreadcrumbList on the others); hero-cta,
final-cta (home pages only). Romanian pages live in ro/ and are
edited by hand like the English ones; header, footer, meta, hreflang pairs and JSON-LD come
from the T table and PAGES here. It also writes sitemap.xml with hreflang alternates, each
page's lastmod taken from git (today for a page that differs from the last commit).

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
DEVELOPER = "Visto Apps, the brand of Darius Cirjan"
DEVELOPER_ORG = {"@type": "Organization", "@id": ORIGIN + "/#developer", "name": "Visto Apps",
                 "url": "https://vistoapps.com", "founder": {"@type": "Person", "name": "Darius Cirjan"}}
MORE_APPS = "https://vistoapps.com/apps.html"
YEAR = 2026
OG_IMAGE = {"path": "/og-image.jpg", "width": 1200, "height": 630,
            "alt": "Luris on two iPhones, the Home tab with today's steps ring and a run drawn on the "
                   "map, over a runner at dusk, beside the words Everything you need to move more."}

LANGUAGES = ["en", "ar", "bn", "ca", "zh-Hans", "zh-Hant", "hr", "cs", "da", "nl", "fi", "fr", "de", "el", "gu", "he", "hi", "hu", "id", "it", "ja", "kn", "ko", "ms", "ml", "mr", "nb", "or", "pl", "pt-BR", "pt-PT", "pa", "ro", "ru", "sk", "sl", "es", "sv", "ta", "te", "th", "tr", "uk", "ur", "vi"]

PAGES = {
    "index.html": {
        "path": "/", "nav": None, "og_type": "website", "lang": "en", "alt": "ro/index.html",
        "title": f"{APP_NAME} for iPhone",
        "description": "Luris is a free step counter and fitness tracker for iPhone. Steps from Apple Health, "
                       "GPS maps of walks, runs and rides, and a six-week plan.",
        "social": "Steps, GPS walks, runs and rides, a six-week plan and progress you can see, built on "
                  "Apple Health.",
        "crumb": None,
    },
    "support.html": {
        "path": "/support.html", "nav": "support", "og_type": "website", "lang": "en", "alt": "ro/support.html",
        "title": "Luris Support: Help and Questions",
        "description": "Help for Luris: contact the developer and get answers on Apple Health, GPS walks, "
                       "runs and rides, the leaderboard, units and deleting your data.",
        "social": "Contact the developer and find answers about Apple Health, GPS walks, runs and rides, "
                  "the leaderboard and your data.",
        "crumb": "Support",
    },
    "privacy.html": {
        "path": "/privacy.html", "nav": None, "og_type": "article", "lang": "en", "alt": "ro/privacy.html",
        "title": "Luris Privacy Policy",
        "description": "How Luris handles your data: health data stays on your iPhone. Google ads, "
                       "analytics and crash reports, RevenueCat purchases, and what goes to Apple.",
        "social": "Health data stays on your iPhone. What goes to Apple, and nothing to the developer.",
        "crumb": "Privacy Policy",
    },
    "terms.html": {
        "path": "/terms.html", "nav": None, "og_type": "article", "lang": "en", "alt": "ro/terms.html",
        "title": "Luris Terms of Use",
        "description": "The terms for using Luris, the fitness tracker for iPhone: your licence, the health "
                       "disclaimer, safety on walks, runs and rides, and leaderboard rules.",
        "social": "Your licence, the health and fitness disclaimer, safety on walks, runs and rides and "
                  "the leaderboard rules.",
        "crumb": "Terms of Use",
    },
    "ro/index.html": {
        "path": "/ro/", "nav": None, "og_type": "website", "lang": "ro", "alt": "index.html",
        "title": "Luris: Contor de pași și activitate pe iPhone",
        "description": "Luris, contor de pași și tracker fitness gratuit pentru iPhone. Pași din Apple Health, "
                       "trasee GPS pentru mers, alergare și ciclism, plan de șase săptămâni.",
        "social": "Pași, trasee GPS pentru mers, alergare și ciclism, un plan de șase săptămâni și progres "
                  "pe care îl vezi, construit pe Apple Health.",
        "crumb": None,
    },
    "ro/support.html": {
        "path": "/ro/support.html", "nav": "support", "og_type": "website", "lang": "ro", "alt": "support.html",
        "title": "Asistență Luris: ajutor și întrebări",
        "description": "Ajutor pentru Luris: contactează dezvoltatorul și găsește răspunsuri despre Apple "
                       "Health, GPS, clasament, unități și ștergerea datelor.",
        "social": "Contactează dezvoltatorul și găsește răspunsuri despre Apple Health, mers, alergare și "
                  "ciclism cu GPS, clasament și datele tale.",
        "crumb": "Asistență",
    },
    "ro/privacy.html": {
        "path": "/ro/privacy.html", "nav": None, "og_type": "article", "lang": "ro", "alt": "privacy.html",
        "title": "Politica de confidențialitate Luris",
        "description": "Cum tratează Luris datele tale: datele de sănătate rămân pe iPhone. Reclame, analize "
                       "și rapoarte de erori Google, achiziții RevenueCat, ce ajunge la Apple.",
        "social": "Datele de sănătate rămân pe iPhone. Ce ajunge la Apple și nimic către dezvoltator.",
        "crumb": "Politica de confidențialitate",
    },
    "ro/terms.html": {
        "path": "/ro/terms.html", "nav": None, "og_type": "article", "lang": "ro", "alt": "terms.html",
        "title": "Termeni de utilizare Luris",
        "description": "Termenii de utilizare Luris, trackerul de fitness pentru iPhone: licența ta, "
                       "avertismentul privind sănătatea, siguranța la mers, alergare și ciclism, clasament.",
        "social": "Licența ta, avertismentul privind sănătatea și fitnessul, siguranța la mers, alergare și "
                  "ciclism și regulile clasamentului.",
        "crumb": "Termeni de utilizare",
    },
    "404.html": {
        "path": None, "nav": None, "og_type": None, "robots": "noindex", "lang": "en", "alt": None,
        "title": "Page not found | Luris",
        "description": "This page does not exist or has moved.",
        "crumb": None,
    },
}

# Chrome text per language: header, footer, store block, trademark credit.
T = {
    "en": {
        "prefix": "", "home_label": "Luris home", "features": "Features", "privacy": "Privacy", "questions": "Questions",
        "support": "Support", "get": "Get Luris", "get_aria": "Get Luris on the App Store",
        "lang_name": "Română", "lang_code": "ro", "lang_aria": "Romanian",
        "soon": "Coming soon to the App Store", "req_soon": "For iPhone with iOS 18.0 or later.",
        "req": "Requires iPhone with iOS 18.0 or later.", "get_big": "Get Luris on the App Store",
        "badge_alt": "Download on the App Store", "qr_aria": "QR code that opens Luris on the App Store",
        "qr_note": "Scan with your iPhone camera",
        "footer_blurb": "Steps, GPS walks, runs and rides, workouts and progress for iPhone, built on Apple Health.",
        "legal": "Legal", "privacy_policy": "Privacy Policy", "terms": "Terms of Use",
        "chd": "Consumer Health Data Privacy", "help": "Help and questions", "delete": "Delete your data",
        "developer": "Developer", "dev_line": "Independent developer, Romania",
        "health_note": "Luris is not a medical device and does not give medical advice. Check with a doctor "
                       "before starting a new exercise programme.",
        "health_link": "Read the health disclaimer", "made_by": "Made by Visto Apps",
        "more_apps": "More apps by Visto Apps", "lang_label": "Language", "brand": DEVELOPER,
        "joiner": " and ", "is_tm": "is a trademark", "are_tm": "are trademarks",
        "tm_reg": "of Apple Inc., registered in the U.S. and other countries.", "tm_plain": "of Apple Inc.",
        "locale": "en_US", "site_inLanguage": "en",
    },
    "ro": {
        "prefix": "/ro", "home_label": "Luris, acasă", "features": "Funcții", "privacy": "Confidențialitate",
        "questions": "Întrebări", "support": "Asistență", "get": "Descarcă Luris",
        "get_aria": "Descarcă Luris din App Store",
        "lang_name": "English", "lang_code": "en", "lang_aria": "English",
        "soon": "În curând în App Store", "req_soon": "Pentru iPhone cu iOS 18.0 sau mai nou.",
        "req": "Necesită iPhone cu iOS 18.0 sau mai nou.", "get_big": "Descarcă Luris din App Store",
        "badge_alt": "Descarcă din App Store", "qr_aria": "Cod QR care deschide Luris în App Store",
        "qr_note": "Scanează cu camera iPhone-ului",
        "footer_blurb": "Pași, mersuri, alergări și ture cu bicicleta cu GPS, antrenamente și progres pentru "
                        "iPhone, construit pe Apple Health.",
        "legal": "Juridic", "privacy_policy": "Politica de confidențialitate", "terms": "Termeni de utilizare",
        "chd": "Datele de sănătate ale consumatorilor", "help": "Ajutor și întrebări",
        "delete": "Șterge-ți datele",
        "developer": "Dezvoltator", "dev_line": "Dezvoltator independent, România",
        "health_note": "Luris nu este un dispozitiv medical și nu oferă sfaturi medicale. Consultă un medic "
                       "înainte de a începe un nou program de exerciții.",
        "health_link": "Citește avertismentul privind sănătatea", "made_by": "Creat de Visto Apps",
        "more_apps": "Mai multe aplicații de la Visto Apps", "lang_label": "Limba",
        "brand": "Visto Apps, marca lui Darius Cirjan",
        "joiner": " și ", "is_tm": "este o marcă comercială", "are_tm": "sunt mărci comerciale",
        "tm_reg": "ale Apple Inc., înregistrate în S.U.A. și în alte țări.", "tm_plain": "a Apple Inc.",
        "locale": "ro_RO", "site_inLanguage": "ro",
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


def brand(lang="en"):
    t = T[lang]
    return (
        f'<a class="brand" href="{t["prefix"]}/" aria-label="{esc(t["home_label"])}">'
        '<img src="/img/app-icon-128.webp" width="36" height="36" alt="">'
        '<svg class="wordmark" viewBox="0 0 6679 1493" aria-hidden="true" focusable="false">'
        '<use href="#wordmark"/></svg></a>'
    )


def lang_link(page, cls="lang-switch"):
    """Plain link to the same page in the other language (no JavaScript)."""
    info = PAGES[page]
    other = PAGES[info["alt"]]
    t = T[info["lang"]]
    cls_attr = f' class="{cls}"' if cls else ""
    return (f'<a{cls_attr} href="{other["path"]}" hreflang="{t["lang_code"]}" lang="{t["lang_code"]}" '
            f'aria-label="{esc(t["lang_aria"])}">{t["lang_name"]}</a>')


def header(state, page):
    info = PAGES[page]
    lang, nav = info["lang"], info["nav"]
    t = T[lang]
    p = t["prefix"]
    current = ' aria-current="page"' if nav == "support" else ""
    campaign = "web-support" if nav == "support" else "web-header"
    if state["released"]:
        cta = (f'<a class="btn btn-primary btn-small" href="{esc(store_link(state, campaign))}" '
               f'aria-label="{esc(t["get_aria"])}">{t["get"]}</a>')
    else:
        cta = '<span class="soon-chip"><span class="pulse" aria-hidden="true"></span>Coming soon</span>'
    switch = f'                {lang_link(page)}\n' if info["alt"] else ""
    return (
        '    <header class="site-header">\n'
        '        <div class="container bar">\n'
        f'            {brand(lang)}\n'
        '            <nav class="nav" aria-label="Primary">\n'
        f'                <a class="nav-wide" href="{p}/#features">{t["features"]}</a>\n'
        f'                <a class="nav-wide" href="{p}/#privacy">{t["privacy"]}</a>\n'
        f'                <a class="nav-wide" href="{p}/#pro">Luris Pro</a>\n'
        f'                <a class="nav-wide" href="{p}/#questions">{t["questions"]}</a>\n'
        f'                <a href="{p}/support.html"{current}>{t["support"]}</a>\n'
        f'{switch}'
        f'                {cta}\n'
        '            </nav>\n'
        '        </div>\n'
        '    </header>\n'
    )


def qr_tile(state, lang="en"):
    t = T[lang]
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
        f'aria-label="{esc(t["qr_aria"])}" shape-rendering="crispEdges">'
        f'<rect width="{box}" height="{box}" fill="#fff"/>'
        f'<path fill="#000" d="{"".join(path)}"/></svg>'
        f'<p>{t["qr_note"]}</p></div>'
    )


def store_state(state, campaign, indent, button, lang="en"):
    t = T[lang]
    pad = " " * indent
    if not state["released"]:
        soon = ('<p class="soon"><svg aria-hidden="true" focusable="false"><use href="#i-clock"/></svg>'
                f'{t["soon"]}</p>')
        return (
            f'{pad}<div class="store-state">\n'
            f'{pad}    {soon}\n'
            f'{pad}    <p class="requirement">{t["req_soon"]}</p>\n'
            f'{pad}</div>\n'
        )
    if button:
        link = (f'<a class="btn btn-primary btn-large" href="{esc(store_link(state, campaign))}">'
                f'{t["get_big"]}</a>')
    else:
        # Apple's official badge, unaltered, 50 px tall
        link = (f'<a class="store-badge" href="{esc(store_link(state, campaign))}">'
                '<img src="/img/badges/app-store-black-en-us.svg" width="150" height="50" '
                f'alt="{esc(t["badge_alt"])}"></a>')
    return (
        f'{pad}<div class="store-state">\n'
        f'{pad}    <div class="store-row">\n'
        f'{pad}        {link}\n'
        f'{pad}        {qr_tile(state, lang)}\n'
        f'{pad}    </div>\n'
        f'{pad}    <p class="requirement">{t["req"]}</p>\n'
        f'{pad}</div>\n'
    )


def hero_cta(state, lang="en"):
    return store_state(state, "web-hero", 20, button=False, lang=lang)


def final_cta(state, lang="en"):
    return store_state(state, "web-final", 20, button=True, lang=lang)


def footer(state, trademarks, page):
    info = PAGES[page]
    lang, nav = info["lang"], info["nav"]
    t = T[lang]
    p = t["prefix"]
    store = ""
    if state["released"]:
        campaign = "web-support" if nav == "support" else "web-footer"
        store = f'\n                        <li><a href="{esc(store_link(state, campaign))}">App Store</a></li>'
    switch = f'\n                        <li>{lang_link(page, "")}</li>' if info["alt"] else ""
    return (
        '    <footer class="site-footer">\n'
        '        <div class="container">\n'
        '            <div class="footer-grid">\n'
        '                <div class="footer-brand">\n'
        f'                    {brand(lang)}\n'
        f'                    <p>{t["footer_blurb"]}</p>\n'
        '                </div>\n'
        '                <nav class="footer-col" aria-labelledby="footer-luris">\n'
        '                    <h2 id="footer-luris">Luris</h2>\n'
        '                    <ul>\n'
        f'                        <li><a href="{p}/#features">{t["features"]}</a></li>\n'
        f'                        <li><a href="{p}/#privacy">{t["privacy"]}</a></li>\n'
        f'                        <li><a href="{p}/#pro">Luris Pro</a></li>\n'
        f'                        <li><a href="{p}/#questions">{t["questions"]}</a></li>{store}{switch}\n'
        '                    </ul>\n'
        '                </nav>\n'
        '                <nav class="footer-col" aria-labelledby="footer-legal">\n'
        f'                    <h2 id="footer-legal">{t["legal"]}</h2>\n'
        '                    <ul>\n'
        f'                        <li><a href="{p}/privacy.html">{t["privacy_policy"]}</a></li>\n'
        f'                        <li><a href="{p}/terms.html">{t["terms"]}</a></li>\n'
        f'                        <li><a href="{p}/privacy.html#consumer-health-data">{t["chd"]}</a></li>\n'
        '                    </ul>\n'
        '                </nav>\n'
        '                <nav class="footer-col" aria-labelledby="footer-support">\n'
        f'                    <h2 id="footer-support">{t["support"]}</h2>\n'
        '                    <ul>\n'
        f'                        <li><a href="{p}/support.html">{t["help"]}</a></li>\n'
        f'                        <li><a href="{p}/support.html#delete">{t["delete"]}</a></li>\n'
        f'                        <li><a href="mailto:{CONTACT}">{CONTACT}</a></li>\n'
        '                    </ul>\n'
        '                </nav>\n'
        '                <section class="footer-col footer-dev" aria-labelledby="footer-dev">\n'
        f'                    <h2 id="footer-dev">{t["developer"]}</h2>\n'
        f'                    <p>{t["brand"]}<br>{t["dev_line"]}<br>'
        f'<a href="mailto:{CONTACT}">{CONTACT}</a><br>'
        f'<a href="{MORE_APPS}" rel="noopener">{t["more_apps"]}</a></p>\n'
        '                </section>\n'
        '            </div>\n'
        f'            <p class="footer-health">{t["health_note"]} '
        f'<a href="{p}/terms.html#accuracy">{t["health_link"]}</a>.</p>\n'
        '            <div class="footer-bottom">\n'
        f'                <span>&copy; {YEAR} {t["brand"]}. <a href="https://vistoapps.com" rel="noopener">{t["made_by"]}</a></span>\n'
        f'                <span class="trademarks">{trademarks}</span>\n'
        '            </div>\n'
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
        '    <meta name="theme-color" content="#040b1a">\n'
        f'{banner}'
        '    <link rel="icon" href="/favicon.ico" sizes="48x48">\n'
        '    <link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">\n'
        '    <link rel="apple-touch-icon" href="/apple-touch-icon.png">\n'
        '    <link rel="preload" href="/assets/fonts/inter.woff2" as="font" type="font/woff2" crossorigin>\n'
        '    <link rel="preload" href="/assets/fonts/instrument-serif.woff2" as="font" type="font/woff2" crossorigin>\n'
        f'    <link rel="stylesheet" href="/styles.css?v={css_version()}">\n'
    )


def page_url(page):
    return ORIGIN + PAGES[page]["path"]


def meta(page):
    info = PAGES[page]
    t = T[info["lang"]]
    lines = [f'    <title>{esc(info["title"])}</title>',
             f'    <meta name="description" content="{esc(info["description"])}">']
    if info.get("robots"):
        lines.append(f'    <meta name="robots" content="{info["robots"]}">')
    if info["path"]:
        url = page_url(page)
        image = ORIGIN + OG_IMAGE["path"]
        lines.append(f'    <link rel="canonical" href="{url}">')
        if info["alt"]:
            en = page if info["lang"] == "en" else info["alt"]
            ro = info["alt"] if info["lang"] == "en" else page
            lines += [
                f'    <link rel="alternate" hreflang="en" href="{page_url(en)}">',
                f'    <link rel="alternate" hreflang="ro" href="{page_url(ro)}">',
                f'    <link rel="alternate" hreflang="x-default" href="{page_url(en)}">',
            ]
        alt_locale = T["en" if info["lang"] == "ro" else "ro"]["locale"]
        lines += [
            f'    <meta property="og:type" content="{info["og_type"]}">',
            '    <meta property="og:site_name" content="Luris">',
            f'    <meta property="og:locale" content="{t["locale"]}">',
            f'    <meta property="og:locale:alternate" content="{alt_locale}">',
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


FEATURES = {
    "en": [
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
    "ro": [
        "Pași și activitate din Apple Health",
        "Urmărire GPS pentru mers, alergare și ciclism, cu hartă",
        "Plan de antrenament de șase săptămâni",
        "873 de exerciții cu imagini",
        "Grafice de evoluție pentru greutate și grăsime corporală și poze de progres",
        "49 de realizări",
        "Clasament săptămânal de pași în Game Center",
        "Carduri Share Studio",
        "Widget pe ecranul de start și pe ecranul de blocare",
        "Live Activity",
    ],
}
CATEGORY = {"en": "Step counter and GPS walk, run and ride tracker",
            "ro": "Contor de pași și tracker GPS pentru mers, alergare și ciclism"}
CRUMB_HOME = {"en": "Luris", "ro": "Luris"}


def faq_entities(markup):
    """FAQPage questions, taken from the visible FAQ of the page itself."""
    items = []
    for block in re.findall(r'<details class="qa-item">(.*?)</details>', markup, re.S):
        question = re.search(r"<summary><span>(.*?)</span>", block, re.S)
        answer = re.search(r'<div class="qa-body"><p>(.*?)</p></div>', block, re.S)
        if not (question and answer):
            continue
        text = html.unescape(re.sub(r"<[^>]+>", "", answer.group(1))).strip()
        items.append({"@type": "Question", "name": html.unescape(question.group(1)).strip(),
                      "acceptedAnswer": {"@type": "Answer", "text": text}})
    return items


def jsonld(state, page, markup):
    info = PAGES[page]
    lang = info["lang"]
    t = T[lang]
    home_url = f"{ORIGIN}{t['prefix']}/"
    if info["crumb"]:
        graph = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": CRUMB_HOME[lang], "item": home_url},
                {"@type": "ListItem", "position": 2, "name": info["crumb"], "item": page_url(page)},
            ],
        }
    else:
        app = {
            "@type": "MobileApplication",
            "@id": f"{home_url}#app",
            "name": "Luris",
            "alternateName": APP_NAME,
            "url": home_url,
            "description": info["description"],
            "applicationCategory": "HealthApplication",
            "applicationSubCategory": CATEGORY[lang],
            "operatingSystem": "iOS 18.0 or later",
            "availableOnDevice": "iPhone",
            "inLanguage": LANGUAGES,
            "featureList": FEATURES[lang],
            "image": f"{ORIGIN}/img/app-icon-512.png",
            "screenshot": [f"{ORIGIN}/img/screens/home-screen.jpg", f"{ORIGIN}/img/screens/route-screen.jpg"],
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "author": {"@id": f"{ORIGIN}/#developer"},
            "publisher": {"@id": f"{ORIGIN}/#developer"},
        }
        if state["released"]:
            app["downloadUrl"] = f"https://apps.apple.com/app/id{APP_ID}"
            app["installUrl"] = f"https://apps.apple.com/app/id{APP_ID}"
            app["sameAs"] = [f"https://apps.apple.com/app/id{APP_ID}"]
        faq = faq_entities(markup)
        graph = {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebSite", "@id": f"{home_url}#website", "url": home_url, "name": "Luris",
                 "inLanguage": t["site_inLanguage"], "publisher": {"@id": f"{ORIGIN}/#developer"}},
                dict(DEVELOPER_ORG, description=DEVELOPER, email=CONTACT),
                app,
            ] + ([{"@type": "FAQPage", "@id": f"{home_url}#faq", "inLanguage": t["site_inLanguage"],
                   "mainEntity": faq}] if faq else []),
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


def trademark_credit(markup, lang="en"):
    t = T[lang]
    text = visible_text(markup)
    registered = [m for m in REGISTERED_MARKS if re.search(MARK_PATTERNS[m], text)]
    unregistered = [m for m in UNREGISTERED_MARKS if re.search(MARK_PATTERNS[m], text)]

    def join(items):
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + t["joiner"] + items[-1]

    parts = []
    if registered:
        verb = t["is_tm"] if len(registered) == 1 else t["are_tm"]
        parts.append(f"{join(registered)} {verb} {t['tm_reg']}")
    if unregistered:
        verb = t["is_tm"] if len(unregistered) == 1 else t["are_tm"]
        parts.append(f"{join(unregistered)} {verb} {t['tm_plain']}")
    return " ".join(parts)


def render(page, markup, state):
    info = PAGES[page]
    lang = info["lang"]
    home = info["path"] in ("/", "/ro/")
    fragments = {
        "head": head(state),
        "meta": meta(page),
        "sprite": sprite(),
        "header": header(state, page),
        "footer": footer(state, "TRADEMARKS", page),
    }
    if home:
        fragments.update({"hero-cta": hero_cta(state, lang), "final-cta": final_cta(state, lang)})
    if info["path"]:
        fragments["jsonld"] = jsonld(state, page, markup)

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
    return out.replace("TRADEMARKS", esc(trademark_credit(out.replace("TRADEMARKS", ""), lang)))


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
        if not info["path"]:
            continue
        links = ""
        if info["alt"]:
            en = page if info["lang"] == "en" else info["alt"]
            ro = info["alt"] if info["lang"] == "en" else page
            for code, target in (("en", en), ("ro", ro), ("x-default", en)):
                links += (f'\n        <xhtml:link rel="alternate" hreflang="{code}" href="{page_url(target)}"/>')
        rows.append(f"    <url>\n        <loc>{page_url(page)}</loc>\n        <lastmod>{git_lastmod(page)}</lastmod>"
                    f"{links}\n    </url>")
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">\n' + "\n".join(rows) + "\n</urlset>\n")
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
