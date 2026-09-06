"""Lining a song up behind the one playing.

The rest of this suite reads console.js as text, which is enough to hold
a wiring or a selector. It is not enough here: what `playNext` gets right
or wrong is the arithmetic of moving one element of an array while two
markers point into it, and every wrong version of that is a source file
that reads perfectly well. So this drives the shipped function.

Skipped where node is not installed rather than made a dependency: the
Python suite must go on passing on a machine that has never run a
JavaScript tool.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("src/pypl2mp3/web/static/console.js")

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)


def _source(name: str) -> str:
    """The named function, lifted out of console.js as it ships."""

    body = re.search(
        r"\n  function " + name + r"\((.*?)\n  \}\n", SCRIPT.read_text(), re.S
    )
    assert body, f"{name} is not where this test looked for it"

    return "function " + name + "(" + body.group(1) + "\n}"


def _one_song(tmp_path):
    """A repository holding a single song, so the listing has a row."""

    from mutagen.id3 import ID3, TXXX

    folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "UNKNOWN - Something [aaaaaaaaaaa] (JUNK).mp3"
    path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
    frames.save(path)

    return path

def _run(setup: str, steps: str) -> dict:
    """Run playNext against a stubbed console and report the queue."""

    harness = f"""
let queue = [], index = 0, direction = 1, orderIsOwn = false;
let rows = [];
function queueFromRows() {{ return rows.map(id => ({{ id }})); }}
function setQueue(entries, startAt, randomOrder) {{
  queue = entries;
  lineup = [];
  orderIsOwn = Boolean(randomOrder);
  index = startAt > 0 ? startAt : 0;
}}
function paint() {{ lineupRanks(); }}
let lineup = [];
{_source("lineupAhead")}
{_source("lineupRanks")}
{_source("playNext")}
{setup}
{steps}
paint();
console.log(JSON.stringify({{
  queue: queue.map(e => e.id),
  playing: queue[index] ? queue[index].id : null,
  index, lineup, direction, orderIsOwn,
  // Read off the page's own ranking, not worked out a second time here.
  ranks: [...lineupRanks()].map(([id, rank]) => id + ":" + rank),
}}));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr

    return json.loads(done.stdout)


FIVE = """
rows = ["a", "b", "c", "d", "e"];
queue = rows.map(id => ({ id }));
index = 0;
"""


@needs_node
def test_one_song_goes_straight_after_the_one_playing():
    out = _run(FIVE, 'playNext("d");')

    assert out["queue"] == ["a", "d", "b", "c", "e"], out
    assert out["playing"] == "a", "the song playing must not change"

    # And the queue's order is now its own, which is what puts the play
    # position beside every row: the listing can no longer show it.
    assert out["orderIsOwn"] is True, (
        "a song moved by hand, and the listing still claims to be the order"
    )


@needs_node
def test_the_next_one_goes_after_it_and_not_after_the_playing_song():
    """The whole of the request. Lining up three songs plays them in the
    order they were picked; appending each one right behind the playing
    song would play them in reverse."""

    out = _run(FIVE, 'playNext("d"); playNext("e"); playNext("c");')

    assert out["queue"] == ["a", "d", "e", "c", "b"], out
    assert out["ranks"] == ["d:1", "e:2", "c:3"], out


@needs_node
def test_a_song_is_moved_and_never_copied():
    """A copy would play the song twice and make the toolbar's "12 / 79"
    a count of something other than the selection."""

    out = _run(FIVE, 'playNext("d"); playNext("e"); playNext("d");')

    assert sorted(out["queue"]) == ["a", "b", "c", "d", "e"], out
    assert len(out["queue"]) == 5, out


@needs_node
def test_asking_again_for_one_already_lined_up_moves_it_to_the_end():
    """Pressing it a second time is a second request, so the song goes
    where a second request goes — behind the rest of the run.

    This is the case that needs the pointer to come back with the
    removal. Without it the run is measured from where it ended before
    the song was taken out of the middle of it, and the song lands one
    place too far — past a song nobody asked for."""

    out = _run(FIVE, 'playNext("d"); playNext("e"); playNext("d");')

    assert out["queue"] == ["a", "e", "d", "b", "c"], out
    assert out["ranks"] == ["e:1", "d:2"], out


@needs_node
def test_a_song_already_behind_the_playing_one_comes_forward():
    """The index has to come back with it. Working the destination out
    before the removal puts the queue one place out and the wrong song
    reads as playing."""

    out = _run(FIVE + "index = 2;", 'playNext("a");')

    assert out["playing"] == "c", "the playing song moved under the cursor"
    assert out["queue"] == ["b", "c", "a", "d", "e"], out


