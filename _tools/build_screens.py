"""Frame the raw app captures in a real iPhone and export the site's screen images.

    python3 _tools/build_screens.py              # every slot
    python3 _tools/build_screens.py home route   # only these slots

Input: _tools/captures/<slot>.png, raw 1320x2868 simulator captures made by
_tools/capture_screens.sh (iPhone 17 Pro Max, dark, 9:41 status bar, sample data).

Output, all in img/screens/ and referenced by the HTML by slot name only:

    <slot>-{480,720,1080}.avif and .webp   the capture inside the device frame, with
                                           alpha; AVIF first, WebP as the fallback
    <slot>-screen.jpg                      the bare capture at 1080 px wide, for the
                                           JSON-LD screenshot list (home and route)
    share-card-{240,360,540}.avif/.webp    the streak card exactly as Share Studio renders
                                           it, cut from the share-streak capture along its
                                           own rounded edge (shown beside a device, never
                                           over one)

The frame is Apple's own iPhone 17 Pro Max art in Deep Blue (_tools/frames/DeepBlue.png,
1470x3000, from fastlane's frameit-frames, the same art the ASO pipelines use), used
unaltered: no tilt, no crop, no reflections, nothing drawn over the screen. The capture is
a sharp rectangle and the real screen has rounded corners, so the exact aperture is read
from the frame's own alpha: the transparent hole that does not touch the image border.

Requires Pillow with AVIF and WebP, numpy and scipy.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
CAPTURES = os.path.join(HERE, "captures")
OUT = os.path.join(SITE, "img", "screens")

SLOTS = ("home", "route", "activity", "plan", "progress", "leaderboard", "share")
SCREEN_JPEG_SLOTS = ("home", "route")
# card slot -> (capture, card box in capture pixels, corner radius in capture pixels)
CARDS = {"share-card": ("share-streak", (104, 380, 1216, 2353), 60)}
CARD_WIDTHS = (240, 360, 540)

FRAME = {"file": os.path.join(HERE, "frames", "DeepBlue.png"), "origin": (75, 66), "screen": (1320, 2868)}
WIDTHS = (480, 720, 1080)
AVIF = {"quality": 45, "speed": 4}
WEBP = {"quality": 80, "method": 6}
JPEG = {"quality": 82, "optimize": True, "progressive": True}


def aperture_mask(frame):
    alpha = np.asarray(frame)[:, :, 3]
    labels, _ = ndimage.label(alpha == 0)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border.discard(0)
    aperture = (alpha == 0) & ~np.isin(labels, list(border))
    x0, y0 = FRAME["origin"]
    w, h = FRAME["screen"]
    return Image.fromarray(aperture[y0:y0 + h, x0:x0 + w].astype(np.uint8) * 255)


def load_capture(slot):
    path = os.path.join(CAPTURES, f"{slot}.png")
    if not os.path.exists(path):
        sys.exit(f"missing capture {path}: run _tools/capture_screens.sh first")
    capture = Image.open(path).convert("RGB")
    if capture.size != FRAME["screen"]:
        sys.exit(f"{path} is {capture.size}, expected {FRAME['screen']} (iPhone 17 Pro Max)")
    return capture


def framed(capture, frame, mask):
    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    canvas.paste(capture, FRAME["origin"], mask)
    canvas.alpha_composite(frame)
    return canvas


def export(image, slot, widths=WIDTHS):
    sizes = []
    for width in widths:
        height = round(image.height * width / image.width)
        resized = image.resize((width, height), Image.LANCZOS)
        for ext, options in (("avif", AVIF), ("webp", WEBP)):
            path = os.path.join(OUT, f"{slot}-{width}.{ext}")
            resized.save(path, ext.upper(), **options)
            sizes.append(f"{width}.{ext} {os.path.getsize(path) // 1024} KB")
    print(f"{slot}: " + ", ".join(sizes))


def build_card(slot):
    source, box, radius = CARDS[slot]
    card = load_capture(source).crop(box).convert("RGBA")
    mask = Image.new("L", (card.width * 4, card.height * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius * 4, fill=255)
    card.putalpha(mask.resize(card.size, Image.LANCZOS))
    export(card, slot, CARD_WIDTHS)


def main(slots):
    os.makedirs(OUT, exist_ok=True)
    frame = Image.open(FRAME["file"]).convert("RGBA")
    mask = aperture_mask(frame)
    for slot in slots:
        if slot in CARDS:
            build_card(slot)
            continue
        if slot not in SLOTS:
            sys.exit(f"unknown slot {slot!r}; known: {', '.join((*SLOTS, *CARDS))}")
        capture = load_capture(slot)
        export(framed(capture, frame, mask), slot)
        if slot in SCREEN_JPEG_SLOTS:
            bare = capture.resize((1080, round(capture.height * 1080 / capture.width)), Image.LANCZOS)
            bare.save(os.path.join(OUT, f"{slot}-screen.jpg"), "JPEG", **JPEG)


if __name__ == "__main__":
    main(sys.argv[1:] or (*SLOTS, *CARDS))
