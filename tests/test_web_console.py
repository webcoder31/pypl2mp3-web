"""The one-page console: everything at hand, nothing navigates away."""

import re
from html.parser import HTMLParser
from pathlib import Path

import httpx

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
OTHER = "Owner - Beta [PL0000000000000000000000000000002]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, artist, title, vid, junk=False, playlist=PLAYLIST):
    folder = repo / playlist
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    (folder / f"{artist} - {title} [{vid}]{suffix}.mp3").write_bytes(
        _MP3_FRAME * 8
    )


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


class _AudioAncestors(HTMLParser):
    """Ids of the elements each <audio> tag sits inside."""

    def __init__(self):
        super().__init__()
        self.stack: list[str | None] = []
        self.found: list[set[str]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "audio":
            self.found.append({i for i in self.stack if i})
        # Void elements never nest; tracking them would unbalance the stack.
        if tag not in ("input", "img", "br", "meta", "link", "hr", "source"):
            self.stack.append(attributes.get("id"))

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


async def test_the_console_holds_every_region_in_one_document(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    for region in ("nav", "list", "inspector", "player", "header"):
        assert f'id="{region}"' in body, region


async def test_the_audio_element_sits_outside_every_swap_target(tmp_path):
    """The rule the whole layout rests on.

    A fragment swap that contained the <audio> element would recreate it
    and cut the sound.

    The forbidden set is not hardcoded here. It is every region the
    template marks `data-swap-region`, plus every element some hx-target
    already points at — so declaring a new swappable region is enough to
    have the rule enforced on it, and a region that is swappable but not
    yet targeted is caught before it ever is.
    """

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    targets = {
        selector[1:]
        for selector in re.findall(r'hx-target="([^"]+)"', body)
        if selector.startswith("#")
    } | set(re.findall(r'id="([^"]+)"[^>]*data-swap-region', body))

    assert len(targets) >= 4, (
        f"only {targets} look swappable — the check would be near-vacuous"
    )

    parser = _AudioAncestors()
    parser.feed(body)
    assert len(parser.found) == 1, (
        f"expected exactly one player, found {len(parser.found)}"
    )

    clash = parser.found[0] & targets
    assert not clash, f"the player is inside swap target(s) {clash}"


async def test_the_listing_carries_no_player_of_its_own(tmp_path):
    """There used to be one <audio> per row — 915 in a full listing."""

    for i in range(5):
        _make_song(tmp_path, "ARTIST", f"Song {i}", f"vid{i:07d}")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    assert "<audio" not in fragment
    assert fragment.count('data-song-id="') == 5, (
        "rows must be identifiable — console.js builds the queue from them"
    )


async def test_a_row_shows_the_playlist_without_repeating_its_id(tmp_path):
    """The id was a column of its own: forty identical characters a row."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    assert "Owner - Alpha" in fragment, "the playlist is no longer shown"
    assert "PL0000000000000000000000000000001" not in fragment, (
        "the playlist id is back in the listing"
    )
    assert "<th" not in fragment, "the column headers are back"


async def test_the_queue_controls_are_not_crammed_into_a_header_cell(tmp_path):
    """They overlapped the count there; a table header is not a toolbar."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    toolbar = re.search(
        r'<div class="toolbar">(.*?)</div>', fragment, re.DOTALL
    )
    assert toolbar, "no toolbar"
    assert 'data-queue-action="play"' in toolbar.group(1)
    assert 'data-queue-action="shuffle"' in toolbar.group(1)

    table = fragment[fragment.index("<table") :]
    assert "data-queue-action" not in table, (
        "a queue control is still inside the table"
    )


async def test_the_page_starts_silent(tmp_path):
    """No src until you press play: opening the console reads no files."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    player = re.search(r"<audio[^>]*>", body).group(0)
    assert "src=" not in player, player


async def test_the_list_fragment_honours_the_filters(tmp_path):
    _make_song(tmp_path, "WU-TANG CLAN", "Tearz", "aaaaaaaaaaa")
    _make_song(tmp_path, "DIRE STRAITS", "Sultans", "bbbbbbbbbbb")
    _make_song(tmp_path, "ARTIST", "Junky", "ccccccccccc", junk=True)

    async with _client(create_app(tmp_path)) as client:
        searched = (await client.get("/fragments/list?q=tearz&match=45")).text
        junk = (await client.get("/fragments/list?junk=1")).text

    assert re.findall(r'data-song-id="(\w+)"', searched) == ["aaaaaaaaaaa"]
    assert re.findall(r'data-song-id="(\w+)"', junk) == ["ccccccccccc"]


async def test_the_fragment_is_a_fragment_not_a_page(tmp_path):
    """Swapping a whole document into #list would nest a page in a page."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    for tag in ("<html", "<body", "<head", "id=\"player\""):
        assert tag not in fragment, tag


async def test_the_nav_offers_every_playlist_and_the_whole_repository(
    tmp_path,
):
    _make_song(tmp_path, "ARTIST", "One", "aaaaaaaaaaa")
    _make_song(tmp_path, "ARTIST", "Two", "bbbbbbbbbbb", playlist=OTHER)

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    assert 'data-playlist=""' in body, "no way back to the whole repository"
    assert 'data-playlist="PL0000000000000000000000000000001"' in body
    assert 'data-playlist="PL0000000000000000000000000000002"' in body


async def test_the_query_survives_a_reload(tmp_path):
    """Reloading a filtered view must not dump you back at everything."""

    _make_song(tmp_path, "WU-TANG CLAN", "Tearz", "aaaaaaaaaaa")
    _make_song(tmp_path, "DIRE STRAITS", "Sultans", "bbbbbbbbbbb")

    async with _client(create_app(tmp_path)) as client:
        body = (
            await client.get(
                "/?q=tearz&match=45"
                "&playlist=PL0000000000000000000000000000001"
            )
        ).text

    assert re.findall(r'data-song-id="(\w+)"', body) == ["aaaaaaaaaaa"]
    assert 'value="tearz"' in body, "the search box lost the query"
    assert (
        'id="playlist-field"' in body
        and 'value="PL0000000000000000000000000000001"' in body
    ), "the playlist selection was not restored"


async def test_the_console_references_no_external_host(tmp_path):
    """Offline tool: every asset must come from us."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        assert (await client.get("/static/console.js")).status_code == 200
        assert (await client.get("/static/console.css")).status_code == 200

    for src in re.findall(
        r'<(?:script|link|img)[^>]*?(?:src|href)="([^"]+)"', body
    ):
        assert not src.startswith(("http://", "https://", "//")), src