@needs_node
def test_once_the_run_has_played_the_next_request_starts_a_new_one():
    """A song the run has been played past is out of it, so the request
    lands right behind the song playing and counts from one again."""

    out = _run(FIVE + 'playNext("e"); index = 2;', 'playNext("c");')

    # a, e, b, c, d — e was played past, b is playing at 2, c comes to 3.
    assert out["playing"] == "b", out
    assert out["queue"] == ["a", "e", "b", "c", "d"], out
    assert out["ranks"] == ["c:1"], out
    assert out["lineup"] == ["c"], "e is behind the cursor and still in the run"


@needs_node
def test_a_song_that_is_in_the_listing_twice_still_takes_one_place():
    """Eight songs sit in two playlists at once, so the queue holds two
    entries carrying one id — the rows are named by the video, not by the
    file, exactly as the playing highlight already is.

    Taking the first copy out does not take the id out of the queue, so
    without dropping it from the run by hand the second request finds its
    own other copy still ahead and lines up behind *that*: the song goes
    to the end instead of the front, and the run numbers one id twice,
    which on screen is a rank with no rank before it."""

    twice = 'rows = ["a", "b", "x", "c"]; queue = ["a", "b", "x", "c", "x"]'
    twice += '.map(id => ({ id })); index = 0;'

    out = _run(twice, 'playNext("x"); playNext("x");')

    assert out["queue"][:2] == ["a", "x"], (
        f"asking twice sent it to the back: {out['queue']}"
    )
    assert out["ranks"] == ["x:1"], out
    assert out["lineup"] == ["x"], "one song, two places in the run"


@needs_node
def test_going_back_does_not_draft_a_song_into_the_run():
    """The bug this file was written the wrong way for.

    The run used to be an index — "it ends here" — and the rank was the
    distance from the playing song. Press ← once and the cursor moves
    the other way, so every song between the new position and that index
    was inside the run: a song nobody had asked for took the head of it,
    and the next request came out one too high. Seen on screen, not
    reasoned about.

    A rank has to come from the run, never from where the cursor
    happens to be."""

    # Playing c at 2, e lined up behind it, then back one to b.
    out = _run(FIVE + 'index = 2; playNext("e"); index = 1;', "")

    assert out["playing"] == "b", out
    assert out["ranks"] == ["e:1"], (
        "a song between the cursor and the run was drafted into it"
    )

    # And the one added after it comes next, not third.
    out = _run(FIVE + 'index = 2; playNext("e"); index = 1;', 'playNext("a");')

    assert [rank.split(":")[1] for rank in out["ranks"]] == ["1", "2"], out
    assert out["ranks"][1] == "a:2", out


@needs_node
def test_the_song_playing_cannot_be_lined_up_behind_itself():
    out = _run(FIVE, 'playNext("a");')

    assert out["queue"] == ["a", "b", "c", "d", "e"], out
    assert out["lineup"] == [], out


@needs_node
def test_it_turns_the_queue_forward():
    """A track ending follows `direction`. Walking backwards through a
    selection would never reach what was just lined up."""

    out = _run(FIVE + "index = 3; direction = -1;", 'playNext("a");')

    assert out["direction"] == 1, out


@needs_node
def test_with_nothing_playing_it_takes_the_listing_and_starts_there():
    """There is no "next" for it to come after."""

    out = _run('rows = ["a", "b", "c"]; queue = [];', 'playNext("b");')

    assert out["queue"] == ["a", "b", "c"], out
    assert out["playing"] == "b", out


