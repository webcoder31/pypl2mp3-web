"""Long jobs in a ribbon: start an import and keep working."""

import asyncio
import re
from pathlib import Path

import httpx

from pypl2mp3.web.app import create_app
from pypl2mp3.web.jobs import JobState

PLAYLIST_ID = "PL0000000000000000000000000000001"
PLAYLIST = f"Owner - Alpha [{PLAYLIST_ID}]"
HX = {"HX-Request": "true"}

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, artist, title, vid):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{artist} - {title} [{vid}].mp3").write_bytes(_MP3_FRAME * 8)


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_the_console_has_a_ribbon_for_running_jobs(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    assert 'id="jobs"' in body

    # The ribbon lives in the header and nothing may swap the header:
    # a running import must outlive every other interaction.
    header = re.search(r"<header[^>]*>", body).group(0)
    assert "data-swap-region" not in header, (
        "swapping the header would take running jobs off the screen"
    )
    assert body.index('id="header"') < body.index('id="jobs"'), (
        "the ribbon is not in the header"
    )


async def _settle_pane(client, app, job_id):
    """Run the pane's poll until its job stops, and return the markup."""

    for _ in range(100):
        job = app.state.jobs.get(job_id)
        if job and job.state.value not in ("pending", "running"):
            break
        await asyncio.sleep(0.02)

    response = await client.get(
        f"/fragments/imports?playlist={PLAYLIST_ID}", headers=HX
    )

    return response.text


async def test_one_button_starts_the_whole_import(tmp_path):
    """Checking and importing were never separate intentions: nobody asks
    what is new without meaning to decide what to do about it.

    The one button looks, then hands you the list. It targets the imports
    pane and not a slot beside itself, because the nav is rebuilt on a
    playlist change and that would take a running import with it.
    """

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get(f"/?playlist={PLAYLIST_ID}")).text

    buttons = re.findall(
        r"<button[^>]*hx-post=\"/playlists/[^\"]*\"[^>]*>", body, re.DOTALL
    )
    assert len(buttons) == 1, (
        f"{len(buttons)} playlist buttons; the pair was meant to become one"
    )
    assert "/check" in buttons[0], buttons[0]
    assert 'hx-target="#imports-body"' in buttons[0], buttons[0]
    assert 'data-open-tab="imports"' in buttons[0], (
        "the button starts work in a pane it does not bring you to"
    )


async def test_nothing_downloads_before_you_have_seen_the_list(tmp_path):
    """What the old confirmation dialog was standing in for.

    The button used to fetch every missing song on one click, so it had
    to ask first. It now runs a check and shows what it found; the only
    thing that downloads anything is Start import, and by then you have
    read the list and the count. That is a stronger guarantee than a
    dialog, so the dialog is gone rather than kept as decoration.
    """

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get(f"/?playlist={PLAYLIST_ID}")).text

    posts = re.findall(r'hx-post="(/playlists/[^"]*)"', body)
    assert posts == [f"/playlists/{PLAYLIST_ID}/check"], (
        f"the shell can start something other than a check: {posts}"
    )


async def test_the_pane_names_the_playlist_it_is_working_on(
    tmp_path, monkeypatch
):
    """Two playlists can be busy at once, and the pane shows one of them.
    Its heading is the only thing saying which."""

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        from types import SimpleNamespace

        return SimpleNamespace(total_remote=1, already_local=1, missing=[])

    monkeypatch.setattr(
        "pypl2mp3.web.app.check_new_songs", fake_check
    )
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        started = await client.post(
            f"/playlists/{PLAYLIST_ID}/check", headers=HX
        )

    assert "Owner - Alpha" in started.text, started.text

    # Everything between angle brackets is markup — ids belong there, in
    # urls and element ids. What is left is what a reader sees, and a
    # thirty-four character playlist id is not a name. Stripping tags
    # rather than listing the places the id is allowed: that list rots
    # every time a url or an attribute changes.
    visible = re.sub(r"<[^>]*>", " ", started.text)
    assert PLAYLIST_ID not in visible, (
        f"the raw id leaked into the visible text: {visible.strip()[:120]}"
    )


