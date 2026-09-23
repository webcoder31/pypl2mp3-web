#!/usr/bin/env python3
"""Song inventory, filtered.

Backs both the `songs` and `junks` commands: they are the same query with
`junk_only` flipped, so they are one service rather than two.

Reads the local filesystem only — no network call, ever. Building a
SongModel parses the file's ID3 tags, which is disk work, not a request.
"""

import dataclasses
import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pypl2mp3.libs.repository import get_repository_songs
from pypl2mp3.libs.song import SongModel
from pypl2mp3.libs.features import read_features
from pypl2mp3.libs.utils import natural_sort_key
from pypl2mp3.services.find_song import song_key_in_folder
from pypl2mp3.services.playlist_order import read_order

DEFAULT_MATCH_THRESHOLD = 45


# The order the sentence names them in, which is the order the panel
# shows them in. Dictionary order would follow whatever was written last.
_BY_HAND_ORDER = (
    "artist", "title", "cover", "album", "year", "genre", "publisher",
)


def release_line(album: str, year: str, genre: str, publisher: str) -> str:
    """The release data as one labelled line, or nothing at all.

    Joined here rather than in a template because the parts are each
    optional: Shazam answers with all four, three, or none, and a
    template assembling separators around holes is where the stray
    middot comes from.

    A function and not only a property, because two places show this now
    — the listing's board and the panel offering Shazam's answer — and a
    second implementation would be a second format.
    """

    line = " · ".join(part for part in (album, year, genre, publisher) if part)

    return f"Album: {line}" if line else ""


def recording_line(isrc: str) -> str:
    """The recording code, opened out into what it says.

    `FRZ031900123` is four things run together and nobody reads it as
    four. Country of the registrant, year of reference, the registrant
    itself, then its own numbering.

    Labelled `Recording`, which is the standard's own word — ISRC is the
    International Standard Recording Code. It identifies a take, not a
    disc and not a song: two recordings of one piece carry two codes,
    which is what settled Chill Rob G against Snap!.

    The year is shown as the registrant wrote it, and that is the point:
    38 codes in this library predate the standard, so the field is
    whatever was put there — usually the recording's own year. A 1973
    code on a 2025 release says the reissue kept the take.

    A string that is not a code is shown whole rather than split into
    four parts it does not have. At least the error is visible.
    """

    code = (isrc or "").replace("-", "").upper()

    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}\d{7}", code):
        return f"Recording (ISRC): {isrc}" if isrc else ""

    two = int(code[5:7])
    pivot = datetime.date.today().year % 100
    year = 2000 + two if two <= pivot else 1900 + two

    return (
        f"Recording (ISRC): {code[:2]} · {year} · {code[2:5]} · {code[7:]}"
    )


