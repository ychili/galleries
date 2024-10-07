"""Unit tests for table_query, using pytest"""

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


def any_error_logs(caplog):
    return any(record.levelname == "ERROR" for record in caplog.records)
