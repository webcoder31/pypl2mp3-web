"""Repairing a junk song's metadata, without calling Shazam."""

from pathlib import Path

import pytest
from mutagen.id3 import ID3, APIC, TXXX

from pypl2mp3.services.fix_junks import (
    FixProposal,
    SongNotFound,
    apply_fix,
    propose_fix,
)
from pypl2mp3.services.list_songs import list_songs

from tests.doubles import FakeProgress

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_junk(repo: Path, vid: str = "aaaaaaaaaaa") -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"UNKNOWN - Something [{vid}] (JUNK).mp3"
    path.write_bytes(_MP3_FRAME * 8)

    # A file imported by pypl2mp3 carries its YouTube id as a tag. Without
    # it, merely constructing a SongModel rewrites the file, and a
    # read-only operation would look like it had side effects.
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.save(path)

    return path


def _fake_shazam(artist: str, title: str, url: str = "", score: float = 88.0):
    """Stand in for SongModel.shazam_song, which hits the network."""

    async def shazam(self, shazam_match_threshold=50, **kwargs):
        self.shazam_artist = artist
        self.shazam_title = title
        self.shazam_cover_art_url = url
        self.shazam_match_score = score

    return shazam


async def test_the_proposal_reports_what_shazam_heard(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "pypl2mp3.libs.song.SongModel.shazam_song",
        _fake_shazam("THE PHARCYDE", "Passin Me By"),
    )
    _make_junk(tmp_path)

    proposal = await propose_fix(tmp_path, "aaaaaaaaaaa", FakeProgress())

    assert isinstance(proposal, FixProposal)
    assert proposal.shazam_artist == "THE PHARCYDE"
    assert proposal.shazam_title == "Passin Me By"
    assert proposal.shazam_match_score == 88.0
    assert proposal.matched is True


async def test_proposing_writes_nothing(tmp_path, monkeypatch):
    """The user has not decided yet; the file must be untouched."""

    monkeypatch.setattr(
        "pypl2mp3.libs.song.SongModel.shazam_song",
        _fake_shazam("THE PHARCYDE", "Passin Me By"),
    )
    path = _make_junk(tmp_path)
    before = path.read_bytes()

    await propose_fix(tmp_path, "aaaaaaaaaaa", FakeProgress())

    assert path.exists(), "the file was renamed by a read-only operation"
    assert path.read_bytes() == before, "the file was rewritten"


async def test_an_unmatched_song_says_so_rather_than_proposing_blanks(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "pypl2mp3.libs.song.SongModel.shazam_song", _fake_shazam("", "", score=0)
    )
    _make_junk(tmp_path)

    proposal = await propose_fix(tmp_path, "aaaaaaaaaaa", FakeProgress())

    assert proposal.matched is False


async def test_applying_writes_the_tags_and_drops_the_junk_suffix(tmp_path):
    _make_junk(tmp_path)
    assert len(list_songs(tmp_path, junk_only=True)) == 1

    result = await apply_fix(
        tmp_path, "aaaaaaaaaaa", "THE PHARCYDE", "Passin Me By"
    )

    assert "(JUNK)" not in result.filename
    assert list_songs(tmp_path, junk_only=True) == []

    written = tmp_path / PLAYLIST / result.filename
    frames = ID3(written)
    assert frames.getall("TPE1")[0].text[0] == "THE PHARCYDE"
    assert frames.getall("TIT2")[0].text[0] == "Passin Me By"


async def test_the_user_can_override_what_shazam_proposed(tmp_path):
    """The whole point of the form: Shazam is a suggestion, not a verdict."""

    _make_junk(tmp_path)

    result = await apply_fix(
        tmp_path, "aaaaaaaaaaa", "MY ARTIST", "My Title"
    )

    assert result.current_artist == "MY ARTIST"
    assert result.current_title == "My Title"

    written = tmp_path / PLAYLIST / result.filename
    assert ID3(written).getall("TPE1")[0].text[0] == "MY ARTIST"


