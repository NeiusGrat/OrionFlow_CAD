"""M0 acceptance (§14): `orion-harness --help` works."""

import pytest

from orion_harness.cli import build_parser, main


def test_help_does_not_raise(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "orion-harness" in out


def test_no_args_prints_help_and_returns_zero(capsys):
    assert main([]) == 0


def test_parser_has_expected_subcommands():
    parser = build_parser()
    sub_actions = [a for a in parser._subparsers._group_actions if hasattr(a, "choices")]
    names = set(sub_actions[0].choices.keys())
    assert {"run", "verify", "selftest", "compare", "report", "power", "tasks"} <= names
