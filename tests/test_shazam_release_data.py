"""What Shazam says about the release, and how it reaches a page.

Shazam answers with more than an artist and a title. The album, the
publisher and the year arrive as display rows under `sections`, addressed
by their own `title`; the genre sits on the track. All four are optional,
and the rows are ordered as Shazam feels like ordering them, so every one
of them is read by name and every one of them may be missing.

They land in the standard ID3 frames — TALB, TPUB, TDRC, TCON — rather
than in TXXX customs: every player and every library already knows how to
read those, which is what they are for.
"""

from pathlib import Path

from pypl2mp3.libs.song import SongModel
from pypl2mp3.services.list_songs import SongSummary


def _shazam_answer(rows, genre=None):
    """A track shaped the way the real payload is shaped."""

    track = {
        "title": "Children of the Sky",
        "subtitle": "...And You Will Know Us By the Trail of Dead",
        "sections": [{"type": "SONG", "metadata": rows}],
    }
    if genre is not None:
        track["genres"] = {"primary": genre}
    return track


def test_reads_the_four_fields_from_a_real_shaped_answer():
    """The shape here is copied from one measured response, rows and all."""

    track = _shazam_answer(
        [
            {"title": "Album", "text": "X: The Godless Void and Other Stories"},
            {"title": "Label", "text": "InsideOutMusic"},
            {"title": "Released", "text": "2019"},
        ],
        genre="Rock",
    )

    assert SongModel._release_data(track) == {
        "album": "X: The Godless Void and Other Stories",
        "publisher": "InsideOutMusic",
        "year": "2019",
        "genre": "Rock",
    }


def test_reads_the_rows_by_name_and_not_by_position():
    """The order is Shazam's to choose, and it is display copy."""

    track = _shazam_answer(
        [
            {"title": "Released", "text": "1999"},
            {"title": "Album", "text": "Madonna"},
        ]
    )

    assert SongModel._release_data(track) == {
        "year": "1999",
        "album": "Madonna",
    }


def test_absent_fields_are_absent_rather_than_empty():
    """The result is splatted into update_state, where False means "keep"
    and None means "clear". A key that is present with an empty value
    would wipe whatever the file already carried."""

    assert SongModel._release_data({}) == {}
    assert SongModel._release_data(_shazam_answer([], genre="")) == {}
    assert SongModel._release_data(
        _shazam_answer([{"title": "Album", "text": "   "}])
    ) == {}
    # A row Shazam sends that means nothing here.
    assert SongModel._release_data(
        _shazam_answer([{"title": "Explicit", "text": "No"}])
    ) == {}


def test_the_non_breaking_spaces_are_squeezed_out():
    """Shazam answers with them inside album names, and they survive into
    the tag and then into every search that expects a space."""

    track = _shazam_answer(
        [{"title": "Album", "text": "X:\u00a0The Godless\u00a0Void"}]
    )

    assert SongModel._release_data(track) == {
        "album": "X: The Godless Void"
    }


def _summary(**release):
    return SongSummary(
        path=Path("x.mp3"),
        youtube_id="aaaaaaaaaaa",
        artist="IAMX",
        title="Kiss",
        playlist="Owner - Alpha [PL000]",
        duration="00:03:03",
        is_junk=False,
        **release,
    )


def test_the_release_line_is_joined_where_the_parts_are_known():
    """Assembled in the summary and not in the template: the parts are
    each optional, and a template putting separators between holes is
    where a stray middot comes from."""

    assert _summary(
        album="Madonna", year="1983", genre="Pop", publisher="Sire"
    ).release == "Madonna · 1983 · Pop · Sire"

    assert _summary(year="1983").release == "1983"
    assert _summary(album="Madonna", genre="Pop").release == "Madonna · Pop"
    assert _summary().release == ""


