import html
import io
import json
import re
import zipfile
from collections.abc import Callable

from app import store
from app.captions import Cue, to_srt
from app.models import LANGUAGES, Article, Step


def md_inline(text: str) -> str:
    # ponytail: only **bold** and `code` are supported; swap in a Markdown lib if steps need more.
    s = html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", s)


def image_name(s: Step) -> str:
    return f"frames/{s.frame}_{'zoom' if s.zoomed else 'full'}.png"


CSS = """
body{font:16px/1.6 system-ui,-apple-system,sans-serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1f2937;background:#fff}
h1{font-size:2rem;line-height:1.2}ol{padding-left:1.4em}li{margin:0 0 2rem}
img{display:block;max-width:100%;margin-top:.75rem;border:1px solid #e5e7eb;border-radius:8px}
code{background:#f3f4f6;padding:1px 5px;border-radius:4px}.outro{margin-top:2rem}
@media print{li{break-inside:avoid}}
"""


def render_html(a: Article, img_src: Callable[[Step], str], autoprint: bool = False) -> str:
    items = [f'<li><p>{md_inline(s.text)}</p><img src="{img_src(s)}" alt=""></li>' for s in a.steps]
    script = "<script>addEventListener('load',()=>print())</script>" if autoprint else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(a.title)}</title>
<style>{CSS}</style></head><body><h1>{html.escape(a.title)}</h1><p>{md_inline(a.intro)}</p>
<ol>{''.join(items)}</ol><p class="outro">{md_inline(a.outro)}</p>{script}</body></html>"""


def _has_video(a: Article, lang: str) -> bool:
    """A finished video exists (an older one still counts while a new one renders)."""
    v = a.videos.get(lang)
    return bool(v and v.version > 0 and (store.DATA_DIR / a.id / f"video.{lang}.mp4").exists())


def _article_md(a: Article, lang: str, suffix: str) -> str:
    tr = a.translations.get(lang) if lang != a.lang else None
    title, intro, outro = (tr.title, tr.intro, tr.outro) if tr else (a.title, a.intro, a.outro)
    lines = [f"# {title}", "", intro, ""]
    if _has_video(a, lang):
        name = LANGUAGES.get(lang, lang)
        lines += [f'<video controls width="100%" src="video{suffix}.mp4"><track kind="captions" '
                  f'src="video{suffix}.vtt" srclang="{lang}" label="{name}" default></video>', ""]
    for n, step in enumerate(a.steps, 1):
        text = tr.steps[step.id].text if tr and step.id in tr.steps else step.text
        lines += [f"{n}. {text}", "", f"   ![Step {n}](images/{n}.png)", ""]
    lines.append(outro)
    return "\n".join(lines) + "\n"


def docs_zip(a: Article) -> bytes:
    """Everything a docs site needs: article.md (video embedded), images, and the video and captions, per language."""
    d = store.DATA_DIR / a.id
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n, s in enumerate(a.steps, 1):
            z.write(d / image_name(s), f"images/{n}.png")
        for lang in [a.lang, *a.translations]:
            suffix = "" if lang == a.lang else f".{lang}"
            z.writestr(f"article{suffix}.md", _article_md(a, lang, suffix))
            if _has_video(a, lang):
                z.write(d / f"video.{lang}.mp4", f"video{suffix}.mp4", compress_type=zipfile.ZIP_STORED)
                z.write(d / f"captions.{lang}.vtt", f"video{suffix}.vtt")
    return buf.getvalue()


def srt(a: Article, lang: str) -> str:
    cs = [Cue(**c) for c in json.loads((store.DATA_DIR / a.id / f"cues.{lang}.json").read_text())]
    return to_srt(cs)
