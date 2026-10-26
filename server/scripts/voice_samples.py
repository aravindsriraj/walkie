"""Listen before you choose: synthesize real tutorial lines in candidate voices.

    uv run python scripts/voice_samples.py <out_dir> [--mine sample.wav consent.wav]

Writes <out_dir>/<voice>.<lang>.<n>.wav and prints latency and length per clip, then transcribes every clip back
and prints each voice's word error rate per language: a voice that mispronounces a language shows up here (Iapetus
read Spanish as English, 94% wrong), before anyone has to listen.
"""

import asyncio
import base64
import io
import re
import subprocess
import sys
import time
import unicodedata
import wave
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv()
TTS = "gemini-3.8-flash-tts"
STYLE = "a calm, friendly product-tour narrator speaking at a natural, unhurried pace"
VOICES = ["Achird", "Sulafat", "Charon", "Aoede", "Kore"]  # the app's voices; Iapetus failed Spanish (94% wrong)
LINES = {
    "en": ["Click Glossary in the left navigation to see all your business glossaries.",
           "Expand Atlan Corporate Glossary, then open Business Definitions to see its terms.",
           "Click Save, and the term is now linked to this table."],
    "es": ["Haz clic en Glossary en la navegación de la izquierda para ver todos tus glosarios de negocio.",
           "Despliega Atlan Corporate Glossary y abre Business Definitions para ver sus términos.",
           "Haz clic en Save y el término quedará vinculado a esta tabla."],
    "de": ["Klicke links in der Navigation auf Glossary, um alle Geschäftsglossare zu sehen.",
           "Klappe Atlan Corporate Glossary auf und öffne Business Definitions, um die Begriffe zu sehen.",
           "Klicke auf Save, und der Begriff ist jetzt mit dieser Tabelle verknüpft."],
    "fr": ["Cliquez sur Glossary dans la navigation à gauche pour voir tous vos glossaires métier.",
           "Développez Atlan Corporate Glossary, puis ouvrez Business Definitions pour voir ses termes.",
           "Cliquez sur Save : le terme est maintenant lié à cette table."],
    "ja": ["左側のナビゲーションで Glossary をクリックすると、すべてのビジネス用語集が表示されます。",
           "Atlan Corporate Glossary を展開し、Business Definitions を開いて用語を確認します。",
           "Save をクリックすると、用語がこのテーブルにリンクされます。"],
}


def wav_ms(data: bytes) -> int:
    with wave.open(io.BytesIO(data)) as w:
        return round(w.getnframes() * 1000 / w.getframerate())


def to_wav(path: str) -> bytes:
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "24000", "-sample_fmt", "s16",
                           "-f", "wav", "-"], check=True, capture_output=True).stdout


async def speak(c, text: str, voice: str) -> bytes:
    r = await c.interactions.create(
        model=TTS, store=False, response_format={"type": "audio"},
        input=[{"type": "user_input", "content": [{"type": "text", "text": text,
                                                    "annotations": [{"type": "speech_metadata", "style": STYLE}]}]}],
        generation_config={"speech_config": [{"voice": voice}]})
    return base64.b64decode(r.output_audio.data)


def word_error(ref: str, hyp: str, lang: str = "") -> float:
    def words(t: str) -> list[str]:
        t = unicodedata.normalize("NFKC", t).lower()
        # Japanese has no spaces, so each hiragana or kanji counts as one "word". Katakana and Latin are skipped: the
        # transcript writes English UI names in katakana ("Glossary" → グロッサリー), which is right, not an error.
        return re.findall(r"[\u3040-\u309f\u4e00-\u9fff]", t) if lang == "ja" else re.findall(r"[\w']+", t)
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
    return d[len(h)] / max(1, len(r))


async def check(out: Path) -> None:
    from app.gemini import transcribe
    gate = asyncio.Semaphore(8)

    async def one(f: Path) -> tuple[str, str, float]:
        voice, lang, n = f.stem.split(".")
        async with gate:
            heard = " ".join(s.text for s in await transcribe(f.read_bytes(), "audio/wav"))
        return voice, lang, word_error(LINES[lang][int(n) - 1], heard, lang)

    by = defaultdict(list)
    for voice, lang, w in await asyncio.gather(*(one(f) for f in sorted(out.glob("*.wav")))):
        by[voice].append((lang, w))
    print("\nword error rate (transcribed back):")
    for voice, rows in sorted(by.items()):
        print(f"{voice:13}", "  ".join(f"{lang} {sum(w for x, w in rows if x == lang) / 3:.0%}" for lang in LINES))


async def main(out: Path, mine: tuple[str, str] | None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    async with genai.Client().aio as c:
        voices = list(VOICES)
        if mine:
            b64 = lambda p: base64.b64encode(to_wav(p)).decode()  # noqa: E731
            v = await c.voices.create(store=False, voice={
                "model": TTS, "type": "replicated", "display_name": "Stepcast",
                "replicated": {"source_audio": {"mime_type": "audio/wav", "data": b64(mine[0])},
                               "consent_audio": {"mime_type": "audio/wav", "data": b64(mine[1])}}})
            voices = [v.key]
        sem = asyncio.Semaphore(6)

        async def one(voice, lang, n, text):
            async with sem:
                t = time.time()
                data = await speak(c, text, voice)
                name = "mine" if voice.startswith("voicekey_") else voice
                (out / f"{name}.{lang}.{n}.wav").write_bytes(data)
                print(f"{name:13} {lang} {n}  {time.time() - t:5.1f}s  {wav_ms(data) / 1000:4.1f}s audio  {len(text)} chars")

        await asyncio.gather(*(one(v, lang, n, text) for v in voices for lang, lines in LINES.items()
                               for n, text in enumerate(lines, 1)))
    await check(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    mine = (args[args.index("--mine") + 1], args[args.index("--mine") + 2]) if "--mine" in args else None
    asyncio.run(main(Path(args[0]), mine))
