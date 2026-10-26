"""Captions from the narration: cues timed inside each scene's clip, as VTT/SRT, or as images to burn in."""

import os
import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

LINE = 42  # columns per caption line (broadcast convention); a full-width character takes two
NO_LINE_START = "、。，．・：；！？）」』】ー"  # noqa: RUF001 (no Japanese or Chinese line begins with these)


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str  # at most two lines, joined by "\n"


def speakable(text: str) -> str:
    """Article markdown → plain words, for the voice and the captions."""
    return re.sub(r"\s+", " ", re.sub(r"\*\*|`", "", text)).strip()


def _cols(text: str) -> int:
    """Screen width in columns: Chinese, Japanese and Korean characters are twice as wide as Latin ones."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _wrap(text: str) -> list[str]:
    lines: list[str] = []
    for word in text.split(" "):
        if lines and _cols(lines[-1]) + 1 + _cols(word) <= LINE:
            lines[-1] += " " + word
            continue
        lines.append("")
        for c in word:  # Japanese and Chinese have no spaces, so a long run breaks between full-width characters
            if lines[-1] and _cols(lines[-1] + c) > LINE and _cols(c) == 2 and c not in NO_LINE_START:
                lines.append("")
            lines[-1] += c
    return lines


def cues(lines: list[tuple[int, int, str]]) -> list[Cue]:
    """lines: per scene, (where its clip starts in the video, clip length, narration)."""
    out = []
    for start, clip_ms, narration in lines:
        text = speakable(narration)
        if not text or clip_ms <= 0:
            continue
        wrapped = _wrap(text)
        chunks = ["\n".join(wrapped[i:i + 2]) for i in range(0, len(wrapped), 2)]
        total = sum(len(c) for c in chunks)
        done = 0
        for c in chunks:  # each cue gets time in proportion to its characters
            a = start + round(clip_ms * done / total)
            done += len(c)
            out.append(Cue(a, start + round(clip_ms * done / total), c))
    return out


def _ts(ms: int, sep: str) -> str:
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def to_vtt(cs: list[Cue]) -> str:
    return "WEBVTT\n" + "".join(f"\n{_ts(c.start_ms, '.')} --> {_ts(c.end_ms, '.')}\n{c.text}\n" for c in cs)


def to_srt(cs: list[Cue]) -> str:
    return "\n".join(f"{n}\n{_ts(c.start_ms, ',')} --> {_ts(c.end_ms, ',')}\n{c.text}\n" for n, c in enumerate(cs, 1))


# Burned-in captions need a font with every character in them. Pillow's built-in font lacks even "ó".
# First match wins: Debian/Docker (fonts-noto-core, fonts-noto-cjk), then macOS.
FONTS = [
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    # scripts the fonts above lack
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
    "/System/Library/Fonts/GeezaPro.ttc",
    "/System/Library/Fonts/Kohinoor.ttc",
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
]
# Scripts whose letters join or reorder: drawing them right needs Pillow's raqm layout engine.
NEEDS_SHAPING = re.compile("[\u0590-\u08ff\u0900-\u0dff\u0e00-\u0eff\u1000-\u109f]")


@cache
def _glyph(font: ImageFont.FreeTypeFont, c: str) -> bytes:
    img = Image.new("L", (font.size * 2, font.size * 2))
    ImageDraw.Draw(img).text((0, 0), c, font=font, fill=255)
    return img.tobytes()


def covers(font: ImageFont.FreeTypeFont, text: str) -> bool:
    """Every character has a real glyph (not the font's 'missing' box)."""
    missing = _glyph(font, "\U0010fffd")
    return all(c.isspace() or _glyph(font, c) != missing for c in set(text))


@cache
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def caption_font(text: str, size: int) -> ImageFont.FreeTypeFont:
    paths = [p for p in [os.getenv("WALKIE_CAPTION_FONT", ""), *FONTS] if p and Path(p).exists()]
    for path in paths:
        if covers(f := _font(path, size), text):
            return f
    raise ValueError("No installed font can draw these captions. Set WALKIE_CAPTION_FONT to a font that covers "
                     "this language, or download the captions file instead.")


def caption_png(text: str, width: int) -> Image.Image:
    """White text on a dark rounded box, centred on a transparent strip `width` wide (for burning in)."""
    if NEEDS_SHAPING.search(text) and not features.check("raqm"):
        raise ValueError("Captions in this language can't be drawn into the video here. Download the captions file "
                         "instead; video players show it correctly.")
    font = caption_font(text, max(18, width // 40))
    pad, margin = font.size // 2, font.size // 2
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    x0, y0, x1, y1 = probe.multiline_textbbox((0, 0), text, font=font, align="center", spacing=font.size // 4)
    bw, bh = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    img = Image.new("RGBA", (width, bh + 2 * margin), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    left = (width - bw) // 2
    d.rounded_rectangle((left, margin, left + bw, margin + bh), radius=pad, fill=(0, 0, 0, 184))
    d.multiline_text((left + pad - x0, margin + pad - y0), text, font=font, fill="white", align="center",
                     spacing=font.size // 4)
    return img
