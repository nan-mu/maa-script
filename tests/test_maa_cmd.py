from pathlib import Path

from maa_runner.maa import _with_log_file


def test_log_file_bare_flag_is_not_given_a_path():
    path = Path("/tmp/run.log")
    assert _with_log_file(("-vv", "--batch", "--log-file"), path) == [
        "-vv",
        "--batch",
        "--log-file",
    ]


def test_extra_args_passed_through_unchanged():
    path = Path("/tmp/ignored.log")
    assert _with_log_file(("-vv", "--batch"), path) == ["-vv", "--batch"]