async def test_an_empty_cover_field_leaves_the_stored_url_alone(tmp_path):
    """The field says "leave empty to keep the current one", and leaving
    it empty used to delete the URL.

    It was invisible: the embedded picture is a separate frame and
    survived, so the panel looked right while the file had lost the only
    record of where the picture came from. A song saved twice could no
    longer fetch its own cover.

    `update_state` already distinguishes "clear this" from "do not touch
    it" — None against False — and this passed the wrong one.
    """

    path = _make_junk(tmp_path)

    frames = ID3(path)
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
    frames.add(TXXX(encoding=3, desc="Cover art URL",
                    text="https://example.invalid/art.jpg"))
    frames.save(path)

    result = await apply_fix(tmp_path, "aaaaaaaaaaa", "THE PHARCYDE",
                             "Passin Me By", cover_art_url="")

    written = ID3(tmp_path / PLAYLIST / result.filename)
    kept = written.getall("TXXX:Cover art URL")

    assert kept, "saving without touching the cover deleted its URL"
    assert kept[0].text[0] == "https://example.invalid/art.jpg"


async def test_an_empty_name_still_means_empty(tmp_path):
    """The cover is the exception, not the rule. A song with no artist and
    no title is what junk *is*, so clearing those has to stay possible —
    the same "or None" that was wrong for the cover is right here."""

    _make_junk(tmp_path)
    await apply_fix(tmp_path, "aaaaaaaaaaa", "THE PHARCYDE", "Passin Me By")

    result = await apply_fix(tmp_path, "aaaaaaaaaaa", "", "")

    written = ID3(tmp_path / PLAYLIST / result.filename)
    assert not written.getall("TPE1"), "the artist could not be cleared"
    assert not written.getall("TIT2"), "the title could not be cleared"


def _catch_downloads(monkeypatch, fail: bool = False):
    """Stand in for the cover download, and count it.

    A one-pixel JPEG is enough: nothing here looks at the picture, only
    at whether it was fetched at all.
    """

    import urllib.request

    calls = []
    jpeg = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300"
        + "ff" * 64
        + "ffd9"
    )

    def fetch(url, filename, hook=None):
        calls.append(url)
        if fail:
            raise OSError("no route to host")
        Path(filename).write_bytes(jpeg)
        return filename, None

    monkeypatch.setattr(urllib.request, "urlretrieve", fetch)
    return calls


async def test_a_new_cover_url_actually_fetches_the_picture(
    tmp_path, monkeypatch
):
    """It did not, and nothing said so. `update_cover_art` decides whether
    to download by comparing the URL it was given against the one recorded
    in the file — and `update_state` had already written the new URL
    there, so the two were always equal.

    Three saves with three different URLs produced three updated URLs and
    zero downloads: the file kept claiming a picture it no longer had, and
    the panel kept showing the old one.
    """

    _make_junk(tmp_path)
    calls = _catch_downloads(monkeypatch)

    await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                    cover_art_url="https://example.invalid/first.jpg")
    assert calls == ["https://example.invalid/first.jpg"]

    await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                    cover_art_url="https://example.invalid/second.jpg")
    assert calls[-1] == "https://example.invalid/second.jpg", (
        "a changed cover URL did not fetch anything"
    )
    assert len(calls) == 2


async def test_the_same_cover_url_twice_fetches_once(
    tmp_path, monkeypatch
):
    """The comparison is worth keeping — it is only the order that was
    wrong. Asking for the picture already embedded should cost nothing."""

    _make_junk(tmp_path)
    calls = _catch_downloads(monkeypatch)

    for _ in range(3):
        await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                        cover_art_url="https://example.invalid/same.jpg")

    assert len(calls) == 1, f"the same picture was fetched {len(calls)} times"


async def test_a_cover_that_cannot_be_fetched_leaves_the_song_alone(
    tmp_path, monkeypatch
):
    """The names used to be written first, so a failed download left the
    file carrying a new artist, a new title and a URL for a picture it had
    never received. Fetching first makes it all-or-nothing."""

    path = _make_junk(tmp_path)
    _catch_downloads(monkeypatch, fail=True)

    with pytest.raises(Exception):
        await apply_fix(tmp_path, "aaaaaaaaaaa", "THE PHARCYDE",
                        "Passin Me By",
                        cover_art_url="https://example.invalid/gone.jpg")

    assert path.exists(), "the song was renamed on a failed save"
    frames = ID3(path)
    assert not frames.getall("TPE1"), "the artist was written anyway"
    assert not frames.getall("TXXX:Cover art URL"), (
        "the file claims a picture it never received"
    )


