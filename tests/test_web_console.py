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


async def test_the_listing_fragment_is_rows_and_nothing_else(tmp_path):
    """Its toolbar moved out when it stopped needing anything from the
    server. What is left must stay swappable without taking the queue's
    readout with it."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    assert "<table" in fragment
    assert 'data-song-id="aaaaaaaaaaa"' in fragment
    for gone in ("toolbar", "data-queue-action", "player-position",
                 "player-next"):
        assert gone not in fragment, gone


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


async def test_the_artist_filter_box_ignores_accents(tmp_path):
    """Typing "etienne" has to find "Étienne Daho", the way the sort does."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert "normalize(\"NFD\")" in script, (
        "the artist filter box would miss every accented name"
    )


async def test_the_presets_say_when_they_only_cover_one_playlist(tmp_path):
    """A bare count of 420 reads as "every artist".

    The presets are scoped to the selected playlist — they have to be,
    or picking an artist held elsewhere would filter to nothing. An
    artist absent from the current playlist then reads as missing, which
    is exactly how this was reported.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")
    _make_song(tmp_path, "THE CURE", "A Forest", "bbbbbbbbbbb", playlist=OTHER)

    async with _client(create_app(tmp_path)) as client:
        whole = (await client.get("/")).text
        scoped = (
            await client.get("/?playlist=PL0000000000000000000000000000001")
        ).text

    assert re.findall(r'data-artist="([^"]*)"', whole) == ["IAMX", "THE CURE"]
    assert re.findall(r'data-artist="([^"]*)"', scoped) == ["IAMX"]

    note = re.search(r'<p class="scope">(.*?)</p>', scoped, re.DOTALL)
    assert note, "nothing says the presets cover one playlist"
    # The title, not the whole folder name: every playlist here belongs
    # to the same owner, so repeating it says nothing.
    assert "Alpha" in note.group(1), "the note does not name it"

    # A way back to every playlist, somewhere in this column — not
    # necessarily on this line. It used to be a second button here, which
    # is the same escape the first row of the nav already is.
    assert scoped.count('data-playlist=""') >= 1, (
        "nothing in the nav goes back to every playlist"
    )

    assert 'class="scope"' not in whole, (
        "the unscoped nav claims a scope it does not have"
    )


async def test_the_nav_refetches_when_the_playlist_changes(tmp_path):
    """Otherwise it keeps offering artists the listing cannot show, and
    keeps the old playlist highlighted as current."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    nav = re.search(r'<nav[^>]*id="nav"[^>]*>', body, re.DOTALL)
    assert nav, "no nav element"
    assert 'hx-get="/fragments/nav"' in nav.group(0)
    assert "playlistChanged from:body" in nav.group(0)
    assert 'hx-include="#filters"' in nav.group(0), (
        "the refetch would lose the playlist it is meant to scope to"
    )


async def test_only_a_playlist_change_rebuilds_the_nav(tmp_path):
    """Rebuilding it costs a pass over the songs; a keystroke must not."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text
        page = (await client.get("/")).text

    assert 'dispatchEvent(new CustomEvent("playlistChanged"))' in script

    form = re.search(r'<form[^>]*id="filters"[^>]*>', page, re.DOTALL)
    assert "playlistChanged" not in form.group(0), (
        "every keystroke would pay for a nav rebuild"
    )


async def test_changing_playlist_clears_the_artist_preset(tmp_path):
    """The artist may not exist in the new playlist; keeping it would
    filter to nothing and look like an empty playlist."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    playlist_branch = script[
        script.index("button[data-playlist]") : script.index(
            "button[data-artist]"
        )
    ]
    assert 'artistField.value = ""' in playlist_branch


async def test_the_nav_fragment_is_a_fragment(tmp_path):
    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/nav")).text

    for tag in ("<html", "<body", "<head", "<audio"):
        assert tag not in fragment, tag
    assert 'data-artist="IAMX"' in fragment
    assert 'data-playlist=""' in fragment, "no way back to everything"


async def test_the_console_keeps_the_cli_s_playback_controls(tmp_path):
    """Parity with `play`, which the standalone player page used to hold.

    A wiring check — the behaviour needs a browser engine — but it is
    what stops these keys quietly disappearing.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    for key in ("ArrowRight", "ArrowLeft", "Tab", "Escape"):
        assert f'"{key}"' in script, key
    assert 'case " "' in script, "no space bar handling"
    assert 'addEventListener("ended"' in script, (
        "the queue does not advance when a song finishes"
    )
    assert "youtu.be/" in script, "no way to open the video"


async def test_the_presets_refresh_when_a_song_is_fixed(tmp_path):
    """A repaired junk song gains a real artist, which belongs in the
    presets. This was once too expensive to do on every save; the
    parsed-song cache brought a nav rebuild down to about 40ms."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    nav = re.search(r'<nav[^>]*id="nav"[^>]*>', body, re.DOTALL).group(0)
    trigger = re.search(r'hx-trigger="([^"]+)"', nav).group(1)

    assert "songsChanged from:body" in trigger, (
        "a fixed song does not reach the artist list until a reload"
    )
    assert "playlistChanged from:body" in trigger, "the other trigger went"


