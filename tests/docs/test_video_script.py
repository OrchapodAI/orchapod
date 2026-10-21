"""docs/video-script.md must fit the 3-minute limit, flag every shot that needs a live run and list its screenshots.

Cheap drift guards, stdlib only: the shot table and the screenshot table are parsed, not rendered.
"""

from __future__ import annotations

import re

from tests.docs.test_readme import STALE, _read

SCRIPT = _read("docs", "video-script.md")
LIMIT_S = 175  # Devpost wants a video under 3:00; keep 5 s of margin
WORDS_PER_S = 2.3  # clear narration is about 140 words a minute
# | # | m:ss-m:ss | Screen | Voice-over | Caption | Live run |
SHOT = re.compile(r"^\| (\d+) \| (\d+):(\d\d)-(\d+):(\d\d) \| ([^|]*) \| ([^|]*) \| ([^|]*) \| ([^|]*) \|[ \t]*$", re.M)
TABLE_ROW = re.compile(r"^\| \d+ \|", re.M)  # every row of the shot table, well formed or not


def shots() -> list[tuple[int, int, int, str, str, str]]:
    rows = [(int(n), 60 * int(m0) + int(s0), 60 * int(m1) + int(s1), vo.strip(), cap.strip(), live.strip())
            for n, m0, s0, m1, s1, _screen, vo, cap, live in SHOT.findall(SCRIPT)]
    assert rows and len(rows) == len(TABLE_ROW.findall(SCRIPT)), "a shot row is missing or malformed"
    return rows


def test_shots_are_contiguous_and_end_under_the_limit():
    rows = shots()
    assert [r[0] for r in rows] == list(range(1, len(rows) + 1))
    assert rows[0][1] == 0 and all(a[2] == b[1] for a, b in zip(rows, rows[1:]))
    assert all(r[2] > r[1] for r in rows) and rows[-1][2] <= LIMIT_S


def test_every_shot_has_a_caption_and_a_voice_over_that_fits_its_time():
    for n, start, end, vo, caption, _ in shots():
        assert vo and caption, f"shot {n}: voice-over and caption are required"
        assert len(vo.split()) <= WORDS_PER_S * (end - start), f"shot {n}: more words than {end - start} s allow"


def test_live_shots_are_marked_todo():
    for n, _, _, vo, caption, live in shots():
        assert live.lower() == "no" or "TODO(D8)" in live, f"shot {n}: say 'no', or TODO(D8) and what the shot needs"
        if "{" in vo + caption:
            assert "TODO(D8)" in live, f"shot {n}: a placeholder is filled from a live run"


def test_no_music_no_stale_names_and_every_todo_names_its_day():
    assert re.search(r"no music", SCRIPT, re.I)
    assert [s for s in STALE if s in SCRIPT] == []
    assert not re.search(r"TODO(?!\(D8\))", SCRIPT)


def test_screenshots_are_listed_once_and_live_ones_are_marked_todo():
    rows = [[c.strip() for c in ln.strip("| \n").split("|")] for ln in SCRIPT.splitlines() if ln.startswith("| `docs/img/")]
    files = [r[0].strip("`") for r in rows]
    assert len(files) == len(set(files)) and all(re.fullmatch(r"docs/img/[\w-]+\.png", f) for f in files)
    for kind in ("plan", "run", "eval", "playground"):  # the README's Results TODO names these four
        assert any(kind in f for f in files), f"no screenshot for the {kind}"
    assert [f for f, r in zip(files, rows) if not (r[-1].lower() == "no" or "TODO(D8)" in r[-1])] == []
