"""Long jobs in a ribbon: start an import and keep working."""

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


async def test_both_job_buttons_send_their_job_to_the_ribbon(tmp_path):
    """Not to a slot beside themselves: the nav is rebuilt on a playlist
    change, and that would take a running import with it."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get(f"/?playlist={PLAYLIST_ID}")).text

    for kind in ("check", "import"):
        button = re.search(
            r"<button[^>]*hx-post=\"/playlists/[^\"]*/" + kind + r"\"[^>]*>",
            body,
            re.DOTALL,
        )
        assert button, f"no {kind} button"
        assert 'hx-target="#jobs"' in button.group(0), kind
        assert 'hx-swap="beforeend"' in button.group(0), kind


async def test_the_job_buttons_appear_only_for_a_chosen_playlist(tmp_path):
    """Import needs a playlist; there is nothing to import "everything"
    from."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        everything = (await client.get("/")).text

    assert "/import" not in everything
    assert "/check" not in everything


async def test_the_import_button_still_warns_before_a_long_download(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get(f"/?playlist={PLAYLIST_ID}")).text

    button = re.search(
        r"<button[^>]*hx-post=\"/playlists/[^\"]*/import\"[^>]*>",
        body,
        re.DOTALL,
    )
    assert "hx-confirm" in button.group(0), (
        "a long download must not start on a stray click"
    )


async def test_a_ribbon_entry_names_the_playlist_it_belongs_to(
    tmp_path, monkeypatch
):
    """The ribbon is global; two playlists can be busy at once."""

    def fake_check(repository_path, playlist_id, progress=None):
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
    assert PLAYLIST_ID not in started.text.replace(
        f"job-check-{PLAYLIST_ID}", ""
    ).replace(f"/playlists/{PLAYLIST_ID}/", "").replace(
        f"check:{PLAYLIST_ID}", ""
    ), "the raw id leaked into the visible text"


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


async def test_the_report_lands_in_the_inspector_not_on_a_page(
    tmp_path, monkeypatch
):
    """Its counts fit in the ribbon; which songs failed and why do not."""

    async def fake_import(repository_path, playlist_id, progress=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=2,
            already_local=0,
            imported=[],
            failed=[
                SimpleNamespace(
                    youtube_id="zzzzzzzzzzz",
                    reason="age restricted",
                    issue="AgeRestrictedError",
                    retryable=False,
                )
            ],
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)

        for _ in range(80):
            settled = (
                await client.get(f"/jobs/import:{PLAYLIST_ID}", headers=HX)
            ).text
            if "hx-trigger" not in settled:
                break

        assert 'hx-target="#inspector"' in settled, (
            "the report still navigates away from the console"
        )

        fragment = (
            await client.get(
                f"/jobs/import:{PLAYLIST_ID}/report", headers=HX
            )
        ).text

    for tag in ("<html", "<body", "<head"):
        assert tag not in fragment, tag
    assert "age restricted" in fragment
    assert "zzzzzzzzzzz" in fragment


async def test_the_report_page_still_works_without_htmx(tmp_path, monkeypatch):
    """A bookmarked report URL must not answer with a bare fragment."""

    async def fake_import(repository_path, playlist_id, progress=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=0, already_local=0, imported=[], failed=[]
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import")

        for _ in range(80):
            job = client._transport.app.state.jobs.get(
                f"import:{PLAYLIST_ID}"
            )
            if job and job.state is not JobState.RUNNING:
                break

        page = (
            await client.get(f"/jobs/import:{PLAYLIST_ID}/report")
        ).text

    assert "<html" in page


async def test_a_junk_import_is_fixable_from_the_report(tmp_path, monkeypatch):
    """Imported without a Shazam match: on disk, still junk."""

    async def fake_import(repository_path, playlist_id, progress=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            total_remote=1,
            already_local=0,
            imported=[
                SimpleNamespace(
                    youtube_id="aaaaaaaaaaa",
                    artist="UNKNOWN",
                    title="Something",
                    filename="UNKNOWN - Something [aaaaaaaaaaa] (JUNK).mp3",
                    shazam_match_score=None,
                    is_junk=True,
                )
            ],
            failed=[],
        )

    monkeypatch.setattr("pypl2mp3.web.app.import_playlist", fake_import)
    _make_song(tmp_path, "ARTIST", "Song", "bbbbbbbbbbb")

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)

        for _ in range(80):
            settled = (
                await client.get(f"/jobs/import:{PLAYLIST_ID}", headers=HX)
            ).text
            if "hx-trigger" not in settled:
                break

        fragment = (
            await client.get(
                f"/jobs/import:{PLAYLIST_ID}/report", headers=HX
            )
        ).text

    assert "/fragments/inspector/aaaaaaaaaaa" in fragment, (
        "no way to repair the song the report just flagged"
    )
