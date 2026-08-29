"""Which TRCK frames are a misuse and which are a track number.

An older version of this tool stored the video id in `TRCK`, the frame
ID3 defines as the track number — 659 songs in one 944-song library carry
one. Every player that shows a track number shows the id instead.

The rule has to be narrow. Deleting every TRCK would also delete the real
track numbers of anything tagged by other software, and "this library
happens to have none" is not a reason to write a script that would.
"""

import importlib.util
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TRCK, TXXX
from mutagen.mp3 import MP3

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"


@pytest.fixture(scope="module")
def script():
    path = Path("scripts/clean_track_number.py")
    spec = importlib.util.spec_from_file_location("clean_trck", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _song(repo: Path, *, vid="aaaaaaaaaaa", track=None, id_tag=True):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"IAMX - Kiss [{vid}].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    if id_tag:
        tags.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    if track is not None:
        tags.add(TRCK(encoding=3, text=track))
    tags.save(path, v1=0, v2_version=3)

    return path


def test_a_track_number_that_is_the_video_id_is_a_misuse(script, tmp_path):
    path = _song(tmp_path, vid="r4L-YY5rtq4", track="r4L-YY5rtq4")
    tags = MP3(path).tags

    assert script.misused_track_number(tags, "r4L-YY5rtq4") == "r4L-YY5rtq4"


def test_a_real_track_number_is_left_alone(script, tmp_path):
    """The whole reason to compare against the id rather than to match a
    shape: an eleven-character track number is unlikely, and unlikely is
    not a reason to delete somebody's data."""

    for value in ("6", "6/16", "11", "aaaaaaaaaab"):
        path = _song(tmp_path, vid="aaaaaaaaaaa", track=value)
        tags = MP3(path).tags

        assert script.misused_track_number(tags, "aaaaaaaaaaa") == "", (
            f"the track number {value!r} was taken for a video id"
        )


def test_no_track_number_at_all(script, tmp_path):
    path = _song(tmp_path, track=None)

    assert script.misused_track_number(MP3(path).tags, "aaaaaaaaaaa") == ""


def test_the_id_is_read_from_the_tag_first(script, tmp_path):
    """The same two sources the model uses, in the same order — and the
    tag is the one the model writes on every save."""

    path = _song(tmp_path, vid="r4L-YY5rtq4")

    assert script.song_id(path, MP3(path).tags) == "r4L-YY5rtq4"


def test_the_filename_answers_when_the_tag_does_not(script, tmp_path):
    """A file with no id tag still carries it in brackets, which is what
    find_song_file searches. Without this the script would compare
    against nothing and remove nothing."""

    path = _song(tmp_path, vid="r4L-YY5rtq4", track="r4L-YY5rtq4",
                 id_tag=False)
    tags = MP3(path).tags

    assert script.song_id(path, tags) == "r4L-YY5rtq4"
    assert script.misused_track_number(tags, script.song_id(path, tags)) == (
        "r4L-YY5rtq4"
    )


def test_removing_it_leaves_the_id_where_the_model_reads_it(
    script, tmp_path, monkeypatch, capsys
):
    """The point of the check: the id survives in the tag the model reads
    and in the filename, so the frame being removed carries nothing that
    is not held twice elsewhere."""

    from pypl2mp3.libs.song import SongModel

    path = _song(tmp_path, vid="r4L-YY5rtq4", track="r4L-YY5rtq4")

    monkeypatch.setattr(
        "sys.argv",
        ["clean", "--repository", str(tmp_path)],
    )
    script.main()

    tags = MP3(path).tags
    assert tags.get("TRCK") is None, "the frame is still there"
    assert str(tags["TXXX:YouTube ID"].text[0]) == "r4L-YY5rtq4"
    assert SongModel(path).youtube_id == "r4L-YY5rtq4"


def test_a_dry_run_writes_nothing(script, tmp_path, monkeypatch):
    path = _song(tmp_path, vid="r4L-YY5rtq4", track="r4L-YY5rtq4")

    monkeypatch.setattr(
        "sys.argv",
        ["clean", "--repository", str(tmp_path), "--dry-run"],
    )
    script.main()

    assert MP3(path).tags.get("TRCK") is not None