async def test_the_file_records_where_its_picture_came_from(
    tmp_path, monkeypatch
):
    """Two URLs, and they answer different questions. `Cover art URL` is
    what was last asked for; `Stored cover art URL` is where the picture
    actually embedded in the file came from.

    They differ exactly when a request was written but never carried out,
    and telling them apart is what makes "is this already the picture
    being asked for?" answerable. The old CLI kept both and compared
    against the record; the refactor kept writing it and started comparing
    against the request, so the two were always equal and nothing was ever
    refetched.
    """

    _make_junk(tmp_path)
    calls = _catch_downloads(monkeypatch)

    await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                    cover_art_url="https://example.invalid/one.jpg")

    frames = ID3(next(tmp_path.rglob("*.mp3")))
    assert frames.getall("TXXX:Stored cover art URL")[0].text[0] == (
        "https://example.invalid/one.jpg"
    )
    assert len(calls) == 1


async def test_the_record_survives_a_save_that_is_not_about_the_cover(
    tmp_path, monkeypatch
):
    """update_id3_tags wipes every TXXX before rewriting the ones it
    knows, and this was not among them — so the record written on each
    download lasted exactly until the next save of anything at all. One
    file in a 944-song library still had it.

    Without it the comparison finds nothing, decides "unknown", and
    refetches a picture the file already carries.
    """

    _make_junk(tmp_path)
    calls = _catch_downloads(monkeypatch)

    await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                    cover_art_url="https://example.invalid/one.jpg")

    # A save about the names only.
    await apply_fix(tmp_path, "aaaaaaaaaaa", "OTHER", "NAME")

    frames = ID3(next(tmp_path.rglob("*.mp3")))
    assert frames.getall("TXXX:Stored cover art URL"), (
        "an ordinary save dropped the record"
    )

    # And the same picture is still not fetched again.
    await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                    cover_art_url="https://example.invalid/one.jpg")

    assert len(calls) == 1, f"the picture was fetched {len(calls)} times"


async def test_a_picture_of_unknown_origin_is_fetched_once(
    tmp_path, monkeypatch
):
    """Every file tagged before the record was kept has none. Unknown has
    to mean fetch — the alternative is trusting a request that may never
    have been carried out. It costs one download, after which the file
    knows and stops paying."""

    path = _make_junk(tmp_path)

    # A cover with no record of where it came from, which is what 943
    # songs in one library look like.
    frames = ID3(path)
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
    frames.add(TXXX(encoding=3, desc="Cover art URL",
                    text="https://example.invalid/one.jpg"))
    frames.add(APIC(encoding=3, desc="Cover art", mime="image/jpg", type=3,
                    data=b"\xff\xd8\xff\xe0" + b"\x00" * 32))
    frames.save(path, v1=0, v2_version=3)

    calls = _catch_downloads(monkeypatch)

    await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                    cover_art_url="https://example.invalid/one.jpg")
    assert len(calls) == 1, "an unknown origin was taken on trust"

    await apply_fix(tmp_path, "aaaaaaaaaaa", "A", "B",
                    cover_art_url="https://example.invalid/one.jpg")
    assert len(calls) == 1, "the file did not learn"


async def test_an_unknown_song_raises_rather_than_touching_anything(tmp_path):
    spared = _make_junk(tmp_path)

    with pytest.raises(SongNotFound):
        await apply_fix(tmp_path, "zzzzzzzzzzz", "A", "B")

    assert spared.exists()


async def test_the_proposal_reports_progress(tmp_path, monkeypatch):
    """Shazam takes seconds and can wait 15 more; silence reads as a hang."""

    monkeypatch.setattr(
        "pypl2mp3.libs.song.SongModel.shazam_song",
        _fake_shazam("ARTIST", "Title"),
    )
    _make_junk(tmp_path)
    progress = FakeProgress()

    await propose_fix(tmp_path, "aaaaaaaaaaa", progress)

    kinds = [event[0] for event in progress.events]
    assert "stage_started" in kinds
    assert "stage_done" in kinds
    assert "song_identified" in kinds
