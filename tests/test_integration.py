"""Integration tests for the CLI, using pytest"""

import collections
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
    [
        ([], pathlib.Path.cwd),
        (["-c", "/any/string"], lambda: pathlib.Path("/any/string")),
    ],
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
        assert msg_in_error_logs(caplog, "Failed to create root directory")

    def test_config_exists(self, tmp_path, caplog):
        directory = tmp_path / "test_collection"
        directory.mkdir()
        subdir = directory / galleries.cli.DB_DIR_NAME
        subdir.mkdir()
        config_file = subdir / galleries.cli.DB_CONFIG_NAME
        config_file.touch()
        rc = galleries.cli.main(["init", "--bare", str(directory)])
        assert rc > 0
        assert msg_in_error_logs(
            caplog, "Refusing to overwrite existing configuration file"
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
        assert msg_in_error_logs(caplog, "TemplateDir is not a directory")
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
        assert msg_in_error_logs(caplog, "Refusing to overwrite existing")
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
        write_utf8(global_config_path, f"[init]\nTemplateDir: {fake_dir}\n")
        destination = tmp_path / "destination_collection"
        rc = galleries.cli.main(["init", str(destination)])
        assert rc > 0
        assert msg_in_error_logs(caplog, "TemplateDir is not a directory")
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
    def _assert_csv(csvpath, total):
        assert csvpath.is_file()
        csv_rows = csvpath.read_text(encoding="utf-8").splitlines()
        print(csv_rows)
        assert len(csv_rows) == total
        assert csv_rows[0] == "Path,Count,Tags"

    def test_no_configuration(self, caplog):
        assert galleries.cli.main(["traverse"]) > 0
        assert msg_in_error_logs(caplog, "No valid collection found")

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
        csvpath = root / "test.csv"
        traverse_rc = galleries.cli.main(
            ["-c", str(root), "traverse", "-o", str(csvpath)]
        )
        assert traverse_rc == 0
        self._assert_csv(csvpath, total=2)

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
        write_utf8(config_path, f"[db]\nCSVName=custom.csv\n{key}={value}\n")
        mktree(root, [], [])
        traverse_rc = galleries.cli.main(["-c", str(root), "-v", "traverse"])
        assert traverse_rc == 0
        csvpath = root / galleries.cli.DB_DIR_NAME / "custom.csv"
        assert csvpath.is_file()
        headers = csvpath.read_text(encoding="utf-8").strip().split(",")
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


def db_conf_path(root):
    return root / galleries.cli.DB_DIR_NAME / galleries.cli.DB_CONFIG_NAME


@pytest.fixture
def initialize_collection(tmp_path, real_path):
    """Initialize default collection."""
    root = tmp_path / "test_collection"
    global_config = real_path / "config"
    write_utf8(global_config, "[global]\ndefault = default\n")
    global_collections = real_path / "collections"
    write_utf8(global_collections, f"[default]\nroot = {root}")
    galleries.cli.main([f"--collection={root}", "init"])
    galleries.cli.main([f"--collection={root}", "traverse"])
    return root


@pytest.fixture
def write_to_csv(initialize_collection):
    root = initialize_collection

    def write(data):
        return csv_path(root).write_bytes(data)

    return write


def _edit_db_conf(path, field, value):
    config_text = path.read_text(encoding="utf-8")
    config_text = re.sub(
        rf"^\s*{re.escape(field)}\s*[=:].*$",
        f"{field} = {value}\n",
        config_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    write_utf8(path, config_text)


class TestCount:
    @pytest.mark.usefixtures("write_to_csv")
    def test_no_tags(self, capsys):
        rc = galleries.cli.main(["count"])
        assert rc == 0
        assert not capsys.readouterr().out

    CSV_TAGS_ONLY = b"Tags\n\nA B C\nC B A\nD\nA E\n\n"

    @pytest.fixture
    def input_args_tags_only(self, tmp_path):
        path = tmp_path / "tags-only.csv"
        path.write_bytes(self.CSV_TAGS_ONLY)
        return ["--input", str(path)]

    def test_tags_only(self, write_to_csv, capsys):
        write_to_csv(self.CSV_TAGS_ONLY)
        rc = galleries.cli.main(["count"])
        self._assert_count_output(rc, capsys)

    def test_input_option(self, input_args_tags_only, capsys):
        rc = galleries.cli.main(["count", *input_args_tags_only])
        self._assert_count_output(rc, capsys)

    def _assert_count_output(self, rc, capsys):
        assert rc == 0
        captured = capsys.readouterr()
        print(captured.out)
        lines = captured.out.splitlines()
        assert len(lines) == 5
        assert lines[0].split() == ["3", "a"]

    def test_summarize(self, input_args_tags_only, capsys):
        rc = galleries.cli.main(["count", "--summarize", *input_args_tags_only])
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
        assert msg_in_error_logs(caplog, expected_field)

    @pytest.mark.parametrize("bad_field_in_arg", ["Not a valid fieldname", "無效"])
    def test_argument_not_found(self, input_args_tags_only, caplog, bad_field_in_arg):
        """Case where command-line argument does not match CSV data"""
        rc = galleries.cli.main(["count", *input_args_tags_only, bad_field_in_arg])
        assert rc > 0
        assert msg_in_error_logs(caplog, bad_field_in_arg)

    @pytest.mark.parametrize(
        "data_in", ["Path,Count,Tags\n001,0,untagged\\,\n", "Path,Count,Tags\n001,0\n"]
    )
    def test_field_mismatch(self, write_to_csv, data_in, caplog):
        write_to_csv(data_in.encode())
        rc = galleries.cli.main(["count"])
        assert rc > 0
        assert caplog.text

    def test_empty_input(self, write_to_csv, capsys):
        write_to_csv(b"")
        rc = galleries.cli.main(["count"])
        assert rc == 0
        assert not capsys.readouterr().out

    CSV_MULTIPLE_FIELDS = "A,B,C\na b c,m n,x y z\na b c,i j k,w z\n"
    COUNT_EXPECTED_BY_FIELD = {
        "A": {"a": 2, "b": 2, "c": 2},
        "B": {"m": 1, "n": 1, "i": 1, "j": 1, "k": 1},
        "C": {"x": 1, "y": 1, "z": 2, "w": 1},
    }

    def _assert_count_results(self, output, result_dicts):
        lines = [line.strip() for line in output.splitlines()]
        count_expected = collections.Counter()
        for d in result_dicts:
            count_expected.update(d)
        assert len(lines) == len(count_expected)
        for expected_key, expected_value in count_expected.items():
            assert any(
                re.match(rf"{expected_value}\s+{expected_key}", line) for line in lines
            )

    def test_custom_csv_filename(self, initialize_collection, capsys):
        custom_filename = "MYGALL~1.CSV"
        cla_fields = ("A", "B")
        csvpath = initialize_collection / galleries.cli.DB_DIR_NAME / custom_filename
        write_utf8(csvpath, self.CSV_MULTIPLE_FIELDS)
        _edit_db_conf(db_conf_path(initialize_collection), "CSVName", custom_filename)
        rc = galleries.cli.main(["count", *cla_fields])
        assert rc == 0
        captured = capsys.readouterr()
        print(captured.out)
        self._assert_count_results(
            captured.out, (self.COUNT_EXPECTED_BY_FIELD[field] for field in cla_fields)
        )

    @pytest.mark.parametrize(
        ("conf_fields", "cla_fields", "fields_expected"),
        [
            ("A", [], ["A"]),
            ("B", [], ["B"]),
            ("A;B;C", [], ["A", "B", "C"]),
            ("A;B;C", ["C"], ["C"]),
        ],
    )
    def test_custom_tag_fields(
        self, initialize_collection, capsys, conf_fields, cla_fields, fields_expected
    ):
        write_utf8(csv_path(initialize_collection), self.CSV_MULTIPLE_FIELDS)
        _edit_db_conf(db_conf_path(initialize_collection), "TagFields", conf_fields)
        rc = galleries.cli.main(["count", *cla_fields])
        assert rc == 0
        captured = capsys.readouterr()
        print(captured.out)
        self._assert_count_results(
            captured.out,
            (self.COUNT_EXPECTED_BY_FIELD[field] for field in fields_expected),
        )


class TestQuery:
    @pytest.fixture
    def input_args_empty(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_bytes(b"")
        return ["--input", str(path)]

    @pytest.mark.parametrize("format_args", [[], ["-Fnone"], ["-Fauto"]])
    def test_empty_input(self, input_args_empty, capsys, format_args):
        # All these format args should produce the same unformatted output,
        # given stdout is not a tty.
        rc = galleries.cli.main(["query", *input_args_empty, *format_args])
        assert rc == 0
        captured = capsys.readouterr()
        assert not captured.err
        assert captured.out == "\r\n"

    def test_sort_field_not_found(self, input_args_empty, caplog):
        bad_field_in_arg = "???"
        rc = galleries.cli.main(
            ["query", *input_args_empty, "--sort", bad_field_in_arg]
        )
        assert rc > 0
        assert msg_in_error_logs(caplog, bad_field_in_arg)

    @pytest.mark.usefixtures("write_to_csv")
    def test_no_tags(self, capsys):
        rc = galleries.cli.main(["query"])
        assert rc == 0
        captured = capsys.readouterr()
        assert not captured.err
        assert len(captured.out.splitlines()) == 1

    @pytest.mark.parametrize("arg", ["ish", "免許"])
    def test_invalid_format_arg(self, capsys, arg):
        with pytest.raises(SystemExit):
            galleries.cli.main(["query", f"-F{arg}"])
        assert arg in capsys.readouterr().err

    def test_input_option(self, tmp_path, capsys):
        path = tmp_path / "test.csv"
        text = "Tags\r\nA\r\nB\r\nC\r\n"
        write_utf8(path, text)
        rc = galleries.cli.main(["query", "--input", str(path)])
        assert rc == 0
        assert capsys.readouterr().out == text

    def test_field_argument_not_found(self, tmp_path, caplog):
        bad_field_arg = "tagz"
        path = tmp_path / "test.csv"
        write_utf8(path, "Tags\r\nA\r\nB\r\nC\r\n")
        rc = galleries.cli.main(
            ["query", "--input", str(path), "--field", bad_field_arg, "A"]
        )
        assert rc > 0
        assert msg_in_error_logs(caplog, bad_field_arg)

    def test_custom_csv_filename(self, initialize_collection, capsys):
        custom_filename = "MYGALL~1.CSV"
        text = "Tags\r\na b c\r\nx y z\r\n"
        csvpath = initialize_collection / galleries.cli.DB_DIR_NAME / custom_filename
        write_utf8(csvpath, text)
        _edit_db_conf(db_conf_path(initialize_collection), "CSVName", custom_filename)
        rc = galleries.cli.main(["query"])
        assert rc == 0
        assert capsys.readouterr().out == text

    @pytest.mark.parametrize(
        ("conf_fields", "cla_fields", "terms", "rows_expected"),
        [
            ("B", [], ["a"], []),
            ("B;A", [], ["a"], ["a,b"]),
            ("B", ["A"], ["a"], ["a,b"]),
            ("A", [], ["+a", "+m"], ["a,b", "m,n"]),
        ],
    )
    def test_custom_tag_fields(
        self,
        initialize_collection,
        capsys,
        conf_fields,
        cla_fields,
        terms,
        rows_expected,
    ):
        csv_text = "A,B\na,b\nm,n\n"
        write_utf8(csv_path(initialize_collection), csv_text)
        _edit_db_conf(db_conf_path(initialize_collection), "TagFields", conf_fields)
        cla_fields = (f"--field={fieldname}" for fieldname in cla_fields)
        rc = galleries.cli.main(["query", *cla_fields, *terms])
        assert rc == 0
        captured = capsys.readouterr()
        print(captured.out)
        # Subtract the header
        results = captured.out.splitlines()[1:]
        assert rows_expected == results

    def test_invalid_format_from_config(self, initialize_collection, caplog):
        arg = "免許"
        _edit_db_conf(db_conf_path(initialize_collection), "Format", arg)
        rc = galleries.cli.main(["query"])
        assert rc > 0
        assert msg_in_error_logs(caplog, arg)

    @pytest.mark.usefixtures("write_to_csv")
    @pytest.mark.parametrize("args", [[" "], ["Π", "#f"]])
    def test_invalid_search_terms(self, caplog, args):
        rc = galleries.cli.main(["query", *args])
        assert rc > 0
        assert repr(args[0]) in caplog.text

    def test_unconfigured_rich_output(self, input_args_empty, capsys):
        rc = galleries.cli.main(["query", *input_args_empty, "--format", "rich"])
        assert rc == 0
        captured = capsys.readouterr()
        assert not captured.err
        assert captured.out.isspace()

    @pytest.mark.parametrize(
        ("file_content", "loglevel"),
        [
            (None, "DEBUG"),  # FileNotFoundError
            (b'"field":"Path",', "ERROR"),  # JSONDecodeError
        ],
    )
    def test_rich_table_file_errors(
        self, tmp_path, input_args_empty, caplog, file_content, loglevel
    ):
        rich_table_file = tmp_path / "rich_table_settings_test"
        if file_content:
            rich_table_file.write_bytes(file_content)
        rc = galleries.cli.main(
            ["-vv", "query", *input_args_empty, "--rich-table", str(rich_table_file)]
        )
        # In any case, the default Rich table is used, so no error exit
        assert rc == 0
        assert any(
            rich_table_file.name in record.message
            for record in caplog.records
            if record.levelname == loglevel
        )

    _FF_JP = "パス\t40\n数\t5\n"

    @pytest.mark.parametrize(
        "file_content",
        [
            None,  # FileNotFoundError
            _FF_JP.encode("shift-jis"),  # UnicodeDecodeError
            _FF_JP.encode("utf-8"),  # FieldNotFoundError
        ],
    )
    def test_field_format_file_errors(
        self, tmp_path, input_args_empty, caplog, file_content
    ):
        field_formats_file = tmp_path / "field_formats_test"
        if file_content:
            field_formats_file.write_bytes(file_content)
        rc = galleries.cli.main(
            [
                "--quiet",
                "query",
                *input_args_empty,
                "--field-formats",
                str(field_formats_file),
            ]
        )
        assert rc > 0
        assert msg_in_error_logs(caplog, "FieldFormats file")

    def test_field_format_file_empty(self, tmp_path, capsys):
        field_formats_file = tmp_path / "field_formats_test"
        field_formats_file.write_bytes(b"")
        csv_file = tmp_path / "test_input.csv"
        csv_file.write_bytes(b"Tags\none\ntwo three\nfour\n")
        rc = galleries.cli.main(
            [
                "query",
                "--input",
                str(csv_file),
                "--field-formats",
                str(field_formats_file),
            ]
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert not captured.out
        assert not captured.err


@pytest.mark.parametrize(
    ("query_args", "expected_results"),
    [
        ([], {"a": "3", "b": "2", "c": "2", "d": "1", "e": "1"}),
        (["b"], {"a": "2", "b": "2", "c": "2"}),
    ],
)
def test_pipe_query_to_count(initialize_collection, query_args, expected_results):
    """Pipe the results of "query" to "count"."""
    csv_path(initialize_collection).write_bytes(TestCount.CSV_TAGS_ONLY)
    collection_args = ("-c", str(initialize_collection))
    with subprocess.Popen(
        ["galleries", *collection_args, "query", *query_args], stdout=subprocess.PIPE
    ) as query_proc:
        count_proc = run_normal(
            ["galleries", *collection_args, "count", "-i-"], stdin=query_proc.stdout
        )
        assert query_proc.stdout is not None
    print(count_proc.stdout)
    output_pairs = [line.split() for line in count_proc.stdout.splitlines()]
    assert len(output_pairs) == len(expected_results), (output_pairs, expected_results)
    # Makes no assertions about the order of count results, just checks that
    # values are correct
    for lineno, (count, tag, *extra) in enumerate(output_pairs, start=1):
        assert not extra, f"Unexpected character(s) on line {lineno} of count output"
        assert expected_results[tag] == count, tag


class TestRelated:
    _EXPECTED_HEADER = ["TAG", "TOTAL", "COUNT", "COSINE", "JACCARD", "OVERLAP", "FREQ"]

    @pytest.mark.usefixtures("write_to_csv")
    @pytest.mark.parametrize(
        ("tag", "error_expected"), [("anytag", False), ("任意", True)]
    )
    def test_no_tags(self, capsys, tag, error_expected):
        rc = galleries.cli.main(["-vv", "related", tag])
        captured = capsys.readouterr()
        if error_expected:
            assert rc > 0
            assert not captured.out
        else:
            assert rc == 0
            assert captured.out.split() == self._EXPECTED_HEADER

    @pytest.mark.parametrize(
        ("field", "value"), [("Limit", "none"), ("SortMetric", "無効")]
    )
    def test_invalid_config_settings(self, initialize_collection, caplog, field, value):
        _edit_db_conf(db_conf_path(initialize_collection), field, value)
        rc = galleries.cli.main(["related", ""])
        assert rc > 0
        assert msg_in_error_logs(caplog, value)

    _EXPECTED_RESULTS_0 = [
        _EXPECTED_HEADER,
        ["b", "3", "3", "1.00000", "1.00000", "1.00000", "100%"],
        ["a", "5", "3", "0.77460", "0.60000", "1.00000", "60%"],
        ["c", "3", "1", "0.33333", "0.20000", "0.33333", "33%"],
    ]
    _EXPECTED_RESULTS_1 = [
        _EXPECTED_HEADER,
        ["a", "5", "5", "0.91287", "0.83333", "1.00000", "100%"],
        ["b", "3", "3", "0.70711", "0.50000", "1.00000", "100%"],
        ["c", "3", "3", "0.70711", "0.50000", "1.00000", "100%"],
        ["d", "2", "2", "0.57735", "0.33333", "1.00000", "100%"],
    ]

    @pytest.mark.parametrize(
        ("args", "expected_results"),
        [(["a", "b"], _EXPECTED_RESULTS_0), ([], _EXPECTED_RESULTS_1)],
    )
    def test_results(self, write_to_csv, capsys, args, expected_results):
        write_to_csv(b"Tags\na b\na b\na c\nc d\na d\na b c\n")
        rc = galleries.cli.main(["related", *args])
        assert rc == 0
        stdout = capsys.readouterr().out
        print(stdout)
        results = [line.split() for line in stdout.splitlines()]
        assert results == expected_results

    _CSV_CONTENT_1 = (
        "Tags\na b e\nb d e\na d e\na c d\na c e\n"
        "a b c d\nc d e\na b d\nc\nc d\na\na b d\n"
    )
    _EXPECTED_RESULTS_FOR_OPTIONS = [
        _EXPECTED_HEADER,
        ["b", "5", "1", "0.44721", "0.20000", "1.00000", "20%"],
        ["d", "8", "1", "0.35355", "0.12500", "1.00000", "12%"],
        ["e", "5", "1", "0.44721", "0.20000", "1.00000", "20%"],
    ]

    def test_options(self, tmp_path, capsys):
        csv_file = tmp_path / "test_input.csv"
        write_utf8(csv_file, self._CSV_CONTENT_1)
        rc = galleries.cli.main(
            ["related", f"--input={csv_file}", "--sort=overlap", "-l4", "~a", "b"]
        )
        assert rc == 0
        stdout = capsys.readouterr().out
        print(stdout)
        results = [line.split() for line in stdout.splitlines()]
        for line in self._EXPECTED_RESULTS_FOR_OPTIONS:
            assert line in results


class TestRefresh:
    def test_simple(self, initialize_collection):
        csv_path(initialize_collection).write_bytes(b"Path,Tags\n,xYz AbC\n")
        rc = galleries.cli.main(["-vv", "refresh", "--no-check"])
        assert rc == 0
        result = csv_path(initialize_collection).read_bytes()
        assert result == b"Path,Tags\r\n,abc xyz\r\n"


def write_utf8(path, text):
    return path.write_text(text, encoding="utf-8")


def msg_in_error_logs(caplog, substring):
    return any(
        substring in record.message
        for record in caplog.records
        if record.levelname == "ERROR"
    )
