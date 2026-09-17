from app import app, format_board_datetime, home_board_instructions


def test_format_board_datetime_converts_to_jst():
    assert format_board_datetime('2026-09-17T04:14:00+00:00') == '2026年9月17日 13:14'


def test_format_board_datetime_keeps_local_without_timezone():
    assert format_board_datetime('2026-09-17T13:14') == '2026年9月17日 13:14'


def test_home_displays_board_before_quick_access_for_all_users():
    client = app.test_client()

    for logged_in in (False, True):
        if logged_in:
            with client.session_transaction() as session:
                session['logged_in'] = True
        response = client.get('/')
        body = response.get_data(as_text=True)

        assert response.status_code == 200
        assert '指示・発信ボード' in body
        assert '発信一覧' in body
        assert body.index('指示・発信ボード') < body.index('防災情報にすぐアクセス')


def test_home_board_instructions_only_contains_high_urgency_items():
    assert home_board_instructions()
    assert all(item['urgency'] == '高' for item in home_board_instructions())
