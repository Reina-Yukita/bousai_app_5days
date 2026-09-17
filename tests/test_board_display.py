from app import format_board_datetime


def test_format_board_datetime_converts_to_jst():
    assert format_board_datetime('2026-09-17T04:14:00+00:00') == '2026年9月17日 13:14'


def test_format_board_datetime_keeps_local_without_timezone():
    assert format_board_datetime('2026-09-17T13:14') == '2026年9月17日 13:14'
