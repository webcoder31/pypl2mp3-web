"""The terminal is the same act as the form, through a different door.

`fix-junks -p` asks for artist, title and cover in the terminal and saves
what it is given. It wrote them as `legacy` — the document's word for
"nobody knows who decided this" — over values somebody had just typed.

The consequence was not in the terminal but in the console: the panel
warns before Ask Shazam that a match would replace what was set by hand,
and a song fixed from the terminal carried no such mark. Two doors onto
one act, and the document could tell them apart.
"""

import asyncio
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TPE1, TIT2, TXXX

from pypl2mp3.commands.fix_junks import JunkSongTagger
from pypl2mp3.libs.song import SongModel

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
VID = "aaaaaaaaaaa"


@pytest.fixture
def junk(tmp_path):
    folder = tmp_path / PLAYLIST
    folder.mkdir(parents=True)
    path = folder / f"IAMX - Kiss [{VID}] (JUNK).mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text=VID))
    tags.add(TPE1(encoding=3, text="IAMX"))
    tags.add(TIT2(encoding=3, text="Kiss"))
    tags.save(path, v1=0, v2_version=3)

    return path


def _answers(monkeypatch, typed):
    """Stand in for the terminal: three fields, then yes."""

    given = iter(typed)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(given))
    monkeypatch.setattr(
        "pypl2mp3.commands.fix_junks.prompt_user",
        lambda _question, _choices: "yes",
    )
    # The cover is not the subject and the network is not available.
    monkeypatch.setattr(
        SongModel, "update_cover_art",
        lambda self, **kwargs: asyncio.sleep(0),
    )


def test_what_the_terminal_is_given_is_marked_as_typed(
    junk, monkeypatch, capsys
):
    song = SongModel(junk)
    command = JunkSongTagger.__new__(JunkSongTagger)
    command.label_formatter = _Formatter()

    _answers(monkeypatch, ["Typed Artist", "Typed Title", ""])

    asyncio.run(command._prompt_for_metadata(song))

    decided = SongModel(junk.parent / song.filename).decided_by

    assert decided["artist"] == "user"
    assert decided["title"] == "user"


class _Formatter:
    """The command builds one in __init__, which this test skips."""

    def format(self, label):
        return label

    def pad_only(self, label):
        return label
