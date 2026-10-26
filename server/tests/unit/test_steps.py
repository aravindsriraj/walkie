from PIL import Image

from app import store
from app.models import Article, RecEvent, Rect, Segment, Viewport
from app.steps import build_parts, normalize_steps

VP = Viewport(w=640, h=400)


def events():
    return [
        RecEvent(t=0, kind="navigate", viewport=VP, url="https://x.test"),
        RecEvent(t=1000, kind="click", viewport=VP, label="Sign in", rect=Rect(x=1, y=1, w=5, h=5)),
        RecEvent(t=3000, kind="input", viewport=VP, label="Name", value="Ada"),
        RecEvent(t=5000, kind="keydown", viewport=VP, key="Enter"),
    ]


def test_bad_and_duplicate_ids_dropped():
    draft = {"steps": [{"event_ids": [1, 99, -1], "text": "Click **Sign in**."},
                       {"event_ids": [1, 2], "text": "Type your name."},
                       {"event_ids": [0], "text": "navigate is not actionable"}]}
    steps = normalize_steps(draft, events())
    assert [s.event_ids for s in steps] == [[1], [2]]
    assert steps[1].frame == 2


def test_none_or_garbage_falls_back():
    for bad in (None, {"steps": "nope"}, {"steps": [{"event_ids": [99], "text": "x"}]}):
        steps = normalize_steps(bad, events())
        assert [s.text for s in steps] == ["Click **Sign in**.", "Type in **Name**.", "Press **Enter**."]


def test_narration_interleaved_in_time_order(tmp_path):
    for i in (1, 2, 3):
        Image.new("RGB", (64, 40)).save(tmp_path / f"{i}_full.png")
    segs = [Segment(start_ms=2500, end_ms=2900, text="now your name"),
            Segment(start_ms=500, end_ms=900, text="first sign in"),
            Segment(start_ms=9000, end_ms=9500, text="trailing")]
    texts = [p.text for p in build_parts(events(), segs, tmp_path) if p.text]
    assert texts == ['0.5s narrator: "first sign in"', '[1] 1.0s click on element "Sign in" at ',
                     '2.5s narrator: "now your name"', '[2] 3.0s input on element "Name" at  (value: "Ada")',
                     '[3] 5.0s keydown on element "" at  (key: Enter)', '9.0s narrator: "trailing"']


def test_build_parts_two_per_action(tmp_path):
    for i in (1, 2, 3):
        Image.new("RGB", (2000, 1000)).save(tmp_path / f"{i}_full.png")
    parts = build_parts(events(), [], tmp_path)
    assert len(parts) == 6
    assert parts[0].text.startswith('[1] 1.0s click on element "Sign in"')
    assert parts[1].inline_data.mime_type == "image/jpeg"


def test_store_roundtrip_and_interrupt(tmp_path):
    store.init(tmp_path / "t.db")
    store.save(Article(id="a1", created_at="2026-01-01", title="T"))
    store.save(Article(id="a2", created_at="2026-01-02", status="ready"))
    assert store.get("a1").title == "T"
    assert [a.id for a in store.list_all()] == ["a2", "a1"]
    store.mark_interrupted()
    a1 = store.get("a1")
    assert a1.status == "failed" and a1.error == "Interrupted — please re-upload"
    assert store.get("a2").status == "ready"
    assert store.get("missing") is None


def test_stale_lists_changed_and_untranslated_steps():
    from app.models import Step, Translation, TStep, source_hash
    s1 = Step(id="a", event_ids=[0], text="Click **Go**.", frame=0, narration="Click Go.")
    s2 = Step(id="b", event_ids=[1], text="Save.", frame=1, narration="Save it.")
    a = Article(id="x", created_at="t", steps=[s1, s2], translations={"es": Translation(
        title="", intro="", outro="", steps={"a": TStep(text="Haz clic", narration="Haz clic", src=source_hash(s1))})})
    assert a.stale == {"es": ["b"]}
    a.steps[0] = s1.model_copy(update={"narration": "Click the Go button."})
    assert a.stale == {"es": ["a", "b"]}
    assert Article.model_validate_json(a.model_dump_json()).stale == a.stale  # round-trips despite the computed key


def test_redact_events_are_not_actionable():
    from app.steps import actionable
    assert actionable([RecEvent(t=0, kind="redact", viewport=VP), *events()]) == [2, 3, 4]


def test_narration_parts_orders_by_recorded_time_and_interleaves_speech(tmp_path):
    from app.models import Step
    from app.steps import narration_parts
    for i in range(2):
        Image.new("RGB", (32, 20)).save(tmp_path / f"{i}_full.png")
    evs = [RecEvent(t=1000, kind="click", viewport=VP), RecEvent(t=5000, kind="click", viewport=VP)]
    steps = [Step(id="b", event_ids=[1], text="Save.", frame=1), Step(id="a", event_ids=[0], text="Open.", frame=0)]
    parts = narration_parts(steps, evs, [Segment(start_ms=3000, end_ms=4000, text="now save it")], tmp_path)
    texts = [p.text for p in parts if p.text]
    assert texts == ["[step 1] Open.", '3.0s narrator: "now save it"', "[step 2] Save."]
    assert sum(1 for p in parts if p.inline_data) == 2
