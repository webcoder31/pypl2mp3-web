#!/usr/bin/env python3
"""
PYPL2MP3: YouTube playlist MP3 converter and player,
with Shazam song identification and tagging capabilities.

This module displays the playlist inventory. All logic lives in
`pypl2mp3.services.list_playlists`; this file only formats output.

Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
License: CeCILL-C (http://www.cecill.info)
Repository: https://github.com/webcoder31/pypl2mp3
"""

# Python core modules
from pathlib import Path

# Third party packages
from colorama import Fore, Back, Style, init

# pypl2mp3 libs
from pypl2mp3.libs.utils import CountFormatter
# Aliased on purpose: until this module was split, `list_playlists` here was
# the command taking a Namespace. Re-importing the service under that very
# name would keep the old public path resolving, but to a function with an
# incompatible signature.
from pypl2mp3.services.list_playlists import (
    PlaylistSummary,
    list_playlists as get_playlist_summaries,
)

# Automatically clear style on each print
init(autoreset=True)


def display_playlists(args: any) -> None:
    """
    Display all playlists in the repository with their song statistics.

    Args:
        args: Command line arguments containing the repository path (args.repo)
    """

    summaries = get_playlist_summaries(Path(args.repo))

    if not summaries:
        print(f"{Back.MAGENTA}{Style.BRIGHT}"
            + f" No playlists found in repository ")
        return

    print(f"\n{Back.YELLOW}{Style.BRIGHT}"
        + f" Found {len(summaries)} playlists in repository. ")

    _display_playlists_details(summaries)


def _display_playlists_details(summaries: list[PlaylistSummary]) -> None:
    """
    Display detailed information for each playlist.

    Args:
        summaries: Playlist summaries, already sorted by the service
    """

    count_formatter = CountFormatter(len(summaries))
    placeholder = count_formatter.placeholder()

    for index, summary in enumerate(summaries, 1):
        counter = count_formatter.format(index)

        # Display playlist information
        print(
            f"\n{counter}  "
            f"{Fore.LIGHTYELLOW_EX}{summary.name}"
        )
        print(
            f"{placeholder}  "
            f"{Fore.LIGHTBLUE_EX}{Style.BRIGHT}ID: {Style.NORMAL}"
            f"{summary.playlist_id}"
        )

        # Display playlist statistics
        print(
            f"{placeholder}  {Style.BRIGHT}"
            f"Number of well tagged songs .... {summary.valid_songs}"
        )
        print(
            f"{placeholder}  {Style.BRIGHT}"
            f"Number of junk songs ........... {summary.junk_songs}"
        )
        print(
            f"{placeholder}  {Fore.LIGHTGREEN_EX}{Style.BRIGHT}"
            f"Total .......................... {summary.total_songs}"
        )
