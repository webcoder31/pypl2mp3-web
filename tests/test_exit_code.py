import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pypl2mp3.main", *args],
        capture_output=True,
        text=True,
    )


def test_successful_command_exits_zero(tmp_path):
    result = _run("playlists", "-r", str(tmp_path))

    assert result.returncode == 0


def test_fatal_error_exits_one(tmp_path):
    # "short" is rejected by the local validation of the identifier format
    # (16 to 34 characters): the error is fatal without touching the
    # network. An identifier of the right length, on the other hand, would
    # go on to query YouTube.
    result = _run("import", "short", "-r", str(tmp_path))

    # Strictly 1: a plain module import failure would also produce a
    # non-zero code, and would therefore pass a "!= 0" assertion.
    assert result.returncode == 1, (
        f"expected 1, got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
