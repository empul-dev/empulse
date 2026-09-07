"""Application release identity, shared by startup protection and the UI."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import tomllib


def get_version() -> str:
    # Container images include pyproject.toml; prefer their shipped source version
    # so editable development installs cannot report another checkout's release.
    project = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if project.is_file():
        return tomllib.loads(project.read_text())["project"]["version"]
    try:
        return version("empulse")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "Cannot determine release version for update backups"
        ) from exc
