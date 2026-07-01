"""End-to-end tests requiring subprocess, using pytest"""

import functools
import shutil
import subprocess
import sys

import pytest

import galleries.cli
import galleries.cli.lib

run_normal = functools.partial(
    subprocess.run, check=True, capture_output=True, encoding="utf-8"
)


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_version(flag):
    cmd = "galleries"
    my_galleries = shutil.which(cmd)
    assert my_galleries is not None, "Executable not found on $PATH!"
    args = [my_galleries, flag]
    proc = run_normal(args)
    assert cmd in proc.stdout
    assert galleries.cli.__version__ in proc.stdout


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help(flag):
    my_galleries = shutil.which("galleries")
    assert my_galleries is not None, "Executable not found on $PATH!"
    args = [my_galleries, flag]
    proc = run_normal(args)
    assert proc.stdout.startswith("usage: galleries")


CSV_TAGS_ONLY = b"Tags\n\nA B C\nC B A\nD\nA E\n\n"


@pytest.fixture
def setup_collection(initialize_collection):
    csv_path = (
        initialize_collection
        / galleries.cli.DB_DIR_NAME
        / galleries.cli.lib.DEFAULT_CONFIG_STATE["db"]["CSVName"]
    )
    csv_path.write_bytes(CSV_TAGS_ONLY)
    return initialize_collection


@pytest.mark.parametrize(
    ("query_args", "expected_results"),
    [
        ([], {"a": "3", "b": "2", "c": "2", "d": "1", "e": "1"}),
        (["b"], {"a": "2", "b": "2", "c": "2"}),
    ],
)
def test_pipe_query_to_count(setup_collection, query_args, expected_results):
    """Pipe the results of "query" to "count"."""
    collection_args = ("-c", str(setup_collection))
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


@pytest.mark.parametrize(
    "cmd_args", [["count"], ["count", "--summarize"], ["query"], ["related"]]
)
def test_broken_pipe(setup_collection, capsys, cmd_args):
    with subprocess.Popen(
        ["galleries", "-c", str(setup_collection), *cmd_args],
        stdout=subprocess.PIPE,
    ) as cmd_proc:
        run_normal(
            [sys.executable, "-c", "import sys; sys.stdin.close()"],
            stdin=cmd_proc.stdout,
        )
    assert cmd_proc.returncode == 0
    assert not capsys.readouterr().err
