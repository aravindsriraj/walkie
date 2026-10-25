from types import SimpleNamespace as W

from app.gemini import words_to_segments


def w(text, start, end):
    return W(text=text, start_offset=start, end_offset=end, type="word_info")


def test_words_group_into_sentences_and_split_on_pauses():
    words = [w("First,", "0.600s", "0.900s"), w("sign", "1s", "1.200s"), w("in.", "1.200s", "1.500s"),
             w("Then", "4s", "4.300s"), w("wait", "4.300s", "4.600s"),
             w("later", "6s", "6.400s")]  # 1.4 s pause before "later" → new segment
    segs = words_to_segments(words)
    assert [(s.start_ms, s.end_ms, s.text) for s in segs] == [
        (600, 1500, "First, sign in."), (4000, 4600, "Then wait"), (6000, 6400, "later")]


def test_no_words():
    assert words_to_segments([]) == []
