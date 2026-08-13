"""Repairing a junk song's metadata, without calling Shazam."""

from pathlib import Path

import pytest
from mutagen.id3 import ID3, TXXX

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