def test_the_release_line_does_not_collide_with_the_display_label():
    """ID3 and Shazam both call the publisher a "label", and the summary
    already has one — the artist-and-title line three templates read.
    Naming the field `label` would have landed the clash there, where
    nothing on the model's side would look wrong."""

    view = _summary(publisher="Sire")

    assert view.label == "IAMX - Kiss"
    assert view.publisher == "Sire"
    assert not hasattr(SongSummary, "label_publisher")  # no second name


def test_the_four_fields_survive_a_round_trip_through_a_real_file(tmp_path):
    """Written as standard frames, read back on the next open. The point
    of TALB/TPUB/TDRC/TCON over TXXX customs is that anything else
    reading this file finds them too."""

    from mutagen.mp3 import MP3

    # MPEG-1 Layer III frames, 128 kbps / 44.1 kHz / mono, 417 bytes
    # each. SongModel opens the file with mutagen, and one frame is not
    # enough for it to sync — eight is what the other suites write.
    frame = b"\xff\xfb\x90\xc0" + b"\x00" * 413
    folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
    folder.mkdir(parents=True)
    song_file = folder / "IAMX - Kiss [aaaaaaaaaaa].mp3"
    song_file.write_bytes(frame * 8)

    song = SongModel(song_file)
    assert (song.album, song.publisher, song.year, song.genre) == (
        None, None, None, None
    )

    song.update_state(
        album="Madonna", publisher="Sire", year="1983", genre="Pop"
    )

    frames = MP3(song_file).tags
    assert str(frames["TALB"].text[0]) == "Madonna"
    assert str(frames["TPUB"].text[0]) == "Sire"
    assert str(frames["TDRC"].text[0]) == "1983"
    assert str(frames["TCON"].text[0]) == "Pop"

    again = SongModel(song_file)
    assert (again.album, again.publisher, again.year, again.genre) == (
        "Madonna", "Sire", "1983", "Pop"
    )

    # And they go when the song is reset, like everything else it holds.
    again.reset_state()
    left = MP3(song_file).tags
    assert not any(left.get(f) for f in ("TALB", "TPUB", "TDRC", "TCON"))


def test_frames_this_program_never_set_are_left_alone(tmp_path):
    """Before these four fields existed, update_id3_tags never mentioned
    TALB, TPUB, TDRC or TCON, so whatever a downloaded file carried
    survived every save untouched. Now that they are written they can
    also be deleted, which is a way to lose data that did not exist
    before — nine songs in one 944-song library carry a full set of
    release frames that never came from Shazam.

    They are read on the first open and written back on the next save.
    """

    from mutagen.id3 import ID3, TALB, TPUB, TDRC, TCON, TPE1, TXXX
    from mutagen.mp3 import MP3

    frame = b"\xff\xfb\x90\xc0" + b"\x00" * 413
    folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
    folder.mkdir(parents=True)
    song_file = folder / "AKHENATON - Mon texte [7aUWJQBekwY].mp3"
    song_file.write_bytes(frame * 8)

    # Tagged by something else entirely, the way a download can arrive.
    tags = ID3()
    tags.add(TPE1(encoding=3, text="AKHENATON"))
    tags.add(TALB(encoding=3, text="Je suis en vie"))
    tags.add(TPUB(encoding=3, text="Universal Music Division"))
    tags.add(TDRC(encoding=3, text="2014"))
    tags.add(TCON(encoding=3, text="Hip-Hop/Rap"))
    tags.add(TXXX(encoding=3, desc="YouTube ID", text="7aUWJQBekwY"))
    tags.save(song_file, v1=0, v2_version=3)

    song = SongModel(song_file)
    assert song.album == "Je suis en vie"
    assert song.publisher == "Universal Music Division"
    assert song.year == "2014"
    assert song.genre == "Hip-Hop/Rap"

    # An ordinary save, mentioning none of them.
    song.update_state(title="Mon texte")

    kept = MP3(song_file).tags
    assert str(kept["TALB"].text[0]) == "Je suis en vie"
    assert str(kept["TPUB"].text[0]) == "Universal Music Division"
    assert str(kept["TDRC"].text[0]) == "2014"
    assert str(kept["TCON"].text[0]) == "Hip-Hop/Rap"
