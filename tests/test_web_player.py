"""Playing a whole selection, the way the CLI's `play` does."""

import json
import re
from pathlib import Path

import httpx

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, artist: str, title: str, vid: str, junk=False):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    path = folder / f"{artist} - {title} [{vid}]{suffix}.mp3"
    path.write_bytes(_MP3_FRAME * 8)


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _queue(body: str) -> list[dict]:
    block = re.search(
        r'<script type="application/json" id="queue-data"[^>]*>(.*?)</script>',
        body,
        re.DOTALL,
    )
    assert block, "the page carries no queue"

    return json.loads(block.group(1))


async def test_it_queues_the_whole_selection(tmp_path):
    for i in range(3):
        _make_song(tmp_path, "ARTIST", f"Song {i}", f"vid{i:07d}")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/player")).text

    queue = _queue(body)
    assert len(queue) == 3
    assert all(entry["youtube_id"] and entry["label"] for entry in queue)


async def test_the_queue_honours_the_same_filters_as_the_listing(tmp_path):
    _make_song(tmp_path, "WU-TANG CLAN", "Tearz", "aaaaaaaaaaa")
    _make_song(tmp_path, "DIRE STRAITS", "Sultans", "bbbbbbbbbbb")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/player?q=wu+tang+tearz&match=45")).text

    queue = _queue(body)
    assert [entry["youtube_id"] for entry in queue] == ["aaaaaaaaaaa"]


async def test_junk_only_reaches_the_player_too(tmp_path):
    _make_song(tmp_path, "ARTIST", "Good", "aaaaaaaaaaa")
    _make_song(tmp_path, "ARTIST", "Bad", "bbbbbbbbbbb", junk=True)

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/player?junk=1")).text

    assert [entry["youtube_id"] for entry in _queue(body)] == ["bbbbbbbbbbb"]


async def test_shuffling_happens_server_side(tmp_path):
    """The CLI's -s reshuffles per run; reloading should too."""

    for i in range(30):
        _make_song(tmp_path, "ARTIST", f"Song {i}", f"vid{i:07d}")

    app = create_app(tmp_path)
    async with _client(app) as client:
        plain = _queue((await client.get("/player")).text)
        first = _queue((await client.get("/player?shuffle=1")).text)
        second = _queue((await client.get("/player?shuffle=1")).text)

    ordered = [entry["youtube_id"] for entry in plain]
    assert [entry["youtube_id"] for entry in first] != ordered, (
        "shuffle returned the natural order"
    )
    assert sorted(entry["youtube_id"] for entry in first) == sorted(ordered), (
        "shuffling must not drop or invent songs"
    )
    assert [e["youtube_id"] for e in first] != [
        e["youtube_id"] for e in second
    ], "two shuffles in a row gave the same order"


async def test_the_visible_queue_matches_the_one_the_script_plays(tmp_path):
    """player.js highlights list.children[index] — they share an index."""

    for i in range(6):
        _make_song(tmp_path, f"ARTIST {i}", f"Song {i}", f"vid{i:07d}")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/player?shuffle=1")).text

    rows = re.findall(r"<li>(.*?)</li>", body, re.DOTALL)
    queue = _queue(body)

    assert len(rows) == len(queue), "the list and the queue disagree in size"
    for row, entry in zip(rows, queue):
        assert entry["label"] in row, (
            f"row {row.strip()!r} does not show {entry['label']!r} — "
            "clicking it would play a different song"
        )


async def test_the_player_script_is_served_locally(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/player")).text
        script = await client.get("/static/player.js")

    assert "/static/player.js" in page
    assert script.status_code == 200
    assert b"ArrowRight" in script.content, "no keyboard navigation"
    assert b"ArrowLeft" in script.content

    # Offline tool: every asset the page pulls must come from us. The audio
    # element's own source is a /songs/… route, so any absolute src here
    # would be a CDN.
    for src in re.findall(r'<(?:script|link|img)[^>]*?(?:src|href)="([^"]+)"', page):
        assert not src.startswith(("http://", "https://", "//")), src


async def test_the_script_covers_the_cli_s_controls(tmp_path):
    """Parity with `play`: next, previous, pause, video, quit."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/player.js")).text

    for key in ("ArrowRight", "ArrowLeft", "Tab", "Escape"):
        assert f'"{key}"' in script, key
    assert '" "' in script, "no space bar handling"
    # The quoted event name, not the bare word: "xended" contains "ended"
    # and would sail through a substring check.
    assert 'addEventListener("ended"' in script, (
        "the queue does not advance when a song finishes"
    )


async def test_the_listing_offers_play_and_shuffle(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/songs")).text

    assert "/player?" in body
    assert "shuffle=1" in body


async def test_an_empty_selection_says_so_instead_of_a_dead_player(tmp_path):
    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/player?q=zzqxwv&match=95")).text

    assert "No songs match" in body
    assert "queue-data" not in body, "an empty queue must not be shipped"
