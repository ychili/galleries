"""Shared pytest test fixtures"""

from pathlib import Path

import pytest

import galleries.cli


@pytest.fixture
def global_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Reroute calls to ``galleries.cli.lib.get_global_config_dir`` to tmp_path.

    Return the path object for the temporary global config directory.
    """

    def mock_global_config_dir() -> Path:
        return tmp_path / "mock_global_config_dir"

    monkeypatch.setattr(
        galleries.cli.lib, "get_global_config_dir", mock_global_config_dir
    )
    return mock_global_config_dir()


@pytest.fixture
def real_path(global_config_dir: Path) -> Path:
    """Create and return ``global_config_dir`` as a real directory."""
    global_config_dir.mkdir()
    return global_config_dir


@pytest.fixture
def initialize_collection(tmp_path: Path, real_path: Path) -> Path:
    """Initialize default collection."""
    root = tmp_path / "test_collection"
    global_config = real_path / "config"
    global_config.write_text("[global]\ndefault = default\n", encoding="utf-8")
    global_collections = real_path / "collections"
    global_collections.write_text(f"[default]\nroot = {root}", encoding="utf-8")
    galleries.cli.main([f"--collection={root}", "init"])
    galleries.cli.main([f"--collection={root}", "traverse"])
    return root
