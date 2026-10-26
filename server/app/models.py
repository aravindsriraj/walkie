import hashlib
from typing import Literal

from pydantic import BaseModel, Field, computed_field

ACTIONABLE = {"click", "input", "keydown"}

# Languages offered for translation (BCP-47 → English name). Gemini TTS speaks many more; these are the common ones.
LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt-BR": "Portuguese (Brazil)",
    "nl": "Dutch", "sv": "Swedish", "pl": "Polish", "tr": "Turkish", "ru": "Russian", "uk": "Ukrainian",
    "ar": "Arabic", "hi": "Hindi", "id": "Indonesian", "vi": "Vietnamese", "th": "Thai", "ja": "Japanese",
    "ko": "Korean", "zh-CN": "Chinese (Simplified)",
}


class Rect(BaseModel):
    x: float
    y: float
    w: float
    h: float


class Viewport(BaseModel):
    w: int
    h: int
    dpr: float = 1


class RecEvent(BaseModel):
    t: int  # ms since recording start
    kind: Literal["click", "input", "keydown", "navigate", "redact"]  # redact: only where to blur, as the page changes
    url: str = ""
    viewport: Viewport
    rect: Rect | None = None
    label: str = ""
    tag: str = ""
    value: str = ""
    key: str = ""
    redact: list[Rect] = []


class Step(BaseModel):
    id: str
    event_ids: list[int]
    text: str
    frame: int  # event index whose screenshot is shown
    zoomed: bool = True
    narration: str = ""  # what the video says for this step (spoken wording, separate from the article text)
    hold_ms: int = 0  # extra time on this scene after the narration
    video_zoom: bool = True


def source_hash(s: Step) -> str:
    """What a translation was made from; when it changes, the translated step is stale."""
    return hashlib.sha1(f"{s.text}\0{s.narration}".encode()).hexdigest()[:10]


class VideoState(BaseModel):
    status: Literal["none", "rendering", "ready", "failed"] = "none"
    stage: str = ""
    updating: list[str] = []  # ids of steps whose scenes are being regenerated
    error: str = ""
    note: str = ""
    version: int = 0  # bumps on every finished render; the editor uses it to reload the player


class TStep(BaseModel):
    text: str
    narration: str
    src: str  # source_hash of the source step when this was translated


class Translation(BaseModel):
    title: str
    intro: str
    outro: str
    steps: dict[str, TStep] = {}  # by step id


class Article(BaseModel):
    id: str
    status: Literal["processing", "ready", "failed"] = "processing"
    error: str = ""
    title: str = ""
    intro: str = ""
    outro: str = ""
    steps: list[Step] = []
    created_at: str
    source: Literal["extension", "upload"] = "extension"  # uploads have no action log; Gemini finds the steps
    # Live progress while processing: what's happening now, and which screenshots are ready.
    stage: str = ""
    stage_total: int = 0  # number of screenshots to capture
    frames: list[int] = []
    lang: str = "en"  # language the presenter spoke; translations are the other languages
    voice: str = ""  # "" = the default voice; "mine" = the user's own voice
    videos: dict[str, VideoState] = {}  # by language
    translations: dict[str, Translation] = {}

    @computed_field
    @property
    def stale(self) -> dict[str, list[str]]:
        """Per translated language: source steps changed since they were translated, or never translated."""
        return {lang: [s.id for s in self.steps if (t := tr.steps.get(s.id)) is None or t.src != source_hash(s)]
                for lang, tr in self.translations.items()}


class Segment(BaseModel):
    start_ms: int
    end_ms: int
    text: str


# --- Agent output schemas ---


class DraftStep(BaseModel):
    event_ids: list[int] = Field(description="Ascending indices of the recorded actions this step covers")
    text: str = Field(description="One imperative instruction; UI labels in **bold**")


class StepsDraft(BaseModel):
    steps: list[DraftStep]


class ArticleMeta(BaseModel):
    title: str = Field(description="'How to ...', at most 10 words")
    intro: str = Field(description="1-2 sentences on what the reader will accomplish")
    outro: str = Field(description="One sentence on the result or next step")


# Uploaded videos: what was done, and where on screen.


class FoundAction(BaseModel):
    # MM:SS text, not seconds: Gemini reads video time as MM:SS, and asked for seconds it wrote 1:03.5 as 103.5.
    at: str = Field(description="When the click lands or the typing ends, as MM:SS.s from the start of the video, e.g. 01:03.5")
    kind: Literal["click", "input", "keydown"] = Field(description="click; input = typed into a field; keydown = pressed Enter")
    label: str = Field(description="The element's visible label or placeholder, exactly as on screen")
    value: str = Field(default="", description="For input: the typed text, or empty if it's a password, email or other personal data")


class FoundActions(BaseModel):
    actions: list[FoundAction]


class Located(BaseModel):
    box: list[int] = Field(description="[ymin, xmin, ymax, xmax] of the element acted on, each 0-1000")
    label: str = Field(default="", description="The element's visible text, or a 2-4 word description of an icon")
    pointer: list[int] = Field(default=[], description="[y, x] (0-1000) of the mouse pointer's tip, or [] if not visible")
    sensitive: list[list[int]] = Field(
        default=[], description="[ymin, xmin, ymax, xmax] boxes (0-1000) of every personal or secret item to blur")


class LocatedFrames(BaseModel):
    frames: list[Located]


# Video: narration, translation, blurring between actions.


class SceneLine(BaseModel):
    step: int = Field(description="The 1-based step number")
    narration: str = Field(description="What the narrator says for this step: 1-2 spoken sentences, no markdown")


class Narration(BaseModel):
    lang: str = Field(description="BCP-47 code of the language the presenter spoke, e.g. en, es, de; en if silent")
    scenes: list[SceneLine]


class TItem(BaseModel):
    id: str
    text: str
    narration: str


class TDoc(BaseModel):
    title: str
    intro: str
    outro: str
    steps: list[TItem]


class SensitiveFrames(BaseModel):
    frames: list[list[list[int]]] = Field(
        description="Per image, in order: [ymin, xmin, ymax, xmax] boxes (0-1000) of every personal or secret item")