async def test_a_finished_entry_can_be_dismissed(tmp_path, monkeypatch):
    """The ribbon would otherwise fill up with yesterday's runs."""

    def fake_check(repository_path, playlist_id, progress=None):
        from types import SimpleNamespace

        return SimpleNamespace(total_remote=1, already_local=1, missing=[])

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)

        for _ in range(80):
            settled = (
                await client.get(f"/jobs/check:{PLAYLIST_ID}", headers=HX)
            ).text
            if "hx-trigger" not in settled:
                break

    assert "data-dismiss-job" in settled, "a finished job cannot be cleared"
    assert "hx-trigger" not in settled, "it is still polling"


async def test_a_running_entry_offers_no_dismiss_button(tmp_path):
    """Removing it would lose sight of a job that keeps running."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        started = await client.post(
            f"/playlists/{PLAYLIST_ID}/check", headers=HX
        )

    if "hx-trigger" in started.text:
        assert "data-dismiss-job" not in started.text


async def test_starting_the_same_job_twice_leaves_one_entry(tmp_path):
    """beforeend appends, so two clicks would stack two elements sharing
    one id."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert "seen.has(entry.id)" in script, "the ribbon does not de-duplicate"
    assert ".reverse()" in script, (
        "keeping the older entry would let a finished job shadow a fresh run"
    )


async def test_a_failed_song_says_why_on_its_own_row(tmp_path, monkeypatch):
    """This is what the report page was for.

    Counts fitted in a ribbon; which songs failed and why did not, so
    they went to a page. The pane has room for both, so the page is gone
    and its job is done here — beside the song it is about.
    """

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("zzzzzzzzzzz", "SOMEBODY - Forbidden")
        progress.item_started("zzzzzzzzzzz", "1/1")
        progress.item_failed(
            "zzzzzzzzzzz", "age restricted", "AgeRestrictedError: nope"
        )
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    assert "SOMEBODY - Forbidden" in pane, pane
    assert "age restricted" in pane, pane


async def test_a_junk_import_is_fixable_from_its_row(tmp_path, monkeypatch):
    """Imported without a Shazam match: on disk, still junk.

    The row it arrived on is where it gets repaired — the outcome and
    the fix are the same click, which is all the report page ever
    offered.
    """

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "UNKNOWN - Something")
        progress.item_started("aaaaaaaaaaa", "1/1")
        progress.item_done("aaaaaaaaaaa")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "bbbbbbbbbbb")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    row = re.search(r'<li class="import-row done"(.*?)</li>', pane, re.DOTALL)
    assert row, pane[-400:]
    assert 'data-song-id="aaaaaaaaaaa"' in row.group(1), (
        f"the finished row does not say which song it is: {row.group(1)[:200]}"
    )


async def test_the_report_page_is_gone(tmp_path):
    """It carried counts, failures and a way into the fix screen. The
    pane carries all three, beside the songs they belong to, without
    leaving the page the player is running on."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        gone = await client.get("/jobs/import:whatever/report")

    assert gone.status_code == 404


async def test_dismissing_the_last_job_leaves_no_gap(tmp_path):
    """Measured in a browser: the header went 70px, 113px with a job,
    then 86px after dismissing it — sixteen it never gave back.

    Every swap leaves the whitespace around its fragment behind, so the
    container ended up holding a dozen text nodes and no elements. That
    is not `:empty`, so the rule that hides it stopped matching, and
    because the ribbon spans the header's full width it went on
    reserving a flex line and the gap that separates one.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text
        script = (await client.get("/static/console.js")).text

    assert "#jobs:empty { display: none; }" in css, (
        "nothing hides the ribbon when it holds nothing"
    )

    handler = script[script.index("[data-dismiss-job]") :]
    handler = handler[: handler.index("\n  });")]
    assert "replaceChildren()" in handler, (
        "the leftover text nodes stay, so :empty never matches again"
    )
    assert "jobs.children.length" in handler, (
        "clearing unconditionally would drop the jobs still running"
    )