@needs_node
def test_writing_the_rank_touches_nothing_it_does_not_change():
    """A MutationObserver on #list calls `paint`, so anything paint writes
    inside the listing calls paint again. `textContent = x` replaces the
    text node even when x is exactly what was already there, and that is
    a childList record, and that record is another paint — the page
    locked up the moment the first song was lined up.

    So this counts the writes rather than reading the result: a second
    call with the same rank must touch nothing at all."""

    # The span ships `hidden` and empty — `test_the_row_offers_it...`
    # below holds the template to it — so the stub starts where the page
    # starts. A stub that starts anywhere else would report a write the
    # real row never makes.
    harness = """
function badge() {
  let text = "", hidden = true, writes = 0;
  return {
    get textContent() { return text; },
    set textContent(v) { writes += 1; text = v; },
    get hidden() { return hidden; },
    set hidden(v) { writes += 1; hidden = v; },
    seen() { return writes; },
  };
}
""" + _source("showRank") + """
const lined = badge();
showRank(lined, 1);
const afterFirst = lined.seen();
showRank(lined, 1);
showRank(lined, 1);

const blank = badge();
showRank(blank, 0);
showRank(blank, 0);

// And one that was lined up and no longer is: it has to be cleared, then
// left alone.
const dropped = badge();
showRank(dropped, 2);
const beforeDrop = dropped.seen();
showRank(dropped, 0);
const afterDrop = dropped.seen();
showRank(dropped, 0);

console.log(JSON.stringify({
  wroteOnce: afterFirst > 0,
  settled: lined.seen() === afterFirst,
  label: lined.textContent,
  untouched: blank.seen(),
  cleared: afterDrop > beforeDrop && dropped.textContent === ""
           && dropped.hidden === true,
  clearedSettled: dropped.seen() === afterDrop,
}));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)

    assert out["wroteOnce"], "the rank never reaches the row"
    assert out["label"] == "next 1", out
    assert out["settled"], (
        "repainting an unchanged row writes to it again, which is the loop"
    )
    assert out["untouched"] == 0, (
        "a row that was never lined up is written to anyway, "
        "so every paint mutates all 944 of them"
    )
    assert out["cleared"], "a row that left the run keeps its rank"
    assert out["clearedSettled"], "clearing it goes on writing afterwards"


def test_a_new_selection_forgets_what_was_lined_up():
    """Read rather than run: `setQueue` is the harness's own stub above,
    so this is the one thing the harness cannot answer for."""

    body = re.search(
        r"\n  function setQueue\(entries, startAt, randomOrder\) \{(.*?)\n  \}",
        SCRIPT.read_text(), re.S,
    )

    assert body, "setQueue moved"
    assert "lineup = []" in body.group(1), (
        "a new selection keeps the run built against the old queue"
    )


async def test_the_row_offers_it_and_has_somewhere_to_show_it(tmp_path):
    """The button, and the badge the page writes the rank into.

    The badge is not a button, deliberately: the row's buttons are
    hidden until the pointer arrives, and a song's place in the queue is
    true of the row whether or not you are looking at it."""

    import httpx

    from pypl2mp3.web.app import create_app

    _one_song(tmp_path)
    app = create_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        page = (await client.get("/")).text

    row = re.search(r'<tr id="song-aaaaaaaaaaa".*?</tr>', page, re.S)
    assert row, "no song row on the page"

    assert "data-play-next" in row.group(0), (
        "no way to line a song up behind the one playing"
    )
    assert re.search(r'<span class="queued"[^>]*hidden', row.group(0)), (
        "nowhere to say where the song stands, or it starts out showing"
    )

    # Painted, and not merely classed — the failure this project keeps
    # meeting.
    css = Path("src/pypl2mp3/web/static/console.css").read_text()
    rule = re.search(r"\n\.row-actions \.queued \{([^}]*)\}", css)
    assert rule, "the badge is a class nothing paints"
    assert "opacity: 0" not in rule.group(1), (
        "the badge hides with the buttons beside it"
    )

    # And the page fills it in.
    script = SCRIPT.read_text()
    assert 'querySelector(".queued")' in script, "nothing ever writes the rank"


# ---------------------------------------------------------------------
# The listing's order
# ---------------------------------------------------------------------

def _order(setup: str, steps: str) -> dict:
    """Drive the shipped ordering against rows that are plain objects.

    `inPlayOrder` and `lay` only ever read `dataset.songId`, `parentNode`
    and identity, so a row can be an object — which is what lets this run
    with no DOM at all.
    """

    harness = """
let queue = [];
class Fragment {
  constructor() { this.taken = []; }
  appendChild(row) { this.taken.push(row); }
}
const document = { createDocumentFragment: () => new Fragment() };
const bench = {
  children: [],
  appendChild(batch) { bench.children = batch.taken.slice(); bench.laid += 1; },
  laid: 0,
};
function row(id) { return { dataset: { songId: id }, parentNode: bench }; }
""" + _source("inPlayOrder") + _source("lay") + """
""" + setup + """
""" + steps + """
console.log(JSON.stringify({
  order: bench.children.map(r => r.dataset.songId),
  laid: bench.laid,
}));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr

    return json.loads(done.stdout)


LISTING = """
bench.children = ["a", "b", "c", "d", "e"].map(row);
queue = ["c", "a", "e", "b", "d"].map(id => ({ id }));
"""


@needs_node
def test_the_listing_can_be_laid_in_the_order_it_plays():
    out = _order(LISTING, "lay(bench.children, inPlayOrder(bench.children));")

    assert out["order"] == ["c", "a", "e", "b", "d"], out
    assert out["laid"] == 1, out


