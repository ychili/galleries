"""Tests for I/O functions of refresh, using pytest"""

import logging

import pytest

import galleries.galleryms
import galleries.refresh

ASCII_BYTES = [
    (
        b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f"
        b"\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f"
    ),
    b" !\"#$%&'()*+,-./0123456789:;<=>?",
    b"@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_",
    b"`abcdefghijklmnopqrstuvwxyz{|}~\x7f",
]


def test_gardener_update_count(tmp_path):
    """Test a failing example of ``Gardener._update_count``."""
    gard = galleries.refresh.Gardener()
    gard.set_update_count(path_field="Path", count_field="Count", root_path=tmp_path)
    assert all(field in gard.needed_fields for field in ["Path", "Count"])
    gallery_gen = (galleries.galleryms.Gallery(Path=path) for path in ["Not Found"])
    with pytest.raises(galleries.refresh.FolderPathError) as raises_ctx:
        list(gard.garden_rows(gallery_gen))
    assert isinstance(raises_ctx.value.__cause__, FileNotFoundError)


def test_tag_actions_object_invalid(tmp_path, caplog):
    path = tmp_path / "tag_actions_file.json"
    path.write_bytes(b"".join(ASCII_BYTES))
    # JSONDecodeError is caught
    galleries.refresh.TagActionsObject().read_file(path)
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_traverse_fs_error_with_path(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    target = "<invalid-path>"
    root_path = tmp_path / target
    assert not list(galleries.refresh.traverse_fs(root_path))
    assert target in caplog.text
