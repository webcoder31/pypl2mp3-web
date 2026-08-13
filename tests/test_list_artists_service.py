"""Artist presets, grouped from songs already in hand."""

from pathlib import Path

from pypl2mp3.services.list_artists import list_artists
from pypl2mp3.services.list_songs import SongSummary


def _song(artist: str, title: str = "Song", junk: bool = False) -> SongSummary:
    return SongSummary(
        path=Path("/repo/Owner - Alpha [PL1]") / f"{artist} - {title}.mp3",
        youtube_id="aaaaaaaaaaa",
        artist=artist,
        title=title,
        playlist="Owner - Alpha [PL1]",
        duration="00:03:00",
        is_junk=junk,
    )


def test_an_empty_repository_has_no_artists():
    assert list_artists([]) == []


def test_it_counts_each_artist_s_songs():
    artists = list_artists(
        [_song("IAMX", "Kiss"), _song("IAMX", "Spit It Out"), _song("The Cure")]
    )

    assert [(a.name, a.song_count) for a in artists] == [
        ("IAMX", 2),
        ("The Cure", 1),
    ]


def test_junk_songs_are_left_out():
    """Their artist is whatever YouTube called the channel."""

    artists = list_artists(
        [
            _song("Chuy Flores - Topic", junk=True),
            _song("ChilledDubstepMusic", junk=True),
            _song("The Cure"),
        ]
    )

    assert [a.name for a in artists] == ["The Cure"]


def test_songs_with_no_artist_at_all_are_left_out():
    """A blank entry in the nav would filter to nothing and say why not."""

    artists = list_artists([_song(""), _song("The Cure")])

    assert [(a.name, a.song_count) for a in artists] == [("The Cure", 1)]


def test_spellings_that_differ_only_in_case_are_one_artist():
    """Filenames uppercase the artist; ID3 tags do not. Both reach here."""

    artists = list_artists(
        [
            _song("Above & Beyond", "Alchemy"),
            _song("ABOVE & BEYOND", "Alone Tonight"),
            _song("Above & Beyond", "All Over The World"),
        ]
    )

    assert len(artists) == 1, [a.name for a in artists]
    assert artists[0].song_count == 3
    assert artists[0].name == "Above & Beyond", (
        "the nav must show the spelling the listing shows"
    )


def test_the_order_is_alphabetical_and_ignores_case():
    """You come here knowing the name; you scan for it."""

    artists = list_artists(
        [_song("the xx"), _song("Air"), _song("ZZ Top"), _song("Björk")]
    )

    assert [a.name for a in artists] == ["Air", "Björk", "the xx", "ZZ Top"]


def test_it_reads_no_files():
    """The whole point: a pass over 900 songs costs 1.4s, and the caller
    that wants artists has just paid for one."""

    artists = list_artists([_song("IAMX")])

    assert artists[0].name == "IAMX"
