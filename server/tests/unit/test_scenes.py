import itertools

import pytest

from app.scenes import (
    INTRO_MS,
    LEAD_MS,
    MAX_SPEED,
    SETTLE_MS,
    SILENT_MS,
    TAIL_MS,
    ScenePlan,
    plan_scene,
    scene_spans,
    sync_errors,
)


def speed(p):
    return (p.src_end_ms - p.src_ms) / p.out_ms


def check(plan, clicks, span, clip, hold=0):
    assert sum(p.out_ms for p in plan.pieces) == plan.out_ms
    assert all(p.out_ms > 0 for p in plan.pieces)
    assert all(speed(p) <= MAX_SPEED + 1e-9 for p in plan.pieces)
    srcs = [(p.src_ms, p.src_end_ms) for p in plan.pieces]
    assert all(a[1] <= b[0] for a, b in itertools.pairwise(srcs))  # forward in time, never repeats
    assert all(span[0] <= a <= b <= span[1] for a, b in srcs)
    assert plan.out_ms >= plan.voice_at_ms + clip + TAIL_MS + hold
    if clip:
        assert all(plan.voice_at_ms + LEAD_MS <= c < plan.voice_at_ms + clip for c in plan.clicks_at_ms)
    assert len(plan.clicks_at_ms) == len(clicks)
    # each click's output time maps back to that click's source time
    for c_out, c_src in zip(plan.clicks_at_ms, clicks, strict=False):
        t = 0
        for p in plan.pieces:
            if t == c_out:
                assert p.src_ms == c_src
                break
            t += p.out_ms
        else:
            pytest.fail(f"no piece starts at click {c_out}")


@pytest.mark.parametrize("clicks,span,clip", [
    ([5000], (3000, 6200), 4000),  # narration longer than the action: freeze before the click
    ([20000], (2000, 21200), 3000),  # 18 s of waiting before a quick sentence: speed + cut
    ([4000, 4600, 9000], (2500, 10200), 6000),  # three clicks in one sentence
    ([100], (0, 1300), 2500),  # click at the very start of the video
    ([5000, 5000], (3000, 6200), 3000),  # two events at the same instant (click + input)
    ([5000], (5000, 5000), 2000),  # zero-length span
])
def test_plan_keeps_every_click_inside_its_sentence(clicks, span, clip):
    check(plan_scene(clicks, span, clip), clicks, span, clip)


def test_hold_adds_time_after_the_narration():
    a, b = plan_scene([5000], (3000, 6200), 3000), plan_scene([5000], (3000, 6200), 3000, hold_ms=1000)
    assert b.out_ms == a.out_ms + 1000


def test_empty_narration_still_shows_the_action():
    p = plan_scene([5000], (3000, 6200), 0)
    assert p.out_ms >= SILENT_MS and p.clicks_at_ms[0] < p.out_ms
    check(p, [5000], (3000, 6200), 0)


def test_cut_keeps_the_moments_right_before_the_click():
    p = plan_scene([20000], (2000, 21200), 3000)
    pre = [q for q in p.pieces if q.src_end_ms <= 20000]
    assert pre[-1].src_end_ms == 20000 and pre[0].src_ms > 2000  # the start of the wait was cut, not the approach


def test_spans_cover_recorded_order_and_skip_the_intro():
    spans = scene_spans([[41000], [47000, 47500], [60000]], 143000)
    assert spans[0][0] == 41000 - INTRO_MS
    assert all(a[1] == b[0] for a, b in itertools.pairwise(spans))  # contiguous
    assert spans[1][0] == 41000 + SETTLE_MS and spans[-1][1] == 60000 + 2 * SETTLE_MS
    assert scene_spans([[300]], 1000) == [(0, 1000)]  # clamped to the video
    assert scene_spans([[1000], [1300]], 5000)[1][0] == 1150  # close clicks split the gap


def test_sync_errors():
    p = plan_scene([5000], (3000, 6200), 4000)
    assert sync_errors([p], [4000], [p.out_ms + 20]) == []
    assert sync_errors([p], [4000], [p.out_ms + 200])  # rendered length drifted
    bad = ScenePlan(p.pieces, p.voice_at_ms, p.out_ms, (p.voice_at_ms + 100,))
    assert sync_errors([bad], [4000], [p.out_ms])  # click before the lead-in
