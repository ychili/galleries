"""Tests for I/O functions of refresh, using pytest"""

import pytest

import galleries.galleryms
import galleries.refresh

# bytes(random.randrange(0x80) for _ in range(30)) =>
RAND_DATA = [
    b"-6\x17XD\x1dclI`E=\x7f:xV?'n}S\x0c\x06\x03eR2\x01yl",
    b'\n5u8l\x13+(\x1c \x1e\x01"|I\x08\x079{K\x13bg%+J\x10}=6',
    b"w~*,\x172\x0f\x1b,\x1fxiLk^&\x1d)eCyF~3\x07\x13AgSH",
    b"\x7f<\x1d\x10c6wy9\x17+JW5SsN\\\x01Y\x18wV2\x07\x01=*\t\\",
    b"\x0f;m*\x0bH(&d\x1az~6;RUT~(Ijym\n>Dfm\x0bv",
    b'"*snn|\x14^Dr#^\x14\x1ah+h\x05\x1c\x06/B9\x13%Uo<M^',
    b"7\x11ORo\x17a\x1f/5\x1f-R\x06J4X\x18fuU\x1fhY{T;=b\x0f",
]
JSON_DATA = '{"key": {\n  "false key": "value"\n  }\n}\n'

_TAG_SET_EXPECTED_SINGLE = galleries.galleryms.TagSet(
    {
        "xilk^&",
        "5u8l\x13+(",
        '\x01"|i\x08\x079{k\x13bg%+j\x10}=6w~*,\x172\x0f\x1b,',
        "/5",
        "cli`e=\x7f:xv?'n}s",
        "\x10c6wy9\x17+jw5ssn\\\x01y\x18wv2\x07\x01=*",
        "-6\x17xd",
        "\x06\x03er2\x01yl",
        ")ecyf~3\x07\x13agsh\x7f<",
        "\\\x0f;m*",
        "\x06/b9\x13%uo<m^7\x11oro\x17a",
        ">dfm",
        "hy{t;=b\x0f",
        'v"*snn|\x14^dr#^\x14\x1ah+h\x05',
        "-r\x06j4x\x18fuu",
        "h(&d\x1az~6;rut~(ijym",
    }
)
_TAG_SET_EXPECTED_MULTIPLE = galleries.galleryms.TagSet(
    {
        "\x06\x03er2\x01yl",
        "cli`e=\x7f:xv?'n}s",
        "w~*,\x172\x0f\x1b,",
        "-6\x17xd",
        "-r\x06j4x\x18fuu",
        "\x7f<",
        '\x01"|i\x08\x079{k\x13bg%+j\x10}=6',
        "/5",
        ">dfm",
        "\x06/b9\x13%uo<m^",
        "\x10c6wy9\x17+jw5ssn\\\x01y\x18wv2\x07\x01=*",
        "\\",
        "h(&d\x1az~6;rut~(ijym",
        ")ecyf~3\x07\x13agsh",
        "5u8l\x13+(",
        "hy{t;=b\x0f",
        "v",
        "7\x11oro\x17a",
        '"*snn|\x14^dr#^\x14\x1ah+h\x05',
        "xilk^&",
        "\x0f;m*",
    }
)
_JSON_EXPECTED = [("key", "{'false key': 'value'}")]
_DESCRIPTORS_EXPECTED = frozenset(
    {
        galleries.galleryms.DescriptorImplication(desc)
        for desc in ["clI`E=\x7f:xV?'n}S", "-6\x17XD", "\x06\x03eR2\x01yl"]
    }
)


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
    path.write_bytes(b"".join(RAND_DATA))
    tagset = galleries.refresh.get_tags_from_file(path)
    assert tagset == _TAG_SET_EXPECTED_SINGLE


def test_get_tags_from_multiple_files(tmp_path):
    path_data = [
        (tmp_path / f"tag_file_{i}.txt", data)
        for i, data in enumerate(RAND_DATA, start=1)
    ]
    for path, data in path_data:
        path.write_bytes(data)
    tagset = galleries.refresh.get_tags_from_file(*[path for path, _ in path_data])
    assert tagset == _TAG_SET_EXPECTED_MULTIPLE


def test_get_aliases_error(tmp_path, caplog):
    path = tmp_path / "aliases_file.json"
    path.write_bytes(b"".join(RAND_DATA))
    # JSONDecodeError is caught
    aliases = galleries.refresh.get_aliases(path)
    assert not aliases
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_get_aliases_valid(tmp_path):
    path = tmp_path / "aliases_file.json"
    path.write_text(JSON_DATA)
    aliases = galleries.refresh.get_aliases(path)
    assert aliases == dict(_JSON_EXPECTED)


def test_get_descriptor_implications(tmp_path):
    path = tmp_path / "descriptors.asc"
    path.write_bytes(RAND_DATA[0])
    descriptors = galleries.refresh.get_implications(path)
    assert descriptors == _DESCRIPTORS_EXPECTED


def test_get_regular_implications(tmp_path):
    path = tmp_path / "implications.json"
    path.write_text(JSON_DATA)
    implications = galleries.refresh.get_implications(path)
    assert implications == frozenset(
        {galleries.galleryms.RegularImplication(*_JSON_EXPECTED[0])}
    )


def test_unknown_implications(tmp_path, caplog):
    path = tmp_path / "unknown_implications_file.spam"
    path.write_bytes(RAND_DATA[-1])
    result = galleries.refresh.get_implications(path)
    assert not result
    assert any(
        path.name in record.message
        for record in caplog.records
        if record.levelname == "WARNING"
    )


def test_tag_actions_object_invalid(tmp_path, caplog):
    path = tmp_path / "tag_actions_file.json"
    path.write_bytes(b"".join(RAND_DATA))
    # JSONDecodeError is caught
    galleries.refresh.TagActionsObject().read_file(path)
    assert any(record.levelname == "ERROR" for record in caplog.records)
