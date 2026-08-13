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


def test_the_order_is_where_a_person_would_look():
    """You come here knowing the name; you scan for it.

    Sorting on the raw name filed accented names after Z and names
    starting with punctuation ahead of the digits. Both are places
    nobody looks, so both were reported as missing.
    """

    artists = list_artists(
        [
            _song("the xx"),
            _song("Air"),
            _song("ZZ Top"),
            _song("Björk"),
            _song("Étienne Daho"),
            _song("...And You Will Know Us By the Trail of Dead"),
            _song("2TH"),
        ]
    )

    assert [a.name for a in artists] == [
        "2TH",
        "Air",
        "...And You Will Know Us By the Trail of Dead",
        "Björk",
        "Étienne Daho",
        "the xx",
        "ZZ Top",
    ]


def test_an_accented_name_files_under_its_plain_letter():
    artists = list_artists([_song("Zero 7"), _song("Étienne Daho")])

    assert [a.name for a in artists] == ["Étienne Daho", "Zero 7"], (
        "É sorts after z by code point, which puts it past the end"
    )


def test_leading_punctuation_does_not_hide_a_name_at_the_top():
    artists = list_artists(
        [_song("Air"), _song("...And You Will Know Us"), _song("2TH")]
    )

    assert [a.name for a in artists] == [
        "2TH",
        "Air",
        "...And You Will Know Us",
    ], "the dots must not file it before the digits"


def test_it_reads_no_files():
    """The whole point: a pass over 900 songs costs 1.4s, and the caller
    that wants artists has just paid for one."""

    artists = list_artists([_song("IAMX")])

    assert artists[0].name == "IAMX"
