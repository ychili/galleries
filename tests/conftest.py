"""Shared pytest test fixtures"""

from pathlib import Path

import pytest

import galleries.cli


@pytest.fixture
def global_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reroute calls to ``galleries.cli.get_global_config_dir`` to tmp_path.

    Return the path object for the temporary global config directory.
    """

    def mock_global_config_dir():
        return tmp_path / "mock_global_config_dir"

    monkeypatch.setattr(galleries.cli, "get_global_config_dir", mock_global_config_dir)
    return mock_global_config_dir()


@pytest.fixture
def real_path(global_config_dir: Path) -> Path:
    """Create and return ``global_config_dir`` as a real directory."""
    global_config_dir.mkdir()
    return global_config_dir
