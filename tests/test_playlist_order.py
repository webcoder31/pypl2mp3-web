"""Mirroring the order a playlist has on YouTube.

The order belongs to the playlist, not to the recordings: the same video
in two playlists has two positions, and noting that one song moved would
otherwise mean rewriting eight hundred and ninety files. One file per
folder, rewritten whole by every check.
"""

import dataclasses
import json
import re
from pathlib import Path

import pytest

from pypl2mp3.services.list_songs import SongSummary, in_playlist_order
from pypl2mp3.services.playlist_order import FILENAME, read_order, write_order

ALPHA = "Owner - Alpha [PL0000000000000000000000000000001]"
BETA = "Owner - Beta [PL0000000000000000000000000000002]"


def _song(vid: str, playlist: str, artist: str = "A") -> SongSummary:
    return SongSummary(
        path=Path(playlist) / f"{artist} - T [{vid}].mp3",
        youtube_id=vid, artist=artist, title="T",
        playlist=playlist, duration="00:03:00", is_junk=False,
    )


def _repo(tmp_path: Path) -> Path:
    for name in (ALPHA, BETA):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)

    return tmp_path


def test_an_unread_playlist_is_not_an_empty_one(tmp_path):
    """None and not an empty mapping, and the difference decides what the
    listing draws: no file means nobody has looked, so nothing is out of
    order and nothing is missing. An empty order would mean a playlist
    YouTube says is empty — and every song in the folder orphaned."""

    assert read_order(_repo(tmp_path) / ALPHA) is None


def test_the_rank_is_the_position_and_starts_at_one(tmp_path):
    """One-based, so that a rank is never falsy — `if song.playlist_rank`
    reads as "it has one" all over the sort below."""

    folder = _repo(tmp_path) / ALPHA
    write_order(folder, "PL1", ["aaa", "bbb", "ccc"])

    assert read_order(folder) == {"aaa": 1, "bbb": 2, "ccc": 3}


def test_it_is_moved_into_place_and_leaves_nothing_behind(tmp_path):
    """A check interrupted halfway must not leave a truncated file: the
    listing would silently order itself by half a playlist."""

    folder = _repo(tmp_path) / ALPHA
    write_order(folder, "PL1", ["aaa"])
    write_order(folder, "PL1", ["bbb", "ccc"])

    assert sorted(p.name for p in folder.iterdir()) == [FILENAME]
    assert read_order(folder) == {"bbb": 1, "ccc": 2}


@pytest.mark.parametrize("content", ["", "{", "[]", '{"order": "aaa"}'])
def test_a_file_nobody_can_read_is_no_file_at_all(tmp_path, content):
    """It is a convenience the next check rebuilds. Nothing here is worth
    an error a caller has to handle."""

    folder = _repo(tmp_path) / ALPHA
    (folder / FILENAME).write_text(content, encoding="utf-8")

    assert read_order(folder) is None


def test_the_listing_follows_the_playlist_and_orphans_go_last(tmp_path):
    """Songs the playlist still holds first, in its order; what it has
    dropped at the end, marked."""

    repo = _repo(tmp_path)
    write_order(repo / ALPHA, "PL1", ["a3", "a1"])

    out = in_playlist_order(repo, [
        _song("a1", ALPHA, "Aa"), _song("a2", ALPHA, "Ab"),
        _song("a3", ALPHA, "Ac"),
    ])

    assert [s.youtube_id for s in out] == ["a3", "a1", "a2"]
    assert [s.playlist_rank for s in out] == [1, 2, None]
    assert [s.off_playlist for s in out] == [False, False, True]


def test_a_playlist_nobody_checked_keeps_its_order_and_no_marks(tmp_path):
    """Not knowing where a song stands is not the same as knowing it is
    gone — and a single sort key would have grouped an unchecked
    repository's whole listing by folder instead of leaving it
    alphabetical."""

    repo = _repo(tmp_path)
    songs = [_song("b1", BETA, "Ba"), _song("a1", ALPHA, "Aa"),
             _song("b2", BETA, "Bb")]

    out = in_playlist_order(repo, songs)

    assert [s.youtube_id for s in out] == ["b1", "a1", "b2"], (
        "an unchecked repository was reordered"
    )
    assert not any(s.off_playlist for s in out)


