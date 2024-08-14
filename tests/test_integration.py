"""Integration tests for the CLI, using pytest"""

import contextlib
import functools
import pathlib
import re
import shutil
import subprocess

import pytest

import galleries.cli

SUBCOMMANDS = [None, "init", "traverse", "count", "query", "refresh", "related"]
DIR_TREE = ["d1", "d1/d1.1", "d1/d1.2", "d2", "d2/d2.1", "d3", "d4"]
FILE_TREE = ["d1/d1.1/f1.1.1", "d1/d1.1/f1.1.2", "d2/f2.1", "d2/d2.1/f2.1.1", "d3/f3.1"]

run_normal = functools.partial(
    subprocess.run, check=True, capture_output=True, encoding="utf-8"
)

# Patch get_global_config_dir for all tests in this module.
pytestmark = pytest.mark.usefixtures("global_config_dir")


def mktree(root, directories, files):
    for path in directories:
        root.joinpath(path).mkdir()
    for path in files:
        root.joinpath(path).touch()


# Use subprocess to test --version and --help and to make sure "galleries" is
# installed on $PATH.


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version_subprocess(flag):
    cmd = "galleries"
    my_galleries = shutil.which(cmd)
    assert my_galleries is not None, "Executable not found on $PATH!"
    args = [my_galleries, flag]
    proc = run_normal(args)
    assert cmd in proc.stdout
    assert galleries.cli.__version__ in proc.stdout


@pytest.mark.parametrize("flag", ["-h", "--help"])
@pytest.mark.parametrize("subcmd", SUBCOMMANDS)
def test_help_subprocess(subcmd, flag):
    my_galleries = shutil.which("galleries")
    assert my_galleries is not None, "Executable not found on $PATH!"
    args = [my_galleries, subcmd, flag]
    proc = run_normal([arg for arg in args if arg])
    assert proc.stdout.startswith("usage: galleries")


# Call cli.main() directly to test these:


def test_help(capsys):
    with contextlib.suppress(SystemExit):
        rc = galleries.cli.main(["--help"])
        assert rc == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("usage:")
    for subcmd in SUBCOMMANDS:
        if subcmd:
            assert subcmd in captured.out


@pytest.mark.parametrize(
    ("argv", "expected"),
    [([], pathlib.Path.cwd), (["-c", "/any/string"], lambda: "/any/string")],
)
def test_path_cmd(capsys, argv, expected):
    rc = galleries.cli.main(argv)
    assert rc == 0
    assert capsys.readouterr().out.strip() == str(expected())


class TestInit:
    def test_bare(self, tmp_path):
        directory = tmp_path / "test_collection"
        rc = galleries.cli.main(["init", "--bare", str(directory)])
        assert rc == 0
        subdir = directory / galleries.cli.DB_DIR_NAME
        assert subdir.is_dir()
        config_file = subdir / galleries.cli.DB_CONFIG_NAME
        assert config_file.is_file()
        assert config_file.read_bytes() == b""

    def test_directory_exists_as_file(self, tmp_path, caplog):
        directory = tmp_path / "test_collection"
        # Create as regular file, not a directory
        directory.touch()
        rc = galleries.cli.main(["init", "--bare", str(directory)])
        assert rc > 0
        assert any(
            "Failed to create root directory" in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )

    def test_config_exists(self, tmp_path, caplog):
        directory = tmp_path / "test_collection"
        directory.mkdir()
        subdir = directory / galleries.cli.DB_DIR_NAME
        subdir.mkdir()
        config_file = subdir / galleries.cli.DB_CONFIG_NAME
        config_file.touch()
        rc = galleries.cli.main(["init", "--bare", str(directory)])
        assert rc > 0
        assert any(
            "Refusing to overwrite existing configuration file" in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )

    def test_template_dir_successful(self, tmp_path, caplog):
        source = tmp_path / "source_collection"
        source.mkdir()
        db_dir = source / "my_db_files"
        db_dir.mkdir()
        file_to_copy = db_dir / "file_to_copy"
        data = b"This file contains arbitrary data.\n"
        file_to_copy.write_bytes(data)
        destination = tmp_path / "destination_collection"
        rc = galleries.cli.main(["init", "--template", str(db_dir), str(destination)])
        assert rc == 0
        new_subdir = destination / galleries.cli.DB_DIR_NAME
        assert new_subdir.is_dir()
        new_file = new_subdir / "file_to_copy"
        assert new_file.is_file()
        assert new_file.read_bytes() == data
        assert not caplog.text

    def test_template_dir_source_not_a_directory(self, tmp_path, caplog):
        source = tmp_path / "source_collection"
        source.mkdir()
        db_dir = source / "my_db_files"
        # Create as regular file, not a directory
        db_dir.touch()
        destination = tmp_path / "destination_collection"
        rc = galleries.cli.main(["init", "--template", str(db_dir), str(destination)])
        assert rc > 0
        assert any(
            "TemplateDir is not a directory" in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )
        assert "my_db_files" in caplog.text

    def test_template_dir_destination_exists(self, tmp_path, caplog):
        source = tmp_path / "source_collection"
        source.mkdir()
        db_dir = source / "my_db_files"
        db_dir.mkdir()
        file_to_copy = db_dir / "file_to_copy"
        data = b"This file contains arbitrary data.\n"
        file_to_copy.write_bytes(data)
        destination = tmp_path / "destination_collection"
        destination.mkdir()
        new_subdir = destination / galleries.cli.DB_DIR_NAME
        new_subdir.mkdir()
        rc = galleries.cli.main(["init", "--template", str(db_dir), str(destination)])
        assert rc > 0
        assert any(
            "Refusing to overwrite existing" in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )
        assert new_subdir.name in caplog.text

    def test_successful(self, tmp_path, caplog):
        directory = tmp_path / "test_collection"
        rc = galleries.cli.main(["--collection", str(directory), "init"])
        assert rc == 0
        subdir = directory / galleries.cli.DB_DIR_NAME
        assert subdir.is_dir()
        config_file = subdir / galleries.cli.DB_CONFIG_NAME
        assert config_file.is_file()
        assert config_file.read_bytes()
        assert not any(
            record for record in caplog.records if record.levelname == "ERROR"
        )

    def test_configuration(self, tmp_path, real_path, caplog):
        global_config_path = real_path / "config"
        fake_dir = tmp_path / "do_not_create"
        global_config_path.write_text(f"[init]\nTemplateDir: {fake_dir}\n")
        destination = tmp_path / "destination_collection"
        rc = galleries.cli.main(["init", str(destination)])
        assert rc > 0
        assert any(
            "TemplateDir is not a directory" in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )
        assert "do_not_create" in caplog.text

    def test_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rc = galleries.cli.main(["init", "--bare"])
        assert rc == 0
        subdir = tmp_path / galleries.cli.DB_DIR_NAME
        assert subdir.is_dir()
        config_file = subdir / galleries.cli.DB_CONFIG_NAME
        assert config_file.is_file()
        assert config_file.read_bytes() == b""