async def test_dismissing_one_of_two_jobs_keeps_the_other(tmp_path):
    """The clear must be conditional: two playlists can be busy at once."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    handler = script[script.index("[data-dismiss-job]") :]
    handler = handler[: handler.index("\n  });")]

    guard = re.search(r"if \(([^)]*)\)\s*jobs\.replaceChildren", handler)
    assert guard, handler
    assert "!jobs.children.length" in guard.group(1), guard.group(1)


async def test_a_song_shazam_could_not_name_says_so(tmp_path, monkeypatch):
    """Zero is not a low score, it is no identification at all.

    song.py coerces a missing match to 0 and the callbacks pass it
    straight on, so a row printing "0%" reads as a song that scored badly
    rather than one that was never named — which is exactly the row you
    would click to go and fix.
    """

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "UNKNOWN - Something")
        progress.item_started("aaaaaaaaaaa", "1/1")
        progress.song_identified("", "", 0.0)
        progress.item_done("aaaaaaaaaaa")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "bbbbbbbbbbb")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    assert "no match" in pane, pane
    assert "0%" not in pane, "a song Shazam never named is shown as scoring 0"


async def test_a_matched_song_shows_its_score(tmp_path, monkeypatch):
    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_started("aaaaaaaaaaa", "1/1")
        progress.song_identified("IAMX", "Kiss", 91.4)
        progress.item_done("aaaaaaaaaaa")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "bbbbbbbbbbb")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    assert "91%" in pane, pane


async def test_a_song_being_fetched_keeps_the_name_it_was_listed_under(
    tmp_path, monkeypatch
):
    """What the browser showed before this was fixed: "1/4".

    The check draws up the list and knows the names. The sweep announces
    a position, because that is all it has until YouTube answers. The
    pane shows one row per song and has to take each half from the job
    that holds it.
    """

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss + Swallow")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, missing=["aaaaaaaaaaa"]
        )

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "")
        progress.item_started("aaaaaaaaaaa", "1/4")
        progress.item_done("aaaaaaaaaaa")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "bbbbbbbbbbb")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        await _settle_pane(client, app, f"check:{PLAYLIST_ID}")
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    assert "IAMX - Kiss + Swallow" in pane, (
        f"the row lost its name once work began on it: {pane[-500:]}"
    )


async def test_a_second_import_can_be_started_after_the_first(
    tmp_path, monkeypatch
):
    """The pane showed the finished import for ever.

    "The import wins over the check" is right while one is running — the
    list you chose from is history and the rows that matter are the ones
    being fetched. It stops being right the moment you ask for a new
    list: the run that matters is then the newer one, and there was no
    way back to a selection.
    """

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, missing=["aaaaaaaaaaa"]
        )

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "")
        progress.item_started("aaaaaaaaaaa", "1/1")
        progress.item_done("aaaaaaaaaaa")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "bbbbbbbbbbb")
    app = create_app(tmp_path)

    async with _client(app) as client:
        # One whole cycle: look, choose, fetch.
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        await _settle_pane(client, app, f"check:{PLAYLIST_ID}")
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        done = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")
        assert "Start import" not in done, done

        # And now the same button again.
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        again = await _settle_pane(client, app, f"check:{PLAYLIST_ID}")

    assert "Start import" in again, (
        "the pane is still showing the finished import, so there is no "
        "way to start a second one"
    )
    assert "IAMX - Kiss" in again, again


async def test_a_running_import_outranks_the_check_that_fed_it(
    tmp_path, monkeypatch
):
    """The other half of the same rule, and the reason it exists: while
    songs are being fetched, the list they were chosen from is history."""

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, missing=["aaaaaaaaaaa"]
        )

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "")
        progress.item_started("aaaaaaaaaaa", "1/1")
        started.set()
        await release.wait()
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", slow_import)
    _make_song(tmp_path, "ARTIST", "Song", "bbbbbbbbbbb")
    app = create_app(tmp_path)

    try:
        async with _client(app) as client:
            await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
            await _settle_pane(client, app, f"check:{PLAYLIST_ID}")
            await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
            await started.wait()

            pane = (
                await client.get(
                    f"/fragments/imports?playlist={PLAYLIST_ID}", headers=HX
                )
            ).text

        assert "Start import" not in pane, (
            "the pane offers to start an import while one is running"
        )
        assert "Importing" in pane, pane
    finally:
        release.set()


def _slow_import(started, release, done_first=True):
    """An import that fetches one song, then waits to be let go."""

    async def run(repository_path, playlist_id, progress=None, only=None):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_listed("bbbbbbbbbbb", "IAMX - Spit It Out")
        progress.item_started("aaaaaaaaaaa", "1/2")
        if done_first:
            progress.item_done("aaaaaaaaaaa")
        progress.item_started("bbbbbbbbbbb", "2/2")
        started.set()
        await release.wait()
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2, already_local=0, imported=[], failed=[]
        )

    return run


async def test_a_running_import_shows_its_progress_on_the_tab(
    tmp_path, monkeypatch
):
    """The tab strip is outside the pane, so the pane cannot render it —
    it publishes the count and the strip copies it across.

    A count and not a dot: how far along a twelve-song import is, is the
    thing you switched away from the pane in order not to watch.
    """

    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(
        "pypl2mp3.web.app.import_playlist", _slow_import(started, release)
    )
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    try:
        async with _client(app) as client:
            await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
            await started.wait()
            pane = (
                await client.get(
                    f"/fragments/imports?playlist={PLAYLIST_ID}", headers=HX
                )
            ).text

        assert 'data-badge="1/2"' in pane, pane[:300]
    finally:
        release.set()


async def test_the_tab_says_nothing_when_nothing_is_running(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")

    async with _client(create_app(tmp_path)) as client:
        pane = (
            await client.get(
                f"/fragments/imports?playlist={PLAYLIST_ID}", headers=HX
            )
        ).text

    assert 'data-badge=""' in pane, pane[:300]


async def test_an_import_can_be_stopped(tmp_path, monkeypatch):
    """Twelve songs is a long time to be sure about."""

    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(
        "pypl2mp3.web.app.import_playlist", _slow_import(started, release)
    )
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    try:
        async with _client(app) as client:
            await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
            await started.wait()

            running = (
                await client.get(
                    f"/fragments/imports?playlist={PLAYLIST_ID}", headers=HX
                )
            ).text
            assert ">Stop<" in running, "no way to stop a run in progress"

            stopped = (
                await client.post(
                    f"/playlists/{PLAYLIST_ID}/import/stop", headers=HX
                )
            ).text

        assert app.state.jobs.get(f"import:{PLAYLIST_ID}").state.value == (
            "cancelled"
        )
        assert "Stopped" in stopped, stopped
        # What arrived stays, and the pane says how much did.
        assert "1 imported" in stopped, stopped
    finally:
        release.set()


async def test_a_stopped_run_is_not_reported_as_finished(
    tmp_path, monkeypatch
):
    """"4 imported" for a run of twelve you stopped yourself says nothing
    about the other eight — they did not fail, they were never tried."""

    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(
        "pypl2mp3.web.app.import_playlist", _slow_import(started, release)
    )
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    try:
        async with _client(app) as client:
            await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
            await started.wait()
            stopped = (
                await client.post(
                    f"/playlists/{PLAYLIST_ID}/import/stop", headers=HX
                )
            ).text

        assert "Stopped" in stopped
        assert "Importing" not in stopped, "the pane still reads as running"
        assert "hx-trigger" not in stopped, (
            "the pane goes on polling a run that has stopped"
        )
    finally:
        release.set()


async def test_stopping_lets_the_listing_catch_up(tmp_path, monkeypatch):
    """Songs reached the disk before the stop, and the page has no other
    way of learning that."""

    started, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(
        "pypl2mp3.web.app.import_playlist", _slow_import(started, release)
    )
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    try:
        async with _client(app) as client:
            await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
            await started.wait()
            await client.post(
                f"/playlists/{PLAYLIST_ID}/import/stop", headers=HX
            )
            await asyncio.sleep(0.05)
            poll = await client.get(
                f"/jobs/import:{PLAYLIST_ID}", headers=HX
            )

        assert poll.headers.get("HX-Trigger") == "songsChanged", (
            "a stopped import leaves songs on disk the listing never shows"
        )
    finally:
        release.set()


async def test_every_row_carries_its_id_and_a_way_to_watch_it(
    tmp_path, monkeypatch
):
    """The id is not decoration in this panel.

    YouTube refuses to name a video often enough that the id is
    sometimes all there is, and the link beside it is then the only way
    to find out what the song actually is. Both are shown for every row,
    named or not — the same way the listing shows them.
    """

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_listed("bbbbbbbbbbb", "")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2, already_local=0,
            missing=["aaaaaaaaaaa", "bbbbbbbbbbb"],
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        pane = await _settle_pane(client, app, f"check:{PLAYLIST_ID}")

    for youtube_id in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        assert f'<span class="id">{youtube_id}</span>' in pane, youtube_id
        assert f"https://youtu.be/{youtube_id}" in pane, youtube_id

    # And a song nobody could name says so, rather than wearing its id
    # as a title.
    assert "unnamed" in pane, pane


async def test_the_number_on_a_finished_row_says_it_is_a_shazam_score(
    tmp_path, monkeypatch
):
    """A bare "91%" beside a finished download reads as how much of it
    arrived."""

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_started("aaaaaaaaaaa", "1/1")
        progress.song_identified("IAMX", "Kiss", 91.0)
        progress.item_done("aaaaaaaaaaa")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    # Scoped to the row: the header carries its own counts, and a match
    # anywhere on the page would pass while the row said only "91%".
    row = re.search(r'<li class="import-row done"(.*?)</li>', pane, re.DOTALL)
    assert row, pane[-400:]
    assert "91%" in row.group(1), row.group(1)
    assert "Shazam" in row.group(1), (
        f"the number stands on its own: {row.group(1).strip()[-200:]}"
    )


async def test_only_a_song_that_arrived_answers_a_click(tmp_path, monkeypatch):
    """Nothing reached the disk for a row that failed, so there is
    nothing to open. A row that answers a click by doing nothing is
    worse than one that plainly does not."""

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_listed("bbbbbbbbbbb", "IAMX - Spit It Out")
        progress.item_started("aaaaaaaaaaa", "1/2")
        progress.item_done("aaaaaaaaaaa")
        progress.item_started("bbbbbbbbbbb", "2/2")
        progress.item_failed("bbbbbbbbbbb", "age restricted", "nope")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    rows = dict(
        re.findall(r'<li class="import-row (\w+)"([^>]*)>', pane)
    )
    assert "data-song-id" in rows["done"], rows
    assert "data-song-id" not in rows["failed"], (
        "a row that failed offers to open a song that was never written"
    )


async def test_the_pane_says_what_a_click_will_do(tmp_path):
    """Green where a click opens something, grey where it does not, and
    a pointer only on the first."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text
        script = (await client.get("/static/console.js")).text

    done = re.search(r"\.import-row\.done:hover \{([^}]*)\}", css)
    failed = re.search(r"\.import-row\.failed:hover \{([^}]*)\}", css)
    assert done and failed, css[-400:]
    assert "var(--accent-soft)" in done.group(1), done.group(1)
    assert "cursor: pointer" in done.group(1), (
        "the row lights up without saying it can be clicked"
    )
    assert "cursor: pointer" not in failed.group(1), (
        "a row with nothing to open still invites a click"
    )

    # And the click is wired to the rows that carry an id, not to every
    # row in the pane.
    assert '.import-row[data-song-id]' in script, (
        "nothing acts on the row, so it lights up and does nothing"
    )