def test_two_playlists_are_grouped_in_the_order_the_nav_lists_them(tmp_path):
    repo = _repo(tmp_path)
    write_order(repo / BETA, "PL2", ["b1"])
    write_order(repo / ALPHA, "PL1", ["a1"])

    out = in_playlist_order(repo, [_song("b1", BETA), _song("a1", ALPHA)])

    assert [s.youtube_id for s in out] == ["a1", "b1"], (
        "Alpha comes before Beta, whichever was checked first"
    )


def test_the_check_records_the_order_it_read(tmp_path, monkeypatch):
    """The one moment the whole remote playlist is in hand, in its own
    order, and it cost a single request."""

    from types import SimpleNamespace

    from pypl2mp3.ports.progress import ProgressPort
    from pypl2mp3.services import check_new_songs as service

    # Eleven characters: that is what an id is, and both the url and the
    # filename readers say so by answering None to anything else.
    here, there = "aaaaaaaaaaa", "bbbbbbbbbbb"

    folder = _repo(tmp_path) / ALPHA
    (folder / f"A - T [{there}].mp3").write_bytes(
        b"\xff\xfb\x90\xc0" + b"\x00" * 413)

    # The `?v=` form, which is what pytubefix yields and the only one
    # `get_song_id_from_url` reads — a `youtu.be/<id>` url answers None,
    # and this test quietly checked an empty playlist until it did not.
    monkeypatch.setattr(service, "Playlist", lambda url: SimpleNamespace(
        video_urls=[f"https://www.youtube.com/watch?v={here}",
                    f"https://www.youtube.com/watch?v={there}"],
        owner="Owner", title="Alpha",
    ))

    class Quiet(ProgressPort):
        def __getattr__(self, name):
            return lambda *a, **k: None

    report = service.check_new_songs(
        tmp_path, "PL0000000000000000000000000000001", Quiet()
    )

    assert report.missing == [here]
    assert read_order(folder) == {here: 1, there: 2}

    said = json.loads((folder / FILENAME).read_text(encoding="utf-8"))
    assert said["playlist"] == "PL0000000000000000000000000000001"


async def test_the_row_marks_a_song_its_playlist_has_dropped(tmp_path):
    """Kept and listed — the file is yours, and a song a playlist dropped
    upstream is exactly the one you might want to know about — but at the
    end and marked, because it has no place in the order the rest is in.
    """

    import httpx
    from mutagen.id3 import ID3, TXXX

    from pypl2mp3.web.app import create_app

    folder = tmp_path / ALPHA
    folder.mkdir(parents=True)

    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        path = folder / f"ARTIST - Song {vid} [{vid}].mp3"
        path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)
        frames = ID3()
        frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
        frames.save(path)

    # Only the second is still in the playlist.
    write_order(folder, "PL0000000000000000000000000000001", ["bbbbbbbbbbb"])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        listing = (await client.get("/fragments/list")).text
        css = (await client.get("/static/console.css")).text

    ids = re.findall(r'data-song-id="(\w+)"', listing)
    assert ids == ["bbbbbbbbbbb", "aaaaaaaaaaa"], (
        f"the dropped song is not last: {ids}"
    )

    rows = re.findall(r"<tr .*?</tr>", listing, re.S)
    assert "off-playlist" not in rows[0], "a song still in the playlist is marked"
    assert "off-playlist" in rows[1], "the dropped song is not marked"

    # Painted, and not merely classed.
    rule = re.search(r"\n\.row-meta \.off-playlist \{([^}]*)\}", css)
    assert rule and "var(--junk)" in rule.group(1), (
        "the mark is a class nothing paints, or it is not the colour the "
        "page uses for a file that wants a decision"
    )