class TestTraverse:
    @staticmethod
    def _assert_csv(csv_path, total):
        assert csv_path.is_file()
        csv_rows = csv_path.read_text(encoding="utf-8").splitlines()
        print(csv_rows)
        assert len(csv_rows) == total
        assert csv_rows[0] == "Path,Count,Tags"

    def test_no_configuration(self, caplog):
        assert galleries.cli.main(["traverse"]) > 0
        assert any(
            "No valid collection found" in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )

    @pytest.mark.parametrize(
        ("directories", "files", "total"), [([], [], 1), (DIR_TREE, FILE_TREE, 5)]
    )
    def test_tree(self, tmp_path, directories, files, total):
        root = tmp_path / "test_collection"
        init_rc = galleries.cli.main(["init", str(root)])
        assert init_rc == 0
        mktree(root, directories, files)
        traverse_rc = galleries.cli.main(["-c", str(root), "traverse"])
        assert traverse_rc == 0
        self._assert_csv(csv_path(root), total)

    @pytest.mark.parametrize(
        ("directories", "files", "total"), [([], [], 1), (DIR_TREE, FILE_TREE, 4)]
    )
    def test_tree_leaves_only(self, tmp_path, directories, files, total):
        root = tmp_path / "test_collection"
        init_rc = galleries.cli.main(["init", str(root)])
        assert init_rc == 0
        mktree(root, directories, files)
        traverse_rc = galleries.cli.main(["-c", str(root), "traverse", "--leaves"])
        assert traverse_rc == 0
        self._assert_csv(csv_path(root), total)

    def test_file_output(self, tmp_path):
        root = tmp_path / "test_collection"
        init_rc = galleries.cli.main(["init", str(root)])
        assert init_rc == 0
        mktree(root, [], [])
        csv_path = root / "test.csv"
        traverse_rc = galleries.cli.main(
            ["-c", str(root), "traverse", "-o", str(csv_path)]
        )
        assert traverse_rc == 0
        self._assert_csv(csv_path, total=2)

    def test_standard_output(self, tmp_path, capsys):
        root = tmp_path / "test_collection"
        init_rc = galleries.cli.main(["init", str(root)])
        assert init_rc == 0
        mktree(root, [], [])
        traverse_rc = galleries.cli.main(["-c", str(root), "traverse", "-o-"])
        assert traverse_rc == 0
        out = capsys.readouterr().out
        assert len(out.splitlines()) == 1

    @pytest.mark.parametrize(
        ("key", "value"),
        [("PathField", "パス"), ("CountField", "数"), ("TagFields", " カラム#1;  カラム#2")],
    )
    def test_configuration(self, tmp_path, key, value):
        root = tmp_path / "test_collection"
        init_rc = galleries.cli.main(["init", "--bare", str(root)])
        assert init_rc == 0
        config_path = root / galleries.cli.DB_DIR_NAME / galleries.cli.DB_CONFIG_NAME
        config_path.write_text(f"[db]\nCSVName=custom.csv\n{key}={value}\n")
        mktree(root, [], [])
        traverse_rc = galleries.cli.main(["-c", str(root), "traverse"])
        assert traverse_rc == 0
        csv_path = root / galleries.cli.DB_DIR_NAME / "custom.csv"
        assert csv_path.is_file()
        headers = csv_path.read_text().strip().split(",")
        fieldnames = galleries.cli.split_semicolon_list(value)
        for field in fieldnames:
            assert field in headers