async def test_the_name_of_a_finished_song_is_not_a_label(
    tmp_path, monkeypatch
):
    """The click handler leaves labels alone, so that ticking a row
    during selection is not also read as opening it.

    Rendering the name as a label on every row therefore swallowed the
    click on exactly the rows meant to answer one — and the name is the
    obvious place to click. The browser showed it; nothing else did.
    """

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_started("aaaaaaaaaaa", "1/1")
        progress.item_done("aaaaaaaaaaa")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        pane = await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    row = re.search(r'<li class="import-row done"(.*?)</li>', pane, re.DOTALL)
    assert row, pane[-400:]
    assert "<label" not in row.group(1), (
        "the name is a label with no checkbox behind it, so clicking it "
        "does nothing"
    )


async def test_the_name_of_a_song_being_chosen_is_a_label(
    tmp_path, monkeypatch
):
    """The other half: while choosing, clicking the name ticks the box."""

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, missing=["aaaaaaaaaaa"]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        pane = await _settle_pane(client, app, f"check:{PLAYLIST_ID}")

    assert '<label class="import-name" for="pick-aaaaaaaaaaa"' in pane, pane


async def test_start_import_is_filled_and_follows_the_choosing(
    tmp_path, monkeypatch
):
    """It is the point of the panel it sits in, the way Save is the point
    of the inspector — and it comes after the box that changes what it
    will act on, because you choose before you commit."""

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, missing=["aaaaaaaaaaa"]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        pane = await _settle_pane(client, app, f"check:{PLAYLIST_ID}")
        css = (await client.get("/static/console.css")).text

    assert pane.index('id="pick-all"') < pane.index("Start import"), (
        "the button that commits comes before the box that changes what "
        "it will act on"
    )

    # Filled by the rule Save is filled by, not by one of its own that
    # could drift into a nearly-matching green.
    rules = [
        selector
        for selector, body in re.findall(
            r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{([^}]*)\}", css
        )
        if "#import-form button[type=\"submit\"]" in selector
        and ":hover" not in selector
        and "background: var(--accent);" in body
    ]
    assert rules, "Start import is as quiet as the rows above it"
    assert '#inspector button[type="submit"]' in rules[0], rules[0]


