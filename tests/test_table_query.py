"""Unit tests for table_query, using pytest"""

import re
import sys

import pytest

import galleries.galleryms
import galleries.table_query


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

    @pytest.mark.parametrize("sort_field", [*_fieldnames, None])
    def test_successful(self, capsys, sort_field):
        # These galleries are already sorted, so results should appear in the
        # same order regardless of the value of sort_field.
        gallery_gen = (galleries.galleryms.Gallery(mapping) for mapping in self._data)
        status = galleries.table_query.main(
            galleries=gallery_gen, fieldnames=self._fieldnames, sort_field=sort_field
        )
        assert status == 0
        out, err = capsys.readouterr()
        assert not err
        results = out.splitlines()
        assert results[0] == "FieldA,FieldB"
        object_regex = r"<object object at 0x[0-9a-f]+>"
        assert re.match(rf"{object_regex},{object_regex}\Z", results[1])
        assert results[2] == "{'a'},{'b'}"

    def test_sort_field_not_found(self, caplog):
        status = galleries.table_query.main(
            galleries=[], fieldnames=self._fieldnames, sort_field=self._bogus_field
        )
        self._assert_field_not_found(status, caplog)

    def test_format_field_not_found(self, caplog):
        status = galleries.table_query.main(
            galleries=[],
            fieldnames=self._fieldnames,
            field_formats={self._bogus_field: galleries.galleryms.FieldFormat(80)},
        )
        self._assert_field_not_found(status, caplog)

    def _assert_field_not_found(self, status, caplog):
        assert status == 1
        assert any_error_logs(caplog)
        assert self._bogus_field in caplog.text


@pytest.mark.usefixtures("set_columns")
class TestPrintFormatted:
    def gallery_gen(self):
        for mapping in [{"FieldA": "a", "FieldB": "b", "FieldC": "c"}, {"FieldA": "a"}]:
            yield galleries.galleryms.Gallery(mapping)

    @pytest.mark.parametrize(
        ("field_formats", "expected_out"),
        [({}, []), ({"FieldA": galleries.galleryms.FieldFormat(79)}, [" a", " a"])],
    )
    def test_successful(self, capsys, field_formats, expected_out):
        # For some reason, it is important that file=sys.stdout be specified
        # in the body of the test function in order for capsys to work.
        galleries.table_query.print_formatted(
            rows=self.gallery_gen(), field_formats=field_formats, file=sys.stdout
        )
        captured = capsys.readouterr()
        assert captured.out.splitlines() == expected_out

    def test_format_field_not_found(self, capsys):
        bogus_field = "CdleiF"
        field_formats = {bogus_field: galleries.galleryms.FieldFormat(79)}
        with pytest.raises(KeyError, match=repr(bogus_field)):
            galleries.table_query.print_formatted(
                rows=self.gallery_gen(), field_formats=field_formats, file=sys.stdout
            )
        assert not capsys.readouterr().out


def any_error_logs(caplog):
    return any(record.levelname == "ERROR" for record in caplog.records)