@needs_node
def test_laying_it_out_twice_moves_nothing_the_second_time():
    """A MutationObserver on #list calls `paint`, so a reorder that runs
    whether or not anything moved calls itself for ever: taking a node
    out and putting it back where it was is still a childList record."""

    out = _order(
        LISTING,
        "lay(bench.children, inPlayOrder(bench.children));"
        "lay(bench.children, inPlayOrder(bench.children));"
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["c", "a", "e", "b", "d"], out
    assert out["laid"] == 1, "it puts the listing back every single paint"


@needs_node
def test_a_song_in_two_playlists_takes_two_places():
    """One id names two rows, and in the queue those are two entries and
    two places. Looked up rather than walked, both rows would answer to
    the first entry and the second would find nothing."""

    out = _order(
        """
        bench.children = ["a", "x", "b", "x"].map(row);
        queue = ["x", "a", "x", "b"].map(id => ({ id }));
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["x", "a", "x", "b"], out


@needs_node
def test_rows_the_queue_never_saw_go_behind_in_their_own_order():
    """The queue is a snapshot of the rows at the moment you pressed
    play, so a listing filtered since then holds songs it never saw.
    Dropping them would be losing rows off the page."""

    out = _order(
        """
        bench.children = ["a", "b", "c", "d"].map(row);
        queue = ["c", "a"].map(id => ({ id }));
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["c", "a", "b", "d"], out


def _ranks(setup: str) -> list:
    """What the page would write into the rows, for the shipped rules."""

    harness = """
let queue = [], listOrder = "name", orderIsOwn = false;
function row(id) { return { dataset: { songId: id } }; }
""" + _source("inPlayOrder") + _source("playRanks") + """
""" + setup + """
console.log(JSON.stringify(
  [...playRanks(listing)].map(([r, n]) => r.dataset.songId + ":" + n)
));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr

    return json.loads(done.stdout)


THREE = 'const listing = ["a", "b", "c"].map(row);'


@needs_node
def test_no_rank_when_it_would_only_count_the_listing_back():
    """Play all takes the rows as they stand, so the queue's order is the
    listing's and a number beside each row says nothing at all."""

    assert _ranks(THREE + 'queue = ["a", "b", "c"].map(id => ({ id }));') == []


@needs_node
def test_the_rank_shows_once_the_queue_has_an_order_of_its_own():
    """Shuffling gives it one, and so does lining a song up by hand.
    Either way the play order is a thing the listing cannot show."""

    for made_its_own in ("orderIsOwn = true;", 'listOrder = "play";'):
        out = _ranks(
            THREE + 'queue = ["c", "a", "b"].map(id => ({ id }));' + made_its_own
        )

        assert out == ["c:1", "a:2", "b:3"], (made_its_own, out)


@needs_node
def test_in_play_order_the_rank_shows_even_when_the_two_agree():
    """Asked for that view, the number is the point: it says where you
    are in a run of 944 rather than where a name falls in an alphabet."""

    out = _ranks(THREE + 'queue = ["a", "b", "c"].map(id => ({ id }));'
                 + 'listOrder = "play";')

    assert out == ["a:1", "b:2", "c:3"], out


@needs_node
def test_a_row_the_queue_never_saw_gets_no_number():
    """It has no place in an order it is not part of."""

    out = _ranks(THREE + 'queue = ["c"].map(id => ({ id })); orderIsOwn = true;')

    assert out == ["c:1"], out


async def test_the_toolbar_carries_the_order_switch(tmp_path):
    """Two named states drawn as text, like the theme switch: a way of
    looking rather than an action."""

    import httpx

    from pypl2mp3.web.app import create_app

    _one_song(tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        page = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text

    switch = re.search(r'<div id="order".*?</div>', page, re.S)
    assert switch, "no way to choose the listing's order"
    assert re.findall(r'data-order="(\w+)"', switch.group(0)) == ["name", "play"],\
        switch.group(0)

    # Painted, and not merely classed.
    rule = re.search(r"\n#order button\.chosen \{([^}]*)\}", css)
    assert rule and "var(--accent)" in rule.group(1), (
        "nothing on the page says which of the two is on"
    )

    # And the row has somewhere to put the number, shipped empty.
    row = re.search(r'<span class="rank"[^>]*>', page)
    assert row and "hidden" in row.group(0), (
        "nowhere to write the play position, or it starts out showing"
    )

    place = re.search(r"\n\.row-actions \.rank \{([^}]*)\}", css)
    assert place, "the slot is a class nothing paints"
    assert "tabular-nums" in place.group(1), (
        "a column of numbers that do not line up"
    )
