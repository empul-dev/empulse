import os
import stat
import subprocess
import sys


def test_generated_secret_file_is_owner_only(tmp_path):
    """The auto-generated secret key must never be group/world readable."""
    env = {
        **os.environ,
        "DB_PATH": str(tmp_path / "empulse.db"),
        "SECRET_KEY": "",
    }
    # Fresh interpreter so the module-level key generation runs. umask 0 plus a
    # no-op chmod exposes the mode the file was *created* with, which a later
    # chmod would hide (the key would be world-readable until then).
    code = (
        "import os, pathlib; os.umask(0); "
        "pathlib.Path.chmod = lambda *a, **k: None; "
        "import empulse.config"
    )
    subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, check=True)

    secret = tmp_path / ".empulse_secret"
    assert len(secret.read_text().strip()) == 64
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
