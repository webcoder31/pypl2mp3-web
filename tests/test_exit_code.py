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
    # « short » est rejeté par la validation locale du format d'identifiant
    # (16 à 34 caractères) : l'erreur est fatale sans toucher au réseau.
    # Un identifiant de la bonne longueur, lui, partirait interroger YouTube.
    result = _run("import", "short", "-r", str(tmp_path))

    # Strictement 1 : un simple échec d'import du module produirait lui aussi
    # un code non nul, et passerait donc une assertion « != 0 ».
    assert result.returncode == 1, (
        f"attendu 1, obtenu {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
