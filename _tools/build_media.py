"""Build every image the site uses from the app's own art (run from anywhere).

    python3 _tools/build_media.py            phones, photos, JSON-LD screenshots
    python3 _tools/build_media.py phones [name ...]   only the framed phones
    python3 _tools/build_media.py photos     only the photography

Sources (all owned by the app, see Luris/.launch-work/ASSET-PROVENANCE.md):
  - real app screens, English, from Luris/.launch-work/shots/captures/en/
  - the real Apple iPhone 16 Pro Max frame from Luris/.launch-work/shots/frames/
  - the athlete and landscape photography in Luris/Luris/Assets.xcassets/

Outputs, all under img/:
  phone/<name>-<w>.avif|webp   transparent framed phones at 3 widths
  photo/<name>-<w>.avif|webp   graded photography at 1 or 2 widths
  screens/home-screen.jpg, route-screen.jpg   plain captures the JSON-LD names

Needs Pillow with AVIF and WebP (Pillow 11 has both).
"""
import os
import sys

from PIL import Image, ImageDraw, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
APP = os.path.expanduser("~/Developer/Luris")
CAPTURES = os.path.join(APP, ".launch-work/shots/captures/en")
FRAME = os.path.join(APP, ".launch-work/shots/frames/Apple iPhone 16 Pro Max Black Titanium.png")
ASSETS = os.path.join(APP, "Luris/Assets.xcassets")

SCREEN_ORIGIN = (75, 66)       # where the 1320x2868 screen sits inside the 1470x3000 frame
SCREEN_SIZE = (1320, 2868)
SCREEN_RADIUS = 170
DATE_BAND = (205, 340)         # rows of the Lock Screen date line (see shots/v2/build.py)

PHONES = {
    "home": "01", "run": "02", "lock": "03", "plan": "04",
    "exercise": "05", "progress": "06", "leaderboard": "07", "share": "08",
    # captured the day before (same build, English): second phones for the hero and chapters
    "workout": "workout", "library": "library", "body": "progress-body",
}
PHONE_WIDTHS = (400, 600, 900)

# name: (asset path, widths, grade strength 0..1, crop box as fractions or None)
PHOTOS = {
    "hero": ("homeHero.imageset/homeHero.jpg", (720, 1100), 0.0, None),
    "steps": ("planCurrentPlan.imageset/planCurrentPlan.jpg", (700, 1100), 0.10, None),
    "ride": ("shareBg11.imageset/shareBg11.jpg", (700, 940), 0.30, (0, 0.18, 1, 0.92)),
    "city": ("shareBg09.imageset/shareBg09.jpg", (700, 940), 0.30, (0, 0.12, 1, 0.88)),
    "plan": ("todaysPlanThumb.imageset/todaysPlanThumb.jpg", (800, 1600), 0.10, None),
    "gym": ("recommendedWorkout.imageset/recommendedWorkout.jpg", (700, 1100), 0.10, None),
    "summit": ("journeyMountain.imageset/journeyMountain.jpg", (800, 1500), 0.05, None),
    "ranks": ("leaderboardHero.imageset/leaderboardHero.jpg", (700, 1250), 0.15, None),
    "sunset": ("shareBg12.imageset/shareBg12.jpg", (700, 940), 0.30, (0, 0.1, 1, 0.9)),
    "ridge": ("shareBg04.imageset/shareBg04.jpg", (700, 940), 0.30, (0, 0.05, 1, 0.8)),
    "horizon": ("weeksLeftFooter.imageset/weeksLeftFooter.jpg", (900, 1900), 0.05, None),
}

NAVY = (6, 12, 28)


def rounded_mask(size, radius, scale=4):
    mask = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] * scale - 1, size[1] * scale - 1),
                                           radius * scale, fill=255)
    return mask.resize(size, Image.LANCZOS)


def capture(code):
    shot = Image.open(os.path.join(CAPTURES, f"{code}.png")).convert("RGB")
    if code == "03":
        # the simulator dates the Lock Screen Jan 1; lift the real date line from 03-real.png
        real = os.path.join(CAPTURES, "03-real.png")
        if os.path.exists(real):
            y0, y1 = DATE_BAND
            shot.paste(Image.open(real).convert("RGB").crop((0, y0, SCREEN_SIZE[0], y1)), (0, y0))
    return shot.resize(SCREEN_SIZE, Image.LANCZOS)


def framed(code):
    frame = Image.open(FRAME).convert("RGBA")
    shot = capture(code).convert("RGBA")
    shot.putalpha(rounded_mask(shot.size, SCREEN_RADIUS))
    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    canvas.paste(shot, SCREEN_ORIGIN, shot)
    canvas.alpha_composite(frame)
    return canvas


def save_pair(img, base, avif_q, webp_q):
    img.save(base + ".avif", "AVIF", quality=avif_q, speed=4)
    img.save(base + ".webp", "WEBP", quality=webp_q, method=6)


def phones(only=None):
    out = os.path.join(SITE, "img/phone")
    os.makedirs(out, exist_ok=True)
    for name, code in PHONES.items():
        if only and name not in only:
            continue
        big = framed(code)
        for width in PHONE_WIDTHS:
            height = round(big.height * width / big.width)
            save_pair(big.resize((width, height), Image.LANCZOS), os.path.join(out, f"{name}-{width}"), 62, 80)
        print("phone", name)
    if only:
        return
    screens = os.path.join(SITE, "img/screens")
    os.makedirs(screens, exist_ok=True)
    for name, code in (("home-screen", "01"), ("route-screen", "02")):
        capture(code).resize((660, 1434), Image.LANCZOS).save(os.path.join(screens, f"{name}.jpg"), "JPEG",
                                                               quality=82, optimize=True, progressive=True)


def grade(img, strength):
    """Pull the photo toward the site's navy: lower exposure, a cool cast in the shadows,
    the warm highlights kept. strength 0 leaves it alone."""
    if strength <= 0:
        return img
    img = ImageEnhance.Brightness(img).enhance(1 - 0.45 * strength)
    img = ImageEnhance.Color(img).enhance(1 - 0.15 * strength)
    navy = Image.new("RGB", img.size, NAVY)
    luma = img.convert("L").point(lambda v: int(255 - v))          # dark areas take more navy
    luma = luma.point(lambda v: int(v * 0.55 * strength))
    return Image.composite(navy, img, luma)


def photos():
    out = os.path.join(SITE, "img/photo")
    os.makedirs(out, exist_ok=True)
    for name, (asset, widths, strength, crop) in PHOTOS.items():
        img = Image.open(os.path.join(ASSETS, asset)).convert("RGB")
        if crop:
            w, h = img.size
            img = img.crop((round(crop[0] * w), round(crop[1] * h), round(crop[2] * w), round(crop[3] * h)))
        img = grade(img, strength)
        for width in widths:
            width = min(width, img.width)
            height = round(img.height * width / img.width)
            save_pair(img.resize((width, height), Image.LANCZOS), os.path.join(out, f"{name}-{width}"), 52, 74)
        print("photo", name, [min(w, img.width) for w in widths])


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "phones"):
        phones(sys.argv[2:] or None)
    if what in ("all", "photos"):
        photos()
