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


async def test_every_row_carries_the_name_the_player_will_show(tmp_path):
    """The player bar reads its title from here.

    It used to look the row up in the DOM when painting, and fall back to
    the YouTube id when the lookup missed — which it does the moment you
    filter while a track plays, the very thing this layout is for. The
    queue carries labels now, so the rows must supply them.
    """

    _make_song(tmp_path, "WU-TANG CLAN", "Tearz", "aaaaaaaaaaa")
    _make_song(tmp_path, "UNKNOWN", "Something", "bbbbbbbbbbb", junk=True)

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    labels = re.findall(r'data-label="([^"]*)"', fragment)
    assert len(labels) == 2, labels
    for label in labels:
        assert label.strip(), "a row would play as a blank title"
        assert not re.fullmatch(r"[\w-]{11}", label), (
            f"{label!r} is a YouTube id, not a name"
        )


async def test_the_player_title_never_falls_back_to_the_id(tmp_path):
    """A wiring check on the regression: the id says less than a blank.

    The bar names the *next* track now, but the trap is the same — a
    lookup in a listing the song may have been filtered out of.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert "following.label" in script, "the bar no longer reads the queue"
    assert "labelFor" not in script, (
        "the DOM lookup that fell back to the id is back"
    )


async def test_a_row_carries_what_the_preview_needs(tmp_path):
    """The bar previews the next track the way the CLI does: duration,
    name, and whether it is still junk."""

    _make_song(tmp_path, "ARTIST", "Good", "aaaaaaaaaaa")
    _make_song(tmp_path, "UNKNOWN", "Bad", "bbbbbbbbbbb", junk=True)

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    rows = re.findall(r"<tr[^>]*>", fragment)
    assert len(rows) == 2

    for row in rows:
        assert re.search(r'data-duration="\d[\d:]*"', row), row

    junk = next(r for r in rows if 'data-song-id="bbbbbbbbbbb"' in r)
    good = next(r for r in rows if 'data-song-id="aaaaaaaaaaa"' in r)
    assert 'data-junk="1"' in junk
    assert 'data-junk="0"' in good


async def test_the_bar_previews_what_comes_next_not_what_is_playing(tmp_path):
    """A wiring check. What is playing already fills the inspector; the
    bar's one useful job is saying what follows."""

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text
        script = (await client.get("/static/console.js")).text

    assert 'id="player-next"' in page
    assert 'id="player-label"' not in page, "the old current-track slot"

    assert "index + direction" in script, "the preview ignores the queue"
    # Pressing ← turns the player round; auto-advance must follow, or the
    # preview promises a track that never comes.
    assert "move(direction)" in script, (
        "a finishing track always goes forward, so the preview can lie"
    )


async def test_the_nav_offers_artist_presets(tmp_path):
    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")
    _make_song(tmp_path, "IAMX", "Spit It Out", "bbbbbbbbbbb")
    _make_song(tmp_path, "THE CURE", "A Forest", "ccccccccccc")
    _make_song(tmp_path, "UNKNOWN", "Something", "ddddddddddd", junk=True)

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    presets = re.findall(r'data-artist="([^"]*)"', body)
    assert presets == ["IAMX", "THE CURE"], presets
    assert "UNKNOWN" not in presets, "a junk channel name became a preset"


async def test_picking_an_artist_filters_the_listing_exactly(tmp_path):
    """Fuzzy matching is what the search box is for. A preset is a name."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")
    _make_song(tmp_path, "IAM", "Petit frere", "bbbbbbbbbbb")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list?artist=IAM")).text

    assert re.findall(r'data-song-id="(\w+)"', fragment) == ["bbbbbbbbbbb"], (
        "an exact preset picked up a fuzzy neighbour"
    )


async def test_an_artist_preset_survives_a_reload(tmp_path):
    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")
    _make_song(tmp_path, "THE CURE", "A Forest", "bbbbbbbbbbb")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/?artist=IAMX")).text

    assert re.findall(r'data-song-id="(\w+)"', body) == ["aaaaaaaaaaa"]
    assert 'id="artist-field"' in body and 'value="IAMX"' in body

    # The preset narrows the listing, never the preset list itself.
    assert re.findall(r'data-artist="([^"]*)"', body) == ["IAMX", "THE CURE"]


async def test_the_presets_cover_the_repository_not_the_current_filter(
    tmp_path,
):
    """Filtering must not shrink the list you filter with."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")
    _make_song(tmp_path, "THE CURE", "A Forest", "bbbbbbbbbbb")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/?q=kiss&match=45")).text

    assert re.findall(r'data-song-id="(\w+)"', body) == ["aaaaaaaaaaa"]
    assert re.findall(r'data-artist="([^"]*)"', body) == ["IAMX", "THE CURE"]


async def test_an_artist_preset_composes_with_a_playlist(tmp_path):
    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")
    _make_song(tmp_path, "IAMX", "Spit It Out", "bbbbbbbbbbb", playlist=OTHER)

    async with _client(create_app(tmp_path)) as client:
        fragment = (
            await client.get(
                "/fragments/list?artist=IAMX"
                "&playlist=PL0000000000000000000000000000002"
            )
        ).text

    assert re.findall(r'data-song-id="(\w+)"', fragment) == ["bbbbbbbbbbb"]


async def test_the_bar_says_next_before_the_arrow(tmp_path):
    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert '"NEXT →"' in script
    assert '"NEXT ←"' in script, "the backward preview lost its label"
