import pytest

from line_mac_reader.main import build_parser


def test_chat_flag_repeatable():
    args = build_parser().parse_args(["--chat", "王小明", "--chat", "家人群"])
    assert args.chat == ["王小明", "家人群"]
    assert not args.all_chats


def test_all_flag():
    args = build_parser().parse_args(["--all"])
    assert args.all_chats
    assert args.chat is None


def test_chat_and_all_mutually_exclusive():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--all", "--chat", "x"])


def test_default_is_unread_only():
    args = build_parser().parse_args([])
    assert args.chat is None
    assert not args.all_chats
    assert not args.ignore_last_read


def test_ignore_last_read_with_window():
    args = build_parser().parse_args(
        ["--chat", "王小明", "--fallback-hours", "120", "--ignore-last-read"])
    assert args.fallback_hours == 120
    assert args.ignore_last_read