async def test_the_nav_leads_with_the_title_not_the_owner(tmp_path):
    """A repository's playlists usually share one owner. Leading with it
    makes every entry start with the same words and files the titles
    where nobody reads."""

    (tmp_path / "Thierry Thiers - What I listen now [PL0001]").mkdir()
    (tmp_path / "Thierry Thiers - mid90s [PL0002]").mkdir()

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/fragments/nav")).text

    titles = {
        found.strip()
        for found in re.findall(r'class="pl-title">([^<]*)<', body)
    }
    owners = {
        found.strip()
        for found in re.findall(r'class="pl-owner">([^<]*)<', body)
    }

    assert titles == {"What I listen now", "mid90s"}, titles
    assert owners == {"Thierry Thiers"}, owners

    # And the title comes first in the document, not merely in the CSS.
    first = body.index('class="pl-title"')
    assert first < body.index('class="pl-owner"')


async def test_nothing_is_marked_playing_when_nothing_plays(tmp_path):
    """Every page load starts with an empty queue.

    classList.toggle takes an *optional* boolean: handed undefined it
    treats the argument as absent and toggles instead of setting. Written
    as `current && row.id === current.id`, that evaluated to undefined
    with nothing playing and marked all 927 rows at once.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    for call in re.findall(r"classList\.toggle\(([^;]*?)\);", script,
                           re.DOTALL):
        assert "&&" not in call, (
            f"classList.toggle({call.strip()}) can hand undefined to an "
            "optional boolean, which toggles instead of setting"
        )

    assert "row.dataset.songId === currentId" in script, (
        "the row-marking comparison is no longer strict"
    )


async def test_static_files_are_always_revalidated(tmp_path):
    """Starlette sends an ETag but no Cache-Control, which leaves the
    browser to guess how long a file stays fresh — Chrome guesses a
    tenth of its age. A stylesheet touched ten hours ago is then held
    for an hour without asking, and an edit simply does not arrive.

    That cost a whole round of chasing a bug that was already fixed: the
    fix was live on the server and the browser was running the file it
    had cached before it.
    """

    async with _client(create_app(tmp_path)) as client:
        for asset in ("console.js", "console.css", "htmx.min.js"):
            response = await client.get(f"/static/{asset}")

            assert response.status_code == 200, asset
            assert response.headers.get("cache-control") == "no-cache", (
                f"{asset} may be served from cache without asking"
            )
            # no-cache means "revalidate", not "re-download": the ETag is
            # what keeps that cheap.
            assert response.headers.get("etag"), asset


async def test_a_revalidated_asset_costs_nothing(tmp_path):
    async with _client(create_app(tmp_path)) as client:
        first = await client.get("/static/console.js")
        again = await client.get(
            "/static/console.js",
            headers={"If-None-Match": first.headers["etag"]},
        )

    assert again.status_code == 304
    assert not again.content


async def test_the_panel_describes_the_first_song_on_arrival(tmp_path):
    """It used to say "Select a song." and nothing else.

    The first row is the obvious one to describe, and describing a song
    is not playing it: the player stays silent until asked, and the
    panel's own Play this button is what asks.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    # The block that runs on arrival, and only that block: slicing from
    # its own guard rather than from a nearby landmark, which caught the
    # rest of the file the first time this was written.
    start = script.index(
        'if (!document.querySelector("#inspector [data-song-id]"))'
    )
    arrival = script[start:]
    arrival = arrival[: arrival.index("\n  }") + 4]

    assert "rows()[0]" in arrival, (
        "nothing picks the first row when the panel arrives empty"
    )
    assert "inspect(first.dataset.songId)" in arrival, arrival

    # Describing, not starting: no queue is built and no audio is set.
    assert "setQueue" not in arrival, "arriving on the page starts playing"
    assert "audio.play" not in arrival, arrival


async def test_a_panel_the_server_already_filled_is_left_alone(tmp_path):
    """A reload during playback, or a bookmarked song: the shell renders
    the panel itself, and overwriting it with row one would throw that
    away."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    guard = script[script.index('if (!document.querySelector("#inspector [data-song-id]"))'):]
    guard = guard[: guard.index("\n  }")]
    assert "rows()[0]" in guard, (
        "the first row is chosen whatever the panel already holds"
    )
