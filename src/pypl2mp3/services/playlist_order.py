#!/usr/bin/env python3
"""The order a playlist has on YouTube, mirrored beside its songs.

One file per playlist folder, rewritten whole at every check. Not one
entry per MP3: the order belongs to the playlist, not to the recordings,
and the same video sitting in two playlists has two positions — which a
song's own document could hold, but only by rewriting 890 files to note
that one of them moved. This is one write, and one read.

A list and not a table of id to rank: the rank is the index, and a list
cannot give two songs the same one.

Disposable by design. If it is missing or unreadable the listing simply
falls back to the order the repository returns, and the next check writes
it again — which is why it is written to a temporary name and moved into
place, rather than truncated and filled.
"""

import json
import os
from pathlib import Path

FILENAME = ".pypl2mp3-order.json"

VERSION = 1


def write_order(
    playlist_folder: Path, playlist_id: str, video_ids: list[str]
) -> Path:
    """Record the order a check just read from YouTube.

    Args:
        playlist_folder: the playlist's folder in the repository.
        playlist_id: the playlist itself, for a reader that wants to
            check the file belongs where it was found.
        video_ids: every video the playlist holds, in its own order.

    Returns:
        The path written.
    """

    path = Path(playlist_folder) / FILENAME
    beside = path.with_name(FILENAME + ".new")

    beside.write_text(
        json.dumps(
            {
                "version": VERSION,
                "playlist": playlist_id,
                "order": list(video_ids),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Moved into place rather than written in place: a check interrupted
    # halfway would otherwise leave a truncated file, and the listing
    # would silently order itself by half a playlist.
    os.replace(beside, path)

    return path


def read_order(playlist_folder: Path) -> dict[str, int] | None:
    """Where each video stands in its playlist, or None if nobody knows.

    None and not an empty mapping, and the difference decides what the
    listing draws: no file means this playlist has never been checked, so
    nothing is out of order and nothing is missing from it. An empty
    order would mean a playlist YouTube says is empty — and every song in
    the folder orphaned.

    Ranks are one-based, so that a rank is never falsy.
    """

    path = Path(playlist_folder) / FILENAME

    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Missing, half-written, or not JSON at all. The file is a
        # convenience and the next check rebuilds it; nothing here is
        # worth an error the caller has to handle.
        return None

    order = said.get("order") if isinstance(said, dict) else None

    if not isinstance(order, list):
        return None

    return {
        video_id: rank
        for rank, video_id in enumerate(order, 1)
        if isinstance(video_id, str)
    }
