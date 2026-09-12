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

import httpx
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
let queue = [], index = 0, direction = 1;
let rows = [];
// A row's key is what says which row; its id is what the server is
// asked about the song. They differ only where one video is held twice,
// which the duplicate tests below spell out — everywhere else one
// letter stands for both.
function entry(key, id) {{ return {{ key, id: id || key }}; }}
function queueFromRows() {{ return rows.map(id => entry(id)); }}
function setQueue(entries, startAt) {{
  queue = entries;
  lineup = [];
  index = startAt > 0 ? startAt : 0;
}}
function paint() {{ lineupStanding(); }}
let lineup = [];
const returns = new Map();
{_source("lineupAhead")}
{_source("lineupStanding")}
{_source("playNext")}
{_source("unqueue")}
{setup}
{steps}
paint();
console.log(JSON.stringify({{
  queue: queue.map(e => e.key),
  playing: queue[index] ? queue[index].key : null,
  index, lineup, direction,
  // Read off the page's own run, not worked out a second time here.
  ranks: lineupStanding().map((s, i) => s.key + ":" + (i + 1)),
}}));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr

    return json.loads(done.stdout)


FIVE = """
rows = ["a", "b", "c", "d", "e"];
queue = rows.map(id => entry(id));
index = 0;
"""


@needs_node
def test_one_song_goes_straight_after_the_one_playing():
    out = _run(FIVE, 'playNext("d");')

    assert out["queue"] == ["a", "d", "b", "c", "e"], out
    assert out["playing"] == "a", "the song playing must not change"


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
def test_two_copies_of_one_video_are_two_places_in_the_run():
    """Eight songs sit in two playlists at once. The rows used to be
    named by the video, so the two were one thing to the page: the one
    playing lit both, and lining up the second lined up the first.

    Named by the playlist and the video they are two, and the run holds
    them apart — asked for in the order second, first, they play in that
    order."""

    twice = (
        'rows = ["a", "b", "x1", "c", "x2"];'
        'queue = [entry("a"), entry("b"), entry("x1", "x"),'
        '         entry("c"), entry("x2", "x")];'
        "index = 0;"
    )

    out = _run(twice, 'playNext("x2"); playNext("x1");')

    assert out["queue"] == ["a", "x2", "x1", "b", "c"], out
    assert out["ranks"] == ["x2:1", "x1:2"], (
        f"one video, one place in the run: {out['ranks']}"
    )


