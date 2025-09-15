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
JSON_DATA = b'{"key": {\n  "false key": "value"\n  }\n}\n'

_TAG_SET_EXPECTED_SINGLE = galleries.galleryms.TagSet(
    {
        "\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b",
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08",
        (
            "!\"#$%&'()*+,-./0123456789:;<=>?@abcdefghijklmnop"
            "qrstuvwxyz[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~\x7f"
        ),
    }
)
_TAG_SET_EXPECTED_MULTIPLE = galleries.galleryms.TagSet(
    {
        "\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b",
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08",
        "!\"#$%&'()*+,-./0123456789:;<=>?",
        "@abcdefghijklmnopqrstuvwxyz[\\]^_",
        "`abcdefghijklmnopqrstuvwxyz{|}~\x7f",
    }
)
_JSON_EXPECTED = [("key", "{'false key': 'value'}")]


def _make_descriptors(*strings):
    return frozenset(
        {galleries.galleryms.DescriptorImplication(word) for word in strings}
    )


_DESCRIPTORS_EXPECTED = [
    _make_descriptors(
        "\x00\x01\x02\x03\x04\x05\x06\x07\x08",
        "\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b",
    ),
    _make_descriptors("!\"#$%&'()*+,-./0123456789:;<=>?"),
    _make_descriptors("@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"),
    _make_descriptors("`abcdefghijklmnopqrstuvwxyz{|}~\x7f"),
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


def test_get_tags_from_single_file(tmp_path):
    path = tmp_path / "tag_file_0.txt"
    path.write_bytes(b"".join(ASCII_BYTES))
    tagset = galleries.refresh.get_tags_from_file(path)
    assert tagset == _TAG_SET_EXPECTED_SINGLE


def test_get_tags_from_multiple_files(tmp_path):
    path_data = [
        (tmp_path / f"tag_file_{i}.txt", data)
        for i, data in enumerate(ASCII_BYTES, start=1)
    ]
    for path, data in path_data:
        path.write_bytes(data)
    tagset = galleries.refresh.get_tags_from_file(*[path for path, _ in path_data])
    assert tagset == _TAG_SET_EXPECTED_MULTIPLE


def test_get_aliases_error(tmp_path, caplog):
    path = tmp_path / "aliases_file.json"
    path.write_bytes(b"".join(ASCII_BYTES))
    # JSONDecodeError is caught
    aliases = galleries.refresh.get_aliases(path)
    assert not aliases
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_get_aliases_valid(tmp_path):
    path = tmp_path / "aliases_file.json"
    path.write_bytes(JSON_DATA)
    aliases = galleries.refresh.get_aliases(path)
    assert aliases == dict(_JSON_EXPECTED)


@pytest.mark.parametrize(
    ("data", "descriptors_expected"),
    zip(ASCII_BYTES, _DESCRIPTORS_EXPECTED, strict=True),
)
def test_get_descriptor_implications(tmp_path, data, descriptors_expected):
    path = tmp_path / "descriptors.asc"
    path.write_bytes(data)
    descriptors = galleries.refresh.get_implications(path)
    assert descriptors == descriptors_expected


def test_get_regular_implications(tmp_path):
    path = tmp_path / "implications.json"
    path.write_bytes(JSON_DATA)
    implications = galleries.refresh.get_implications(path)
    assert implications == frozenset(
        {galleries.galleryms.RegularImplication(*_JSON_EXPECTED[0])}
    )


def test_unknown_implications(tmp_path, caplog):
    path = tmp_path / "unknown_implications_file.spam"
    path.write_bytes(ASCII_BYTES[-1])
    result = galleries.refresh.get_implications(path)
    assert not result
    assert any(
        path.name in record.message
        for record in caplog.records
        if record.levelname == "WARNING"
    )


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