def csv_path(root):
    """Return the default, unconfigured CSV path."""
    return (
        root
        / galleries.cli.DB_DIR_NAME
        / galleries.cli.DEFAULT_CONFIG_STATE["db"]["CSVName"]
    )


@pytest.fixture
def write_to_csv(tmp_path, real_path):
    """
    Initialize default collection and return a function that writes to its DB.
    """
    root = tmp_path / "test_collection"
    global_config = real_path / "config"
    global_config.write_text("[global]\ndefault = default\n")
    global_collections = real_path / "collections"
    global_collections.write_text(f"[default]\nroot = {root}")
    galleries.cli.main([f"--collection={root}", "init"])
    mktree(root, DIR_TREE, FILE_TREE)
    galleries.cli.main([f"--collection={root}", "traverse"])

    def write(data):
        return csv_path(root).write_bytes(data)

    return write


class TestCount:
    @pytest.mark.usefixtures("write_to_csv")
    def test_no_tags(self, capsys):
        rc = galleries.cli.main(["count"])
        assert rc == 0
        assert not capsys.readouterr().out

    CSV_TAGS_ONLY = b"Tags\n\nA B C\nC B A\nD\nA E\n\n"

    def test_tags_only(self, write_to_csv, capsys):
        write_to_csv(self.CSV_TAGS_ONLY)
        rc = galleries.cli.main(["count"])
        assert rc == 0
        captured = capsys.readouterr()
        print(captured.out)
        lines = captured.out.splitlines()
        assert len(lines) == 5
        assert lines[0].split() == ["3", "a"]

    def test_summarize(self, write_to_csv, capsys):
        write_to_csv(self.CSV_TAGS_ONLY)
        rc = galleries.cli.main(["count", "--summarize"])
        assert rc == 0
        captured = capsys.readouterr()
        print(captured.out)
        lines = captured.out.splitlines()
        assert len(lines) == 21
        for expected_key, expected_value in [
            ("galleries", 4),
            ("tags", 9),
            ("t_mean", 1.8),
            ("g_mean", 2.25),
        ]:
            for line in lines:
                if match_obj := re.match(rf"{expected_key}\s+(.+)", line.strip()):
                    assert float(match_obj.group(1)) == expected_value

    def test_invalid_unicode(self, write_to_csv, caplog):
        write_to_csv("日本語ができない！".encode("shift-jis"))
        rc = galleries.cli.main(["count"])
        assert rc > 0
        assert caplog.text

    @pytest.mark.parametrize("bad_field_in_csv", ["Tagz", "tags"])
    def test_field_not_found(self, write_to_csv, caplog, bad_field_in_csv):
        """Case where CSV data does not match configuration"""
        write_to_csv(f"Path,Count,{bad_field_in_csv}\n001,0,untagged\n".encode())
        expected_field = "Tags"
        rc = galleries.cli.main(["count"])
        assert rc > 0
        assert any(
            expected_field in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )

    @pytest.mark.usefixtures("write_to_csv")
    @pytest.mark.parametrize("bad_field_in_arg", ["Not a valid fieldname", "無效"])
    def test_argument_not_found(self, caplog, bad_field_in_arg):
        """Case where command-line argument does not match CSV data"""
        rc = galleries.cli.main(["count", bad_field_in_arg])
        assert rc > 0
        assert any(
            bad_field_in_arg in record.message
            for record in caplog.records
            if record.levelname == "ERROR"
        )

    @pytest.mark.parametrize(
        "data_in", ["Path,Count,Tags\n001,0,untagged\\,\n", "Path,Count,Tags\n001,0\n"]
    )
    def test_field_mismatch(self, write_to_csv, data_in, caplog):
        write_to_csv(data_in.encode())
        rc = galleries.cli.main(["count"])
        assert rc > 0
        assert caplog.text


class TestQuery:
    @pytest.mark.usefixtures("write_to_csv")
    def test_no_tags(self, capsys):
        rc = galleries.cli.main(["query"])
        assert rc == 0
        captured = capsys.readouterr()
        assert not captured.err
        assert len(captured.out.splitlines()) == 5

    @pytest.mark.parametrize("arg", ["ish", "免許"])
    def test_invalid_format_arg(self, capsys, arg):
        with pytest.raises(SystemExit):
            galleries.cli.main(["query", f"-F{arg}"])
        assert arg in capsys.readouterr().err


class TestRelated:
    @pytest.mark.usefixtures("write_to_csv")
    def test_no_tags(self, capsys):
        tags = ["anytag", "任意"]
        rc = galleries.cli.main(["-vv", "related", *tags])
        assert rc == 0
        captured = capsys.readouterr()
        for tag in tags:
            assert tag in captured.out