async def test_pressing_start_keeps_the_list_on_screen(tmp_path, monkeypatch):
    """The panel used to empty itself the moment you pressed Start.

    The rows came from the import job, and an import cannot name a single
    song until it has fetched the playlist from YouTube again — so the
    list vanished, stayed blank for as long as that round trip took, and
    came back with a run already several songs deep. The list you chose
    from was on screen and correct the whole time.
    """

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        for youtube_id, name in (
            ("aaaaaaaaaaa", "IAMX - Kiss"),
            ("bbbbbbbbbbb", "IAMX - Spit It Out"),
            ("ccccccccccc", "IAMX - Bring Me Back a Dog"),
        ):
            progress.item_listed(youtube_id, name)
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=3, already_local=0,
            missing=["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"],
        )

    reached = asyncio.Event()
    release = asyncio.Event()

    async def slow_to_start(repository_path, playlist_id, progress=None,
                            only=None):
        # Stuck exactly where the real one is: fetching the playlist,
        # before it can announce anything at all.
        reached.set()
        await release.wait()
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=3, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", slow_to_start)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    try:
        async with _client(app) as client:
            await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
            await _settle_pane(client, app, f"check:{PLAYLIST_ID}")

            started = await client.post(
                f"/playlists/{PLAYLIST_ID}/import",
                headers=HX,
                data={"selection": "1",
                      "songs": ["aaaaaaaaaaa", "ccccccccccc"]},
            )
            await reached.wait()

        rows = re.findall(r'<li class="import-row (\w+)"', started.text)
        assert len(rows) == 2, (
            f"the panel shows {len(rows)} rows while the import is still "
            "fetching the playlist; it should still be showing what you "
            "ticked"
        )
        assert "IAMX - Kiss" in started.text, started.text
        assert "IAMX - Bring Me Back a Dog" in started.text
        assert "IAMX - Spit It Out" not in started.text, (
            "a song that was unticked is still listed"
        )
    finally:
        release.set()


