"""Scene timing: fit the recorded video around each narration clip, so every click lands while it's being described.

The video is fitted to the voice, never the voice to the video. Pure functions, no I/O; media.render_scene applies
the plans.
"""

import itertools
from dataclasses import dataclass

LEAD_MS = 400  # a click comes at least this long after its sentence starts, so viewers hear what's coming
TAIL_MS = 500  # quiet after the sentence before the next scene
GAP_MS = 250  # quiet before the sentence
SETTLE_MS = 1200  # how long a click's result stays on screen before the next scene's lead-up
MIN_AFTER_MS = 700  # at least this much of the result is shown after a scene's last click
SILENT_MS = 1500  # a scene with no narration still shows its action this long
MAX_SPEED = 3.0  # faster than this looks frantic; longer stretches are cut instead
INTRO_MS = 2000  # the first scene starts this long before the first click (skips a long intro)
FRAME_MS = 34  # one frame at 30 fps: rendered scene lengths may differ from the plan by this much


@dataclass(frozen=True)
class Piece:
    """Plays source [src_ms, src_end_ms) in out_ms. src_ms == src_end_ms freezes on that frame."""
    src_ms: int
    src_end_ms: int
    out_ms: int


@dataclass(frozen=True)
class ScenePlan:
    pieces: tuple[Piece, ...]
    voice_at_ms: int  # where the narration clip starts in the scene
    out_ms: int  # the scene's length
    clicks_at_ms: tuple[int, ...]  # when each click happens in the scene


def scene_spans(click_groups: list[list[int]], duration_ms: int) -> list[tuple[int, int]]:
    """Source span of each scene. Groups are each scene's click times, scenes in recorded order."""
    clamp = lambda t: min(max(t, 0), duration_ms)  # noqa: E731
    starts = [clamp(click_groups[0][0] - INTRO_MS)]
    for prev, cur in itertools.pairwise(click_groups):
        last, first = max(prev), min(cur)
        starts.append(clamp(last + min(SETTLE_MS, max(0, first - last) // 2)))
    ends = [*starts[1:], clamp(max(click_groups[-1]) + 2 * SETTLE_MS)]
    return list(zip(starts, ends, strict=True))


def _targets(k: int, clip_ms: int) -> list[int]:
    """When each of k clicks should happen in the scene: spread through the sentence, after the lead-in."""
    if clip_ms == 0:
        return [600 + 400 * j for j in range(k)]
    lead = min(LEAD_MS, clip_ms // 2)
    lo, hi = GAP_MS + lead, GAP_MS + clip_ms - 1
    step = min(300, max(1, (hi - lo) // k))
    want = [GAP_MS + max(lead, round(clip_ms * (0.35 + 0.5 * j / k))) for j in range(k)]
    want = [min(w, hi - 200) for w in want]
    out: list[int] = []
    for j, w in enumerate(want):  # inside [lo, hi], increasing by at least `step`, room left for later clicks
        t = min(max(w, lo + j * step), hi - (k - 1 - j) * step)
        out.append(max(t, out[-1] + step) if out else t)
    return out


def _gap(a: int, b: int, dur: int, kind: str) -> list[Piece]:
    """Pieces that turn source [a, b) into dur ms of output.

    kind: "first" (lead-up to the first click), "middle" (between clicks), "last" (after the last click).
    """
    src = b - a
    if src <= dur:  # pad with a freeze: before a click on the gap's first frame, after the last click on its end
        if kind == "last":
            return [p for p in (Piece(a, b, src), Piece(b, b, dur - src)) if p.out_ms > 0]
        return [p for p in (Piece(a, a, dur - src), Piece(a, b, src)) if p.out_ms > 0]
    if src <= dur * MAX_SPEED:
        return [Piece(a, b, dur)]
    keep = int(dur * MAX_SPEED)  # too long even at full speed: cut, keeping what matters
    if kind == "first":
        return [Piece(b - keep, b, dur)]  # the approach to the click
    if kind == "last":
        return [Piece(a, a + keep, dur)]  # the click's result
    head = max(1, dur // 3)  # between clicks: a little of the result, then the approach to the next click
    tail = dur - head
    return [Piece(a, a + int(head * MAX_SPEED), head)] + ([Piece(b - int(tail * MAX_SPEED), b, tail)] if tail else [])


def plan_scene(clicks_ms: list[int], span: tuple[int, int], clip_ms: int, hold_ms: int = 0) -> ScenePlan:
    t = _targets(len(clicks_ms), clip_ms)
    if clip_ms:
        out = max(GAP_MS + clip_ms + TAIL_MS, t[-1] + MIN_AFTER_MS) + hold_ms
    else:
        out = max(SILENT_MS, t[-1] + MIN_AFTER_MS) + hold_ms
    src = [span[0]]
    for c in clicks_ms:
        src.append(min(max(c, src[-1]), span[1]))
    src.append(span[1])
    dst = [0, *t, out]
    pieces: list[Piece] = []
    for g in range(len(src) - 1):
        kind = "first" if g == 0 else "last" if g == len(src) - 2 else "middle"
        pieces += _gap(src[g], src[g + 1], dst[g + 1] - dst[g], kind)
    return ScenePlan(tuple(pieces), GAP_MS, out, tuple(t))


def sync_errors(plans: list[ScenePlan], clip_ms: list[int], rendered_ms: list[int]) -> list[str]:
    """Empty when every click lands inside its sentence and every rendered scene is as long as planned."""
    errors = []
    for n, (p, clip, got) in enumerate(zip(plans, clip_ms, rendered_ms, strict=True), 1):
        lead = min(LEAD_MS, clip // 2)
        if clip and not all(p.voice_at_ms + lead <= c < p.voice_at_ms + clip for c in p.clicks_at_ms):
            errors.append(f"scene {n}: click at {p.clicks_at_ms} outside narration {p.voice_at_ms}+{clip} ms")
        if abs(got - p.out_ms) > FRAME_MS:
            errors.append(f"scene {n}: rendered {got} ms, planned {p.out_ms} ms")
    return errors
