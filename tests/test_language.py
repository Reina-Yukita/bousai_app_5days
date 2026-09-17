from app import app


def test_set_language_updates_session():
    client = app.test_client()
    response = client.post('/set_language', data={'lang': 'en', 'next': '/'}, follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session['lang'] == 'en'


def test_set_language_rejects_unsupported_language():
    client = app.test_client()
    response = client.post('/set_language', data={'lang': 'fr', 'next': '/'}, follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session.get('lang', 'ja') == 'ja'