@needs_node
def test_taking_one_out_sends_it_home_and_not_back_to_the_front():
    """Ask for two songs that sit next to each other, and the first
    records the second as its way home. The second is then lifted to the
    front too — so following it home follows it to the front: the song
    came out of the run and went straight back to where the run is,
    unmarked and apparently anchored. Seen on screen.

    Each song the chain passes recorded its own way home, so following
    it past everything still lifted arrives at one that never moved.
    """

    out = _run(
        FIVE + "index = 0;",
        # "c" and "d" are neighbours: c's way home is d, and d is lifted
        # right after it.
        'playNext("c"); playNext("d"); unqueue("c");',
    )

    assert out["queue"] == ["a", "d", "b", "c", "e"], (
        f"c did not go home: {out['queue']}"
    )
    assert out["lineup"] == ["d"], out
    assert out["ranks"] == ["d:1"], out


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
def test_writing_the_button_touches_nothing_it_does_not_change():
    """A MutationObserver on #list calls `paint`, so anything paint writes
    inside the listing calls paint again. `textContent = x` replaces the
    text node even when x is exactly what was already there, and that is
    a childList record, and that record is another paint — the page
    locked up the moment the first song was lined up.

    So this counts the writes rather than reading the result: a second
    call with the same state must touch nothing at all."""

    # A row starts out saying "Play next": that is what the template
    # ships, so the stub starts where the page starts. A stub starting
    # anywhere else would report a write the real row never makes.
    harness = """
function row(label) {
  let text = label, title = "Play it after the one playing", writes = 0;
  const button = {
    get textContent() { return text; },
    set textContent(v) { writes += 1; text = v; },
    get title() { return title; },
    set title(v) { writes += 1; title = v; },
  };
  return {
    querySelector: () => button,
    label: () => text,
    seen: () => writes,
  };
}
""" + _source("showAsk") + """
// Asked for: the label turns over once, then holds.
const asked = row("Play next");
showAsk(asked, true);
const afterFirst = asked.seen();
showAsk(asked, true);
showAsk(asked, true);

// Never asked for: nothing is written at all.
const plain = row("Play next");
showAsk(plain, false);
showAsk(plain, false);

// Taken back out: turned back, then left alone.
const dropped = row("Play next");
showAsk(dropped, true);
const beforeDrop = dropped.seen();
showAsk(dropped, false);
const afterDrop = dropped.seen();
showAsk(dropped, false);

console.log(JSON.stringify({
  wroteOnce: afterFirst > 0,
  settled: asked.seen() === afterFirst,
  label: asked.label(),
  untouched: plain.seen(),
  cleared: afterDrop > beforeDrop && dropped.label() === "Play next",
  clearedSettled: dropped.seen() === afterDrop,
}));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)

    assert out["wroteOnce"], "the label never changes on a song you asked for"
    assert out["label"] == "Take out", out
    assert out["settled"], (
        "repainting an unchanged row writes to it again, which is the loop"
    )
    assert out["untouched"] == 0, (
        "a row nobody asked for is written to anyway, so every paint "
        "mutates all 944 of them"
    )
    assert out["cleared"], "taking it out leaves the label saying Take out"
    assert out["clearedSettled"], "turning it back goes on writing afterwards"


def test_a_new_selection_forgets_what_was_lined_up():
    """Read rather than run: `setQueue` is the harness's own stub above,
    so this is the one thing the harness cannot answer for."""

    body = re.search(
        r"\n  function setQueue\(entries, startAt\) \{(.*?)\n  \}",
        SCRIPT.read_text(), re.S,
    )

    assert body, "setQueue moved"
    assert "lineup = []" in body.group(1), (
        "a new selection keeps the run built against the old queue"
    )


async def test_a_waiting_song_keeps_its_mark_until_it_plays(tmp_path):
    """For as long as it is true, which a badge could not manage: that
    one counted the rows between here and the song playing, so it
    vanished the moment the cursor passed a song that had not moved.

    A ground of its own, one step between the hover and the playing row —
    two rows wearing the playing row's tint would be two rows claiming to
    be on."""

    import httpx

    from pypl2mp3.web.app import create_app

    _one_song(tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        css = (await client.get("/static/console.css")).text

    rule = re.search(r"\ntbody tr\.queued \{([^}]*)\}", css)
    assert rule, "a waiting song is marked by nothing"
    assert "var(--queued)" in rule.group(1), rule.group(1)

    # Its own step, not the playing row's and not the hover's.
    values = dict(re.findall(r"(--(?:queued|accent-soft|hover)):\s*([^;]+);",
                             css))
    assert len({values["--queued"], values["--accent-soft"],
                values["--hover"]}) == 3, values

    # The left edge stays the playing row's alone.
    assert "border-left" not in rule.group(1), (
        "two rows carry the bar that says which one is on"
    )

    # And the pointer still answers on a row that is already tinted.
    assert re.search(r"\ntbody tr\.queued:hover \{", css), (
        "hovering a waiting song shows nothing, its tint having already "
        "taken the hover's place"
    )

    script = SCRIPT.read_text()
    assert 'classList.toggle("queued", queued)' in script, (
        "nothing puts the mark on, or it is put on with a value that "
        "could be undefined — which makes toggle toggle"
    )


async def test_the_row_offers_it_and_takes_it_back(tmp_path):
    """One control, two states. There was a strip above the listing for
    taking a song back out, and with the listing in play order that strip
    showed the run a second time — the confusion it was built to fix,
    moved one row up.

    The label is also the only mark saying you put the song there: in
    play order a row following the one playing looks the same whether you
    asked for it or it was simply next.
    """

    import httpx

    from pypl2mp3.web.app import create_app

    _one_song(tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        page = (await client.get("/")).text

    row = re.search(r'<tr id="song-[0-9a-f]{16}".*?</tr>', page, re.S)
    assert row, "no song row on the page"
    assert "data-play-next" in row.group(0), (
        "no way to line a song up behind the one playing"
    )
    assert row.group(0).count("data-play-next") == 1, (
        "two controls for one decision"
    )

    script = SCRIPT.read_text()
    body = re.search(r"function showAsk\(row, queued\) \{(.*?)\n  \}",
                     script, re.S)
    assert body, "nothing ever writes the button's label"
    assert '"Take out"' in body.group(1), body.group(1)
    assert '"Play next"' in body.group(1), body.group(1)

    # And the click reads which of the two to do off the run itself,
    # rather than off a second attribute that could disagree with it.
    assert "lineup.indexOf(key) === -1" in script, (
        "the button's two meanings are decided somewhere other than the run"
    )


# ---------------------------------------------------------------------
# The listing's order
# ---------------------------------------------------------------------

def _order(setup: str, steps: str) -> dict:
    """Drive the shipped ordering against rows that are plain objects.

    `inPlayOrder` and `lay` only ever read `dataset.songId`, `parentNode`
    and identity, so a row can be an object — which is what lets this run
    with no DOM at all.
    """

    # Rows 50 pixels tall, stacked from the top, so a row's box follows
    # from where it stands — which is what lets the slide below be
    # measured rather than merely read.
    harness = """
