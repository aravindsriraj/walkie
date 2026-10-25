from typing import Literal

from pydantic import BaseModel, Field

ACTIONABLE = {"click", "input", "keydown"}


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
    kind: Literal["click", "input", "keydown", "navigate"]
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


class Article(BaseModel):
    id: str
    status: Literal["processing", "ready", "failed"] = "processing"
    error: str = ""
    title: str = ""
    intro: str = ""
    outro: str = ""
    steps: list[Step] = []
    created_at: str


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
