#!/usr/bin/env python3
"""Locate one song in the repository by the playlist and video naming it.

Shared by every operation that acts on a single named song rather than on
a selection: junkizing, streaming, and anything that follows.

Not the video id alone. Eight songs in a repository of this shape sit in
two playlists at once, and a lookup on the id returned whichever copy the
filesystem listed first — so saving wrote to one of them and left the
other on its old metadata, junkizing renamed one and left the other
whole, and playing streamed a file the row you clicked did not name. The
key is the pair, and a playlist holds a video once.

Matching is exact. Not a fuzzy keyword search — callers use this when
they mean one specific song, and some of them destroy data.
"""

import hashlib
from pathlib import Path

from pypl2mp3.libs.utils import get_song_id_from_filename


class SongNotFound(Exception):
    """No song in the repository carries that YouTube id."""


def song_key(playlist_folder: str, youtube_id: str) -> str:
    """What names one file, as against the video it was made from.

    The playlist and the video, and not the filename: junkizing renames
    the file, and a name that moves is no use as an address — nor as the
    id of the row that has to be replaced in place.

    Hashed because this is also a DOM id and an htmx target: a playlist
    folder carries spaces and brackets, and both of those end a CSS
    selector early. Sixteen hex characters, which is a collision every
    few billion songs.

    One definition, called by both sides. The listing stamps it on every
    row; `find_song_file` recomputes it per candidate. Two spellings of
    the same formula would part company on the first edit.
    """

    name = f"{playlist_folder}/{youtube_id}"

    return hashlib.blake2s(name.encode(), digest_size=8).hexdigest()


def find_song_file(repository_path: Path, key: str) -> Path:
    """Return the path of the song this key names.

    The id is read from each filename rather than by building a SongModel
    per candidate: that constructor rewrites the ID3 header of any file
    lacking a YouTube id tag, so scanning that way would modify files just
    to look at them.

    Raises:
        SongNotFound: if no song in the repository answers to that key.
    """

    repository_path = Path(repository_path)

    # Globbed directly rather than through the repository listing. That
    # one parses and sorts every song so it can answer in artist order,
    # which this neither needs nor uses: 1.3s cold and 41ms warm against
    # 6ms here, on the path of every click that opens a song.
    for song_file in repository_path.glob("*/*.mp3"):
        found = get_song_id_from_filename(song_file.name)

        if found and song_key(song_file.parent.name, found) == key:
            return _ensure_inside(repository_path, song_file)

    raise SongNotFound(key)


def _ensure_inside(repository_path: Path, song_file: Path) -> Path:
    """Refuse a path that escapes the repository.

    The id comes from a URL, so this is the boundary where a crafted value
    could otherwise reach an arbitrary file. The candidates come from a
    repository scan and cannot currently escape, but callers stream these
    paths straight to a browser — the check belongs here, once, rather
    than being remembered at each call site.
    """

    resolved = song_file.resolve()
    root = repository_path.resolve()

    if not resolved.is_relative_to(root):
        raise SongNotFound(song_file.name)

    return resolved