@dataclass(frozen=True)
class SongSummary:
    """What a listing needs about one song, without reopening the file."""

    path: Path
    youtube_id: str
    artist: str
    title: str
    playlist: str
    duration: str
    is_junk: bool
    # What Shazam knows about the release, when it matched the song.
    # Empty strings rather than None: every consumer is a template, and
    # a template treats both the same while None reads back as "None".
    album: str = ""
    publisher: str = ""
    year: str = ""
    genre: str = ""
    # Where the file came from, when the document knows. The video's own
    # title is the only place the original name survives: the import
    # takes it, Shazam overwrites it, and on 652 songs the two differ.
    origin_author: str = ""
    origin_title: str = ""
    # The recording code, from Shazam's answer and nowhere else. Not a
    # field: it is not something the file asserts about itself, it is
    # what one upstream replied.
    isrc: str = ""
    # The fields somebody typed, as opposed to the ones a pass proposed.
    # A tuple and not a set: the sentence built from it has to come out
    # the same way twice.
    set_by_hand: tuple[str, ...] = ()
    # And whether asking YouTube about it is still worth a click. Eleven
    # videos have gone; the link to them answers 404 without saying so.
    video_gone: bool = False
    # Where the song stands in its playlist on YouTube, when a check has
    # read that order. None means nobody has looked — which is not the
    # same as being absent from it, and `off_playlist` says which.
    # What the song sounds like, as the features module measures it, or
    # None when nobody has analysed this file yet. Read from the mutagen
    # object the repository cache already holds, so a listing that is
    # warm pays nothing for it.
    features: tuple[float, ...] | None = None

    playlist_rank: int | None = None
    off_playlist: bool = False

    @property
    def key(self) -> str:
        """What names this file, as against the video it was made from.

        Eight songs in this repository sit in two playlists at once, so a
        video id names two rows and the page could not tell them apart:
        the song playing lit both, and lining the second one up lined up
        the first. The folder and the filename do tell them apart, and
        they are what the listing is made of.

        The playlist and the video, and not the filename: junkizing
        renames the file, and the row that comes back to replace the one
        you clicked has to carry the id it was aimed at. A playlist holds
        a video once, so the pair is as unique as the path and it
        survives every rename the file will ever get — and the playlist's
        half is its id, which survives the playlist being retitled.

        Hashed rather than spelled out because this is also the row's DOM
        id and an htmx target: a playlist folder carries spaces and
        brackets, and both of those end a CSS selector early.

        Not an address. The server still answers for a song by its video
        id — /songs/<id>/audio, /fix, /junkize — and cannot tell two
        copies apart either. This is the page saying which row it means.
        """

        return song_key_in_folder(self.playlist, self.youtube_id)

    @property
    def cover_version(self) -> int:
        """A number that changes whenever the file does.

        The cover lives at /songs/<id>/cover, an address that never
        changes, and the response carries no validator of any kind — so a
        browser that has seen it once keeps showing it. Saving a new cover
        URL replaced the picture on disk and left the old one on screen,
        which read as the save having failed.

        The file's own timestamp is the cheapest thing that moves. It also
        moves when something unrelated is written — a tag edit, the
        waveform peaks — and the cover is then fetched again for nothing.
        That is a few tens of kilobytes over a loopback connection, which
        is a smaller price than a stale picture.

        A property and not a field: the listing builds one summary per
        song and nine hundred stat() calls would be paid by every page,
        while only the two panels that draw a cover ever read this.
        """

        try:
            return int(self.path.stat().st_mtime)
        except OSError:
            # The file went while the page was being built. The panel is
            # about to 404 anyway; it should not do it from here.
            return 0

    @property
    def release(self) -> str:
        """The release line. See `release_line`."""

        return release_line(self.album, self.year, self.genre, self.publisher)

    @property
    def recording(self) -> str:
        """The recording code, opened out. See `recording_line`."""

        return recording_line(self.isrc)

    @property
    def playlist_face(self) -> str:
        """The playlist, labelled like the rest."""

        return f"Playlist: {self.playlist_name}"

    @property
    def by_hand(self) -> str:
        """What was typed rather than found, as a sentence, or nothing.

        The warning that was missing in front of Ask Shazam. A match
        overwrites artist, title and cover without asking, and a value
        somebody typed is the one thing in the file that asking again
        cannot bring back — which is exactly what the backfill had to
        work around by refusing to call `shazam_song` at all.

        A sentence rather than a mark on each field: three marks say the
        same thing three times and read as decoration, and the reader has
        to work out what they mean. One line says it once, in words, at
        the moment it matters.
        """

        if not self.set_by_hand:
            return ""

        names = list(self.set_by_hand)
        listed = (
            names[0] if len(names) == 1
            else ", ".join(names[:-1]) + f" and {names[-1]}"
        )

        return (
            f"{listed} set by hand — Ask Shazam would replace "
            f"{'it' if len(names) == 1 else 'them'}"
        )

    @property
    def by_hand_short(self) -> str:
        """The same warning, short enough for a row that is already full.

        It had a row of its own and that row cost the panel 25px, which
        was the difference between landing on the cover and overrunning
        it. What is left is the half a reader acts on — which fields —
        with the consequence in the tooltip.
        """

        if not self.set_by_hand:
            return ""

        return f"{', '.join(self.set_by_hand)} set by hand"

    @property
    def origin(self) -> str:
        """The video this file was made from, as one line.

        Channel first, then the video's own title — the same order the
        eye reads a listing row in. Empty when the origin was never
        recovered, which is what keeps it off the board: a face with
        nothing to say should not take a turn.

        Prefixed, as they all are now. It was the first face to need it,
        back when it was the only one: both lines were middot-joined and
        "Chill Masters · SYNAPSON - Djon Maya Maï" read exactly like a
        label and an album.
        """

        line = " · ".join(
            part for part in (self.origin_author, self.origin_title) if part
        )

        return f"From: {line}" if line else ""

    @property
    def facts(self) -> list[tuple[str, str, bool]]:
        """The four faces as label, value, and whether it is known.

        The board turns because a listing row and a panel have one line
        to spare. The workbench has a column, and there a face you have
        to wait four seconds for is a face you judge the song without.
        Same four, same order, same strings — split at the colon each one
        already carries rather than formatted a second way, so the board
        and the table can never come to disagree.

        The board drops a face with nothing to say, because a slot that
        turns to a blank is a slot wasted. The table does the opposite
        for the two that matter: a song with no release and no code is
        the song this mode exists for, and saying so is the point —
        marked, and in the colour the rest of the page uses for a file
        that still wants work. The origin keeps the board's rule: it is
        where the file came from, not something to go and find.

        The label is shortened here, too. The board says "Recording
        (ISRC)" because a face there shares its line with three others
        and has to name itself twice over — once for what it is, once for
        what it is called. In the table the label has a column of its own
        and the four are read down rather than one at a time, so the
        code's own name is enough.
        """

        def split(face: str) -> str:
            return face.partition(": ")[2]

        album, code = split(self.release), split(self.recording)
        playlist, origin = split(self.playlist_face), split(self.origin)

        facts = [
            ("Album", album or "unknown", bool(album)),
            ("ISRC", code or "unknown", bool(code)),
            ("Playlist", playlist, True),
        ]

        if origin:
            facts.append(("From", origin, True))

        return facts

    @property
    def label(self) -> str:
        """Artist and title as one line, for a single-column display."""

        return f"{self.artist} - {self.title}"

    @property
    def short_duration(self) -> str:
        """`6:17`, not `00:06:17`.

        SongModel pads to a fixed eight characters so terminal columns
        line up. On screen those leading zeros are three characters of
        nothing, repeated down every row of a 900-row listing.
        """

        parts = self.duration.split(":")
        while len(parts) > 2 and parts[0].strip("0") == "":
            parts.pop(0)

        return ":".join([parts[0].lstrip("0") or "0", *parts[1:]])

    @property
    def playlist_name(self) -> str:
        """The playlist without its YouTube id.

        `playlist` is the folder name, which ends in the id — the same
        forty characters repeated on every row of a listing. list_playlists
        strips it the same way for the same reason.
        """

        return re.sub(r"\s*\[[^\[\]]*\]\s*$", "", self.playlist).strip()