const SLIDE_MS = 220;
const MAX_SLIDE_MS = 520;
const LANDED_MS = 900;
let queue = [];
class Fragment {
  constructor() { this.taken = []; }
  appendChild(row) { this.taken.push(row); }
}
const document = { createDocumentFragment: () => new Fragment() };
const bench = {
  children: [],
  laid: 0,
  get firstElementChild() { return bench.children[0] || null; },
  insertBefore(row, before) {
    const from = bench.children.indexOf(row);
    if (from !== -1) bench.children.splice(from, 1);
    const at = before ? bench.children.indexOf(before) : bench.children.length;
    bench.children.splice(at === -1 ? bench.children.length : at, 0, row);
    bench.laid += 1;
  },
};
const frames = [];
let justMoved = "d";
const window = {
  innerHeight: 10000,
  requestAnimationFrame(run) { frames.push(run); },
  setTimeout() {},
};
function row(key, id) {
  return {
    dataset: { songId: id || key, songKey: key },
    parentNode: bench,
    style: {},
    classList: { names: [], add(n) { this.names.push(n); },
                 remove(n) { this.names = this.names.filter(x => x !== n); } },
    get nextElementSibling() {
      return bench.children[bench.children.indexOf(this) + 1] || null;
    },
    getBoundingClientRect() {
      const at = bench.children.indexOf(this);
      return { top: at * 50, bottom: at * 50 + 50 };
    },
  };
}
function entry(key, id) { return { key, id: id || key }; }
""" + _source("land") + _source("slide") + _source("inPlayOrder") + _source("lay") + """
""" + setup + """
""" + steps + """
console.log(JSON.stringify({
  order: bench.children.map(r => r.dataset.songKey),
  // Nodes moved, not times the listing was rebuilt: putting only what is
  // out of place back is the difference between one insertBefore and
  // nine hundred, and the count is what says which happened.
  laid: bench.laid,
  // Where each row was put back to before being let go: the distance it
  // is about to travel, as the browser will animate it.
  inverted: bench.children
    .filter(r => r.style.transform)
    .map(r => r.dataset.songKey + ":" + r.style.transform.match(/-?\d+/)[0]),
  // The row the click moved, given a body for the journey.
  tinted: bench.children
    .filter(r => r.classList.names.includes("moving"))
    .map(r => r.dataset.songKey),
  frames: frames.length,
  settled: bench.settled,
  ms: bench.ms,
}));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr

    return json.loads(done.stdout)


LISTING = """
bench.children = ["a", "b", "c", "d", "e"].map(k => row(k));
queue = ["c", "a", "e", "b", "d"].map(k => entry(k));
"""


@needs_node
def test_the_listing_can_be_laid_in_the_order_it_plays():
    out = _order(LISTING, "lay(bench.children, inPlayOrder(bench.children));")

    assert out["order"] == ["c", "a", "e", "b", "d"], out
    # Two nodes out of five are out of place; the other three are left
    # exactly where they are.
    assert out["laid"] == 2, out


@needs_node
def test_laying_it_out_twice_moves_nothing_the_second_time():
    """A MutationObserver on #list calls `paint`, so a reorder that runs
    whether or not anything moved calls itself for ever: taking a node
    out and putting it back where it was is still a childList record."""

    out = _order(
        LISTING,
        "lay(bench.children, inPlayOrder(bench.children));"
        "const once = bench.laid;"
        "lay(bench.children, inPlayOrder(bench.children));"
        "lay(bench.children, inPlayOrder(bench.children));"
        "bench.settled = bench.laid === once;",
    )

    assert out["order"] == ["c", "a", "e", "b", "d"], out
    assert out["settled"], "it puts the listing back every single paint"


