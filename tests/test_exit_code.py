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


def test_fatal_error_exits_non_zero(tmp_path):
    # Un identifiant de playlist invalide provoque une erreur fatale.
    result = _run("import", "not-a-playlist-id", "-r", str(tmp_path))

    assert result.returncode != 0, (
        "une erreur critique doit produire un code de sortie non nul"
    )