def list_songs(
    repository_path: Path,
    junk_only: bool = False,
    keywords: str = "",
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    playlist_identifier: Optional[str] = None,
) -> list[SongSummary]:
    """Summarise the songs matching the given criteria.

    Args:
        repository_path: folder where playlists are stored.
        junk_only: restrict to songs Shazam could not match.
        keywords: fuzzy filter; empty means no filtering.
        match_threshold: minimum fuzzy score, 0-100.
        playlist_identifier: id, URL or index; None means every playlist.

    Returns:
        One summary per matching song, in the order the repository
        returned them. Empty when nothing matches — an empty result is a
        legitimate answer, not an error.
    """

    # Asks for the models, not the paths: selecting and sorting has
    # already parsed every candidate, so rebuilding one per path would
    # double the work. Measured at 1.2s over a 915-song repository.
    songs = get_repository_songs(
        Path(repository_path),
        junk_only=junk_only,
        keywords=keywords,
        filter_match_threshold=match_threshold,
        playlist_identifier=playlist_identifier,
    )

    # The repository helper returns None rather than [] when it finds
    # nothing; both mean the same thing here.
    return [summarize(song) for song in (songs or [])]


def in_playlist_order(
    repository_path: Path, songs: list[SongSummary]
) -> list[SongSummary]:
    """The same songs, ordered the way their playlists are on YouTube.

    Songs a playlist no longer holds go last, marked. A whole playlist
    nobody has checked keeps the order it came in and none of its songs
    is marked: not knowing where a song stands is not the same as knowing
    it is gone.

    Not folded into `list_songs`, and not into the repository below it:
    the CLI lists by artist and must go on doing so. This is the web
    listing's own idea of order.
    """

    known: dict[str, dict[str, int] | None] = {}

    def order_of(playlist: str) -> dict[str, int] | None:
        if playlist not in known:
            known[playlist] = read_order(Path(repository_path) / playlist)

        return known[playlist]

    ranked = []

    for song in songs:
        order = order_of(song.playlist)

        if order is None:
            ranked.append(song)
            continue

        rank = order.get(song.youtube_id)
        ranked.append(dataclasses.replace(
            song, playlist_rank=rank, off_playlist=rank is None
        ))

    # Two passes rather than one sort key. What has a rank is grouped by
    # playlist, in the order the nav lists them, then by position. What
    # has none keeps the order it arrived in — the repository's, by
    # artist — and a single key would have had to sort those by playlist
    # too, which would quietly group an unchecked repository's whole
    # listing by folder instead of leaving it alphabetical.
    held = [song for song in ranked if song.playlist_rank]
    rest = [song for song in ranked if not song.playlist_rank]

    held.sort(key=lambda song: (
        natural_sort_key(song.playlist), song.playlist_rank
    ))

    return held + rest


def _features_of(song: SongModel) -> tuple[float, ...] | None:
    """The song's feature vector, if the file carries one.

    Taken from the mutagen object the model already holds rather than
    reopening the file: the repository caches parsed songs by path and
    modification time, so this costs a dictionary lookup on a warm
    listing and the tags are read once either way.
    """

    try:
        found = read_features(song.mp3)
    except Exception:
        # A song whose tags cannot be read has no vector, which is the
        # same as one nobody analysed: it lists, and it has no place in
        # a walk.
        return None

    return tuple(found) if found is not None else None


def summarize(song: SongModel) -> SongSummary:
    """Project a SongModel onto the fields a listing shows.

    Public so callers that already hold a model — after junkizing one, for
    instance — can render it without going back through the repository.
    """

    return SongSummary(
        path=song.path,
        youtube_id=song.youtube_id or "",
        artist=song.artist or "",
        title=song.title or "",
        playlist=song.playlist,
        duration=song.duration,
        is_junk=bool(song.has_junk_filename),
        album=song.album or "",
        publisher=song.publisher or "",
        year=song.year or "",
        genre=song.genre or "",
        set_by_hand=tuple(
            name for name in _BY_HAND_ORDER
            if song.decided_by.get(name) == "user"
        ),
        isrc=song.isrc or "",
        features=_features_of(song),
        origin_author=song.youtube_origin.get("author") or "",
        origin_title=song.youtube_origin.get("title") or "",
        video_gone=bool(song.youtube_origin.get("gone")),
    )