async def test_a_new_look_is_not_narrowed_by_the_last_selection(
    tmp_path, monkeypatch
):
    """Whatever was ticked for the last run has nothing to say about
    what the next check finds.

    What holds this is not a line clearing the selection — that was
    unreachable — but that the panel reads it only while the import is
    the newer of the two jobs. A check is newer, so it shows everything
    it found.
    """

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_listed("bbbbbbbbbbb", "IAMX - Spit It Out")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2, already_local=0,
            missing=["aaaaaaaaaaa", "bbbbbbbbbbb"],
        )

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        await _settle_pane(client, app, f"check:{PLAYLIST_ID}")
        await client.post(
            f"/playlists/{PLAYLIST_ID}/import", headers=HX,
            data={"selection": "1", "songs": ["aaaaaaaaaaa"]},
        )
        await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        again = await _settle_pane(client, app, f"check:{PLAYLIST_ID}")

    assert "IAMX - Spit It Out" in again, (
        "the new list is still narrowed by what was ticked last time"
    )


async def test_unticking_every_row_imports_nothing(tmp_path, monkeypatch):
    """The worst reading of a gesture, and it was the one taken.

    An unticked checkbox sends nothing, so a form with every row unticked
    reaches the server looking exactly like a form with no rows at all —
    which the route read as "no selection given", which means everything
    missing. Unticking the lot downloaded the lot.
    """

    asked = {}

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        progress.item_listed("bbbbbbbbbbb", "IAMX - Spit It Out")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2, already_local=0,
            missing=["aaaaaaaaaaa", "bbbbbbbbbbb"],
        )

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        asked["only"] = only
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        await _settle_pane(client, app, f"check:{PLAYLIST_ID}")
        # Exactly what the browser sends when nothing is ticked: the
        # marker, and not one song.
        await client.post(
            f"/playlists/{PLAYLIST_ID}/import", headers=HX,
            data={"selection": "1"},
        )
        await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    assert asked["only"] == [], (
        f"unticking every row asked the service for {asked['only']!r}, and "
        "None means everything missing"
    )


async def test_a_caller_that_sends_no_selection_still_gets_everything(
    tmp_path, monkeypatch
):
    """The other half. Nothing in the panel does this, but the route is
    the CLI's shape too: no selection means the whole of what is
    missing, and that must not be collateral of the fix above."""

    asked = {}

    async def fake_import(repository_path, playlist_id, progress=None,
                          only=None):
        asked["only"] = only
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        await _settle_pane(client, app, f"import:{PLAYLIST_ID}")

    assert asked["only"] is None, asked


async def test_the_panel_always_says_a_selection_was_made(tmp_path,
                                                          monkeypatch):
    """The marker is what carries the distinction, so it has to be in
    the form whatever is ticked."""

    def fake_check(repository_path, playlist_id, progress=None,
                   with_labels=False):
        progress.item_listed("aaaaaaaaaaa", "IAMX - Kiss")
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1, already_local=0, missing=["aaaaaaaaaaa"]
        )

    monkeypatch.setattr("pypl2mp3.web.app.check_new_songs", fake_check)
    _make_song(tmp_path, "ARTIST", "Song", "zzzzzzzzzzz")
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        pane = await _settle_pane(client, app, f"check:{PLAYLIST_ID}")

    assert '<input type="hidden" name="selection"' in pane, pane
