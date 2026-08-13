#!/usr/bin/env python3
"""Artists, derived from songs already in hand.

A pure function, deliberately: reading the repository costs 1.4s over 900
songs, and the caller that wants an artist list is always a caller that
has just listed songs. Taking the summaries as an argument means the
artist list is free rather than a second pass over the same files.
"""

from dataclasses import dataclass

from pypl2mp3.services.list_songs import SongSummary


@dataclass(frozen=True)
class ArtistSummary:
    """One artist and how much of them the repository holds."""

    name: str
    song_count: int


def list_artists(songs: list[SongSummary]) -> list[ArtistSummary]:
    """Group songs by artist, alphabetically.

    Junk songs are left out. Their artist is whatever YouTube called the
    channel — "ChilledDubstepMusic", "Chuy Flores - Topic" — which is
    exactly the noise a preset list should not carry.

    Args:
        songs: summaries to group. Usually a whole playlist or repository.

    Returns:
        One entry per artist, ordered case-insensitively by name.
    """

    # Spellings differ between files: the ID3 tag says "Above & Beyond",
    # an older one may say "ABOVE & BEYOND". Group case-insensitively and
    # show whichever spelling appears most, so the nav matches the list.
    spellings: dict[str, dict[str, int]] = {}
    for song in songs:
        if song.is_junk or not song.artist:
            continue
        seen = spellings.setdefault(song.artist.casefold(), {})
        seen[song.artist] = seen.get(song.artist, 0) + 1

    artists = [
        ArtistSummary(
            name=max(seen.items(), key=lambda kv: (kv[1], kv[0]))[0],
            song_count=sum(seen.values()),
        )
        for seen in spellings.values()
    ]

    return sorted(artists, key=lambda artist: artist.name.casefold())