@needs_node
def test_each_row_is_put_back_where_it_was_before_being_let_go():
    """FLIP. A reorder is instant — no transition applies to a node that
    changed place — so each row is translated back to where it stood and
    then released, and the browser interpolates the journey it did not
    make.

    Rows fifty pixels tall here. Bringing "d" from the fourth place to
    the second sends it up two rows, and the two it displaces come down
    one each; everything else stands still and is not touched at all.
    """

    out = _order(
        """
        bench.children = ["a", "b", "c", "d", "e"].map(k => row(k));
        queue = ["a", "d", "b", "c", "e"].map(k => entry(k));
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["a", "d", "b", "c", "e"], out
    assert out["inverted"] == ["d:100", "b:-50", "c:-50"], (
        f"the rows are not put back where they came from: {out['inverted']}"
    )
    # And the one the click moved travels in a body of its own, alone.
    # The two that stepped aside move one row and need none.
    assert out["tinted"] == ["d"], out
    # And released on the next frame: setting the transform and clearing
    # it in one go lands both in a single style recalculation, and
    # nothing moves at all.
    assert out["frames"] == 1, out


@needs_node
def test_an_insertion_moves_one_node():
    """Rebuilding the listing into a fragment and re-appending it moved
    all 944 nodes whatever had changed — 94ms of node churn and 138ms of
    layout behind it, measured in the browser. A quarter of a second
    before the slide could begin, for one song changing place."""

    out = _order(
        """
        bench.children = ["a", "b", "c", "d", "e"].map(k => row(k));
        queue = ["a", "d", "b", "c", "e"].map(k => entry(k));
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["a", "d", "b", "c", "e"], out
    assert out["laid"] == 1, (
        f"{out['laid']} nodes moved to put one song in its place"
    )


# Run the frame the slide queued, then read back the duration it chose:
# it is a local, and the transition it writes is the only place it shows.
RELEASE = """
frames.forEach(run => run());
const carrier = bench.children.find(r => r.style.transition);
bench.ms = carrier ? Number(carrier.style.transition.match(/(\\d+)ms/)[1]) : 0;
"""


@needs_node
def test_a_long_journey_is_given_longer_to_be_watched():
    """A fixed 220ms is right for a row stepping aside and far too fast
    for one crossing the window: a thousand pixels in 220ms is
    seventy-five a frame, which reads as a flicker rather than as a
    journey — the row was measured moving and could not be seen to.

    Rows fifty pixels tall here, so bringing "z" from the fortieth place
    to the second is nineteen hundred pixels and takes the cap."""

    near = _order(
        """
        bench.children = ["a", "b", "c", "d"].map(k => row(k));
        queue = ["a", "d", "b", "c"].map(k => entry(k));
        justMoved = "d";
        """,
        "lay(bench.children, inPlayOrder(bench.children));" + RELEASE,
    )
    assert near["ms"] == 220, near

    keys = [str(n) for n in range(40)]
    far = _order(
        "bench.children = [" + ",".join(f'row("{k}")' for k in keys) + "];"
        'queue = ["0", "39"].concat('
        + ",".join(f'"{k}"' for k in keys[1:-1]) + ").map(k => entry(k));"
        'justMoved = "39";',
        "lay(bench.children, inPlayOrder(bench.children));" + RELEASE,
    )
    assert far["order"][1] == "39", far["order"][:4]
    assert far["ms"] == 520, f"a journey of {far['travel']}px took {far['ms']}ms"


@needs_node
def test_only_a_click_animates_the_reorder():
    """Shuffling sends every row to an unrelated place, and nine hundred
    rows crossing each other says nothing anyone could follow. An
    insertion is one row travelling and a handful stepping aside, which
    is what a slide shows — so the measuring only happens when a click
    is what moved something."""

    out = _order(
        """
        justMoved = null;
        bench.children = ["a", "b", "c", "d", "e"].map(k => row(k));
        queue = ["e", "d", "c", "b", "a"].map(k => entry(k));
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["e", "d", "c", "b", "a"], "the reorder still happens"
    assert out["inverted"] == [], "a shuffle is animated row by row"
    assert out["tinted"] == [], "a shuffle lifts a row nobody picked"
    assert out["frames"] == 0, out


@needs_node
def test_a_row_that_has_not_moved_is_never_touched():
    """A transform on every row of nine hundred, to animate the two that
    travelled, is nine hundred style writes and nine hundred needless
    transitions."""

    out = _order(
        """
        bench.children = ["a", "b", "c", "d"].map(k => row(k));
        queue = ["a", "b", "d", "c"].map(k => entry(k));
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["inverted"] == ["d:50", "c:-50"], out


@needs_node
def test_a_song_in_two_playlists_takes_two_places():
    """One video, two rows, two entries, two places — and each entry
    lands on its own row, not both on the first."""

    out = _order(
        """
        bench.children = [row("a"), row("x1", "x"), row("b"), row("x2", "x")];
        queue = [entry("x2", "x"), entry("a"),
                 entry("x1", "x"), entry("b")];
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["x2", "a", "x1", "b"], out


@needs_node
def test_rows_the_queue_never_saw_go_behind_in_their_own_order():
    """The queue is a snapshot of the rows at the moment you pressed
    play, so a listing filtered since then holds songs it never saw.
    Dropping them would be losing rows off the page."""

    out = _order(
        """
        bench.children = ["a", "b", "c", "d"].map(k => row(k));
        queue = ["c", "a"].map(k => entry(k));
        """,
        "lay(bench.children, inPlayOrder(bench.children));",
    )

    assert out["order"] == ["c", "a", "b", "d"], out

async def test_there_is_one_order_and_it_is_the_one_that_plays(tmp_path):
    """The listing is the play order. There is nothing to choose between,
    so there is no switch, and nothing to number, so there is no rank
    column: a row that comes after another comes after it.

    That was the whole job of the two things this removed — a sort
    selector and a figure on every row, both of them explaining a
    disagreement between what you saw and what you would hear."""

    import httpx

    from pypl2mp3.web.app import create_app

    _one_song(tmp_path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        page = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text

    for gone, why in (
        ('id="order"', "the sort selector is back"),
        ('class="rank"', "the rank column is back"),
        ('id="upnext"', "the strip is back, showing the run a second time"),
    ):
        assert gone not in page, why

    for gone in ("#order button", "td.rank-cell", "#upnext"):
        assert gone not in css, f"{gone} is still painted"

    # And the listing is laid in play order unconditionally, not when a
    # setting says so.
    script = SCRIPT.read_text()
    assert "lay(all, inPlayOrder(all));" in script, (
        "the listing is not put in the order it plays"
    )
    assert "listOrder" not in script, "a setting still chooses the order"


async def test_two_playlists_holding_one_video_are_two_rows(tmp_path):
    """The row is named by the playlist and the video, so the eight songs
    this repository holds twice are two rows the page can tell apart.

    The playlist and the video, and not the filename: junkizing renames
    the file, and the row that comes back to replace the one you clicked
    has to carry the id it was aimed at. A playlist holds a video once,
    so the pair is as unique as the path and survives every rename.
    """

    import httpx
    from mutagen.id3 import ID3, TXXX

    from pypl2mp3.web.app import create_app

    for playlist in ("Owner - Alpha [PL0000000000000000000000000000001]",
                     "Owner - Beta [PL0000000000000000000000000000002]"):
        folder = tmp_path / playlist
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "UNKNOWN - Something [aaaaaaaaaaa] (JUNK).mp3"
        path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)
        frames = ID3()
        frames.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
        frames.save(path)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        listing = (await client.get("/fragments/list")).text

    rows = re.findall(r'<tr id="song-([0-9a-f]{16})"[^>]*'
                      r'data-song-id="([^"]+)"[^>]*'
                      r'data-song-key="([^"]+)"', listing, re.S)

    assert len(rows) == 2, f"one video in two playlists gave {len(rows)} rows"

    (id_a, video_a, key_a), (id_b, video_b, key_b) = rows

    assert video_a == video_b == "aaaaaaaaaaa", "the video is the same one"
    assert key_a != key_b, (
        "both rows answer to one key, so the page cannot tell them apart"
    )
    # The row's own DOM id is that key, which is what htmx aims at.
    assert (id_a, id_b) == (key_a, key_b), (id_a, key_a)

    # And a key has to be usable as a selector: a playlist folder carries
    # spaces and brackets, and both end one early.
    assert re.fullmatch(r"[0-9a-f]{16}", key_a), key_a


async def test_the_queue_carries_both_of_a_row_s_names(tmp_path):
    """Read off the shipped source, because the node harness defines its
    own `queueFromRows` and so cannot answer for this one.

    That gap was not hypothetical: an edit to this function was lost, the
    whole suite stayed green, and every row in the browser went dark —
    nothing was marked playing, because the queue entries had no key to
    be marked by.
    """

    import httpx

    from pypl2mp3.web.app import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        script = (await client.get("/static/console.js")).text

    body = re.search(r"function queueFromRows\(\) \{(.*?)\n  \}", script, re.S)
    assert body, "queueFromRows moved"

    assert "id: row.dataset.songId" in body.group(1), body.group(1)
    assert "key: row.dataset.songKey" in body.group(1), (
        "an entry cannot say which row it came from"
    )


def test_the_key_is_the_playlist_id_and_the_video():
    """Stated once here, so the two halves cannot quietly become one —
    and so that the playlist half stays its id rather than the name of
    its folder, which YouTube can change under us."""

    import dataclasses

    from pypl2mp3.services.list_songs import SongSummary

    one = SongSummary(
        path=Path("Owner - Alpha [PL1]/A - B [vvvvvvvvvvv].mp3"),
        youtube_id="vvvvvvvvvvv", artist="A", title="B",
        playlist="Owner - Alpha [PL1]", duration="00:03:00", is_junk=False,
    )

    # Renaming the file — which is what junkizing does — leaves it alone.
    renamed = dataclasses.replace(
        one, path=Path("Owner - Alpha [PL1]/A - B [vvvvvvvvvvv] (JUNK).mp3"))
    assert renamed.key == one.key, "junkizing would move the row's own id"

    # Retitling the playlist on YouTube renames its folder here — the
    # check builds that name afresh from what YouTube answers — and the
    # key is the playlist's *id*, so it does not follow.
    retitled = dataclasses.replace(one, playlist="Owner - Alpha, live [PL1]")
    assert retitled.key == one.key, (
        "renaming a playlist would orphan every key derived from its name"
    )

    # Another playlist is another row.
    elsewhere = dataclasses.replace(one, playlist="Owner - Beta [PL2]")
    assert elsewhere.key != one.key

    # Another video in the same playlist, likewise.
    other = dataclasses.replace(one, youtube_id="wwwwwwwwwww")
    assert other.key != one.key


def _switch(order: str, asked: str) -> dict:
    """Run the shipped switch: what it lights, and what choosing does."""

    harness = f"""
let queue = [], index = 0, direction = 1, lineup = [];
const returns = new Map();
let rows = ["a", "b", "c", "d", "e"];
function entry(key) {{ return {{ key, id: key }}; }}
function queueFromRows() {{ return rows.map(id => entry(id)); }}
const played = [];
function setQueue(entries, startAt) {{
  queue = entries;
  played.push(entries.map(e => e.key).join(""));
  index = startAt > 0 ? startAt : 0;
}}

// Three buttons, one per order, as the shell renders them.
const buttons = ["youtube", "name", "shuffle"].map(function (name) {{
  return {{
    dataset: {{ playOrder: name }},
    pressed: null,
    setAttribute(attr, value) {{ if (attr === "aria-pressed") this.pressed = value; }},
  }};
}});

const orderField = {{ value: "{order}" }};
let requested = null;
const document = {{
  querySelectorAll: () => buttons,
  getElementById: (id) => (id === "filters" ? {{}} : null),
}};
const window = {{ htmx: {{ ajax: (verb, url) => {{ requested = url; }} }} }};

let playOrder = "{order}";
let orderAsked = false;
{_source("showOrder")}
{_source("chooseOrder")}
{_source("shuffled")}

// What the switch says about the order standing, before it is asked to
// change: the shell renders this on arrival, and showOrder is what keeps
// it true from then on.
showOrder();
const litOnArrival = buttons.filter(b => b.pressed === "true")
                            .map(b => b.dataset.playOrder);
chooseOrder("{asked}");

console.log(JSON.stringify({{
  litOnArrival,
  lit: buttons.filter(b => b.pressed === "true").map(b => b.dataset.playOrder),
  field: orderField.value,
  requested, orderAsked, played,
}}));
"""
    done = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=20
    )
    assert done.returncode == 0, done.stderr

    return json.loads(done.stdout)


@needs_node
@pytest.mark.parametrize("order", ["youtube", "name", "shuffle"])
def test_exactly_one_order_is_lit_and_it_is_the_one_playing(order):
    """Three buttons saying one thing between them. Two lit would be two
    claims about the order the songs are in, and none would leave the
    listing's order unaccounted for."""

    out = _switch(order, order)

    assert out["litOnArrival"] == [order], out


@needs_node
@pytest.mark.parametrize("order", ["youtube", "name"])
def test_the_orders_the_server_holds_are_asked_of_it(order):
    """The rows on screen are in the queue's order by now — a song lined
    up by hand is not where either of these two would put it — so the
    listing has to come back from the repository rather than be sorted
    out of the page."""

    out = _switch("shuffle", order)

    assert out["requested"] == "/fragments/list", out
    assert out["field"] == order, "the next refetch would undo the choice"
    assert out["orderAsked"], (
        "the listing arriving would not be taken as the queue"
    )
    assert out["played"] == [], (
        "the queue was rebuilt from rows that are about to be replaced"
    )


@needs_node
def test_a_random_order_is_made_here_and_asked_of_nobody():
    """There is nothing for a repository to hold: the order is made out
    of the rows that are on the page, once, when you ask for it."""

    out = _switch("youtube", "shuffle")

    assert out["requested"] is None, "a round trip for a coin toss"
    assert out["field"] == "shuffle", out
    assert not out["orderAsked"], (
        "the next listing to arrive for any reason would replace this one"
    )
    assert len(out["played"]) == 1, out
    assert sorted(out["played"][0]) == list("abcde"), (
        "shuffling lost or invented a song"
    )


@needs_node
def test_choosing_an_order_starts_it_from_the_top():
    """A reset, and it could be nothing else: an order *is* a queue, so
    choosing one discards whatever was lined up by hand — which is what
    Play all and Shuffle, the two buttons these three replaced, did."""

    source = SCRIPT.read_text()
    handler = re.search(
        r'if \(event\.target\.id !== "list" \|\| !orderAsked\) return;'
        r"(.*?)\n  \}\);",
        source, re.S,
    )

    assert handler, (
        "the listing arriving in a new order is claimed by some other "
        "condition than having been asked for — a filter keystroke swaps "
        "this same listing, and adopting that one restarts the music "
        "under whoever was typing"
    )
    assert "orderAsked = false;" in handler.group(1), (
        "the flag stands for the next listing to arrive to claim"
    )
    assert re.search(r"setQueue\(entries, 0\)", handler.group(1)), handler.group(1)

    # And at the swap: this reads the order the rows arrived in, and the
    # repaint between the swap and the settle lays them out in the order
    # of the queue being replaced. A settle-time reader would choose the
    # order that was already playing.
    hooked = source[:handler.start()].rfind("addEventListener(")
    assert 'addEventListener("htmx:afterSwap"' in source[hooked - 1:handler.start()], (
        source[hooked - 1:handler.start()]
    )


def test_a_request_that_brought_nothing_back_stops_expecting_a_listing():
    """Otherwise the flag stands, and the next listing to arrive for some
    other reason — a filter keystroke, a save — is taken for the order
    that was asked for and restarts the run under whoever was typing."""

    source = SCRIPT.read_text()

    hook = re.search(
        r'addEventListener\("htmx:afterRequest", function \(event\) \{\n'
        r"(.*?)\n  \}\);",
        source, re.S,
    )

    assert hook, "a request that failed leaves the flag standing"
    assert "successful === false" in hook.group(1), (
        "cleared on every request, the successful one included — which is "
        "the one whose listing the flag exists to claim"
    )
    assert "orderAsked = false" in hook.group(1), hook.group(1)


def test_the_listing_is_painted_again_once_htmx_has_settled_it():
    """htmx keeps an element's old attributes across a swap when the same
    id comes back — that is what lets a CSS transition run over arriving
    content — and writes the new markup's own `class` a moment later. The
    repaint on the swap fell inside that window, so the settle put out
    the light on the song still playing: a filter keystroke left the
    queue playing with nothing on the page saying which song."""

    source = SCRIPT.read_text()

    hook = re.search(
        r'addEventListener\("htmx:afterSettle", function \(event\) \{\n'
        r"(.*?)\n  \}\);",
        source, re.S,
    )

    assert hook, "nothing repaints the listing once its attributes are final"
    assert 'event.target.id === "list"' in hook.group(1), hook.group(1)
    assert "paint()" in hook.group(1), hook.group(1)
