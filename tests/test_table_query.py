"""Unit tests for table_query, using pytest"""

import re
import sys

import pytest
import rich.box
import rich.table

import galleries.galleryms
import galleries.table_query
import galleries.util


@pytest.fixture
def tmp_write_text(tmp_path):
    def write_text(path, content):
        textfile = tmp_path / path
        textfile.write_text(content, encoding="utf-8")
        return textfile

    return write_text


@pytest.fixture
def set_columns(monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")


class TestParseFieldFormatFile:
    func = staticmethod(galleries.table_query.parse_field_format_file)

    def test_nonexistent_file(self, tmp_path):
        path = tmp_path / "null"
        with pytest.raises(FileNotFoundError):
            self.func(path)

    def test_empty_file(self, tmp_write_text):
        path = tmp_write_text("empty.txt", "")
        assert self.func(path) == {}

    def test_no_argument(self, tmp_write_text, caplog):
        text = "FieldName \n"
        path = tmp_write_text("no-argument.txt", text)
        assert self.func(path) == {}
        assert any_error_logs(caplog)
        assert ":1:" in caplog.text, "Line number of error"
        assert "FieldName" in caplog.text, "Field name"

    def test_rem_argument(self, tmp_write_text):
        text = "FieldName REM\n"
        path = tmp_write_text("rem-argument.txt", text)
        assert self.func(path) == {
            "FieldName": galleries.galleryms.FieldFormat(
                width=galleries.galleryms.FieldFormat.REMAINING_SPACE
            )
        }

    def test_valid_argument(self, tmp_write_text):
        text = "FieldName 40\n"
        path = tmp_write_text("valid-argument.txt", text)
        assert self.func(path) == {
            "FieldName": galleries.galleryms.FieldFormat(width=40)
        }

    def test_invalid_argument(self, tmp_write_text, caplog):
        text = "FieldName NotANumber\n"
        path = tmp_write_text("invalid-argument.txt", text)
        assert self.func(path) == {}
        assert any_error_logs(caplog)
        assert ":1:" in caplog.text, "Line number of error"
        assert "NotANumber" in caplog.text, "An invalid numeric argument"

    def test_whitespace(self, tmp_write_text):
        text = """
            FieldName      22
        """
        path = tmp_write_text("added-whitespace.txt", text)
        assert self.func(path) == {
            "FieldName": galleries.galleryms.FieldFormat(width=22)
        }

    def test_mixed_validity(self, tmp_write_text, caplog):
        text = """
            FieldA  REM
            FieldB  NotANumber
            FieldC  16
        """
        path = tmp_write_text("mixed-validity.txt", text)
        assert self.func(path) == {
            "FieldA": galleries.galleryms.FieldFormat(
                width=galleries.galleryms.FieldFormat.REMAINING_SPACE
            ),
            "FieldC": galleries.galleryms.FieldFormat(width=16),
        }
        assert any_error_logs(caplog)
        assert ":3:" in caplog.text, "Line number of error"
        assert "NotANumber" in caplog.text, "An invalid numeric argument"

    def test_comments(self, tmp_write_text, caplog):
        text = """
            # A comment on its own line
            FieldName 22  # A trailing comment with number 15
        """
        path = tmp_write_text("comments.txt", text)
        assert self.func(path) == {
            "FieldName": galleries.galleryms.FieldFormat(width=22)
        }
        assert not any_error_logs(caplog)

    def test_quoting_and_escaping(self, tmp_write_text):
        text = "'Field name' 17\nName\\ with\\ spaces 18\n"
        path = tmp_write_text("quoting-and-escaping.txt", text)
        assert self.func(path) == {
            "Field name": galleries.galleryms.FieldFormat(width=17),
            "Name with spaces": galleries.galleryms.FieldFormat(width=18),
        }

    def test_silent_overwrites(self, tmp_write_text, caplog):
        text = """
            FieldName 10
            FieldName 20
        """
        path = tmp_write_text("silent-overwrites.txt", text)
        assert self.func(path) == {
            "FieldName": galleries.galleryms.FieldFormat(width=20)
        }
        assert not caplog.text

    def test_optionals(self, tmp_write_text):
        text = """
            FieldA 10  "" "black"
            FieldB 20
            FieldC REM "bright white" "" Bold
        """
        path = tmp_write_text("optionals.txt", text)
        assert self.func(path) == {
            "FieldA": galleries.galleryms.FieldFormat(width=10, bg="black"),
            "FieldB": galleries.galleryms.FieldFormat(width=20),
            "FieldC": galleries.galleryms.FieldFormat(
                width=galleries.galleryms.FieldFormat.REMAINING_SPACE,
                fg="bright white",
                effect="bold",
            ),
        }

    def test_invalid_color(self, tmp_write_text, caplog):
        text = "FieldName 80 pink\n"
        path = tmp_write_text("invalid-color.txt", text)
        assert self.func(path) == {}
        assert any_error_logs(caplog)
        assert ":1:" in caplog.text, "Line number of error"
        assert "pink" in caplog.text, "An invalid color argument"


class TestQueryFromArgs:
    func = staticmethod(galleries.table_query.query_from_args)

    @pytest.mark.parametrize(
        "args", [[""], ["", "A"], [" "], ["#"], [":A"], ["F:"], ["+"], ["F=3.14"]]
    )
    def test_invalid_args(self, args, caplog):
        with pytest.raises(galleries.table_query.SearchTermError) as raises_ctx:
            self.func(args, fieldnames=[])
        assert isinstance(
            raises_ctx.value.__cause__, galleries.galleryms.ArgumentParsingError
        )
        assert any_error_logs(caplog)

    def test_empty_args(self):
        assert not self.func([], fieldnames=[])

    def test_no_default_tag_fields(self, caplog):
        query = self.func(["Field:A"], fieldnames=["Field"])
        assert len(query.conjuncts) == 1
        assert not any_error_logs(caplog)
        with pytest.raises(galleries.table_query.SearchTermError, match="'A'"):
            self.func(["A"], fieldnames=["Field"])
        assert any_error_logs(caplog)

    @pytest.mark.parametrize(
        ("args", "fieldnames", "default_tag_fields"),
        [
            (["A"], [], ["Fields"]),  # No candidate
            (["PyP:A"], ["PyPy", "PyPI"], None),  # Too many candidates
            (["Field:A"], [], None),  # No candidates
        ],
    )
    def test_ambiguous_args(self, caplog, args, fieldnames, default_tag_fields):
        with pytest.raises(galleries.table_query.SearchTermError, match="'A'"):
            self.func(
                args=args, fieldnames=fieldnames, default_tag_fields=default_tag_fields
            )
        assert any_error_logs(caplog)

    def test_valid_args(self):
        query = self.func(["+G:X"], fieldnames=["F", "G"])
        assert len(query.disjuncts) == 1
        term = query.disjuncts[0]
        assert term.fields == ["G"]
        assert isinstance(term, galleries.galleryms.WholeSearchTerm)
        assert term.word == "X"


class TestMain:
    _data = [
        {"FieldA": object(), "FieldB": object()},
        {"FieldA": {"a"}, "FieldB": {"b"}},
    ]
    _fieldnames = ["FieldA", "FieldB"]
    _bogus_field = "CdleiF"

    def test_successful(self, capsys):
        gallery_gen = (galleries.galleryms.Gallery(mapping) for mapping in self._data)
        galleries.table_query.print_table(
            galleries=gallery_gen, fieldnames=self._fieldnames, output_formatter=None
        )
        out, err = capsys.readouterr()
        assert not err
        results = out.splitlines()
        assert results[0] == "FieldA,FieldB"
        object_regex = r"<object object at 0x[0-9a-f]+>"
        assert re.match(rf"{object_regex},{object_regex}\Z", results[1])
        assert results[2] == "{'a'},{'b'}"

    def test_no_sorting(self):
        glist = [galleries.galleryms.Gallery(mapping) for mapping in self._data]
        result = galleries.table_query.sort_table(
            glist, self._fieldnames, sort_field=None
        )
        assert glist == result

    def test_sort_field_not_found(self, caplog):
        with pytest.raises(galleries.table_query.SortingError, match=self._bogus_field):
            galleries.table_query.sort_table(
                galleries=[], fieldnames=self._fieldnames, sort_field=self._bogus_field
            )
        assert any_error_logs(caplog)
        assert self._bogus_field in caplog.text

    def test_format_field_not_found(self, caplog):
        bogus_table = galleries.table_query.FormattedTablePrinter(
            {self._bogus_field: galleries.galleryms.FieldFormat(80)}
        )
        with pytest.raises(
            galleries.table_query.FormatterError, match=self._bogus_field
        ):
            bogus_table.check_fields(self._fieldnames)
        assert any_error_logs(caplog)
        assert self._bogus_field in caplog.text


@pytest.mark.usefixtures("set_columns")
class TestPrintFormatted:
    @pytest.mark.parametrize(
        ("field_formats", "expected_out"),
        [({}, []), ({"FieldA": galleries.galleryms.FieldFormat(79)}, [" a", " a"])],
    )
    def test_successful(self, capsys, field_formats, expected_out):
        # For some reason, it is important that file=sys.stdout be specified
        # in the body of the test function in order for capsys to work.
        galleries.table_query.print_formatted(
            rows=_gallery_gen(), field_formats=field_formats, file=sys.stdout
        )
        captured = capsys.readouterr()
        assert captured.out.splitlines() == expected_out

    def test_format_field_not_found(self, capsys):
        bogus_field = "CdleiF"
        field_formats = {bogus_field: galleries.galleryms.FieldFormat(79)}
        with pytest.raises(KeyError, match=repr(bogus_field)):
            galleries.table_query.print_formatted(
                rows=_gallery_gen(), field_formats=field_formats, file=sys.stdout
            )
        assert not capsys.readouterr().out


class TestParseRichTableSettings:
    def test_nonexistent_file(self, tmp_path):
        path = tmp_path / "null"
        table = galleries.table_query.parse_rich_table_file(path)
        assert not table.fieldnames
        assert table.table.box == galleries.table_query.DEFAULT_BOX

    def test_empty_file(self, tmp_write_text, caplog):
        path = tmp_write_text("empty.txt", "")
        table = galleries.table_query.parse_rich_table_file(path)
        assert not table.fieldnames
        assert table.table.box == galleries.table_query.DEFAULT_BOX
        assert any(record.levelname == "WARNING" for record in caplog.records)
        assert path.name in caplog.text

    @pytest.mark.parametrize(
        ("filename", "text"),
        [("invalid.json", '{"k", "v"}'), ("invalid.toml", "k=v\n")],
    )
    def test_invalid_file_format(self, tmp_write_text, caplog, filename, text):
        path = tmp_write_text(filename, text)
        table = galleries.table_query.parse_rich_table_file(path)
        assert not table.fieldnames
        assert table.table.box == galleries.table_query.DEFAULT_BOX
        assert any_error_logs(caplog)
        assert path.name in caplog.text

    @pytest.mark.parametrize(
        ("boxarg", "box_expected"),
        [
            ("HEAVY", rich.box.HEAVY),
            ("SQUARE", rich.box.SQUARE),
            ("Box", galleries.table_query.DEFAULT_BOX),
            ("spam", galleries.table_query.DEFAULT_BOX),
            (True, galleries.table_query.DEFAULT_BOX),
            (False, None),
            (None, None),
        ],
    )
    def test_table_settings_box(self, caplog, boxarg, box_expected):
        obj = {"table": {"box": boxarg, "unexpected": True}}
        table = galleries.table_query.parse_rich_table_object(obj)
        assert table.table.box == box_expected
        assert not any_error_logs(caplog)

    @pytest.mark.parametrize(
        ("value", "warnings_expected"),
        [
            # Valid bools
            (True, False),
            (False, False),
            # Invalid values
            ("true", True),
            (0, True),
        ],
    )
    def test_table_settings_show_header(self, caplog, value, warnings_expected):
        obj = {"table": {"show_header": value}}
        table = galleries.table_query.parse_rich_table_object(obj)
        if warnings_expected:
            assert self.assert_msg_in_warning(str(value), caplog)
        else:
            result = value
            assert table.table.show_header == result

    def test_no_columns(self, caplog):
        obj = {"columns": {}}
        table = galleries.table_query.parse_rich_table_object(obj)
        assert "columns" in caplog.text
        assert not table.fieldnames
        assert not table.table.columns

    def test_bare_field(self):
        obj = {"columns": [{"field": "A"}]}
        table = galleries.table_query.parse_rich_table_object(obj)
        assert table.fieldnames == ["A"]
        assert len(table.table.columns) == 1, table.table.columns

    def test_unexpected_column_kwarg(self, caplog):
        obj = {"columns": [{"field": "A", "class": None}]}
        table = galleries.table_query.parse_rich_table_object(obj)
        assert self.assert_msg_in_warning("class", caplog)
        assert not table.fieldnames

    def assert_msg_in_warning(self, substring, caplog):
        return any(
            substring in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )


@pytest.mark.usefixtures("set_columns")
class TestRichTablePrinter:
    def test_default_rich_table(self):
        printer = galleries.table_query.parse_rich_table_object({})
        assert not printer.fieldnames
        assert printer.console is galleries.util.console
        assert printer.add_fields
        assert printer.table.box == galleries.table_query.DEFAULT_BOX
        assert not printer.table.columns

    def test_add_fields(self):
        printer = galleries.table_query.parse_rich_table_object({})
        fieldnames = list("ABCD")
        printer.check_fields(fieldnames)
        assert printer.fieldnames == fieldnames

    def test_check_fields(self):
        printer = galleries.table_query.parse_rich_table_object(
            {"columns": [{"field": "FieldA"}]}
        )
        with pytest.raises(galleries.table_query.FormatterError, match="FieldA"):
            printer.check_fields([])

    def test_print_no_fieldnames(self, capsys):
        printer = galleries.table_query.parse_rich_table_object({})
        printer.print(_gallery_gen())
        assert capsys.readouterr().out.isspace()

    def test_print_valid_fieldnames(self, capsys):
        printer = galleries.table_query.parse_rich_table_object({})
        printer.check_fields({"FieldA"})
        printer.print(_gallery_gen())
        captured = capsys.readouterr()
        assert "FieldA" in captured.out

    def test_print_field_not_found(self):
        printer = galleries.table_query.parse_rich_table_object({})
        # The second gallery does not have FieldB.
        printer.check_fields({"FieldA", "FieldB"})
        with pytest.raises(KeyError, match=repr("FieldB")):
            printer.print(_gallery_gen())

    def test_print_bad_table(self):
        table = rich.table.Table()
        table.add_column(-1)  # type: ignore
        printer = galleries.table_query.RichTablePrinter(table, ["FieldA"])
        with pytest.raises(galleries.table_query.FormatterError):
            printer.print(_gallery_gen())


def any_error_logs(caplog):
    return any(record.levelname == "ERROR" for record in caplog.records)


def _gallery_gen(data=None):
    data = data or [{"FieldA": "a", "FieldB": "b", "FieldC": "c"}, {"FieldA": "a"}]
    for mapping in data:
        yield galleries.galleryms.Gallery(mapping)
