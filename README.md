# 防災アプリ

青森市の気象警報・注意報、避難所、地域のお知らせを確認できる Flask アプリです。

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 起動

```bash
python app.py
```

ブラウザで http://127.0.0.1:5000/ を開きます。

管理者ログインのサンプル認証情報は、ユーザー名 `admin`、パスワード `123` です。開発環境では `SECRET_KEY` 環境変数を設定できます。

## 確認

```bash
python -m py_compile app.py
python - <<'PY'
from app import app
with app.test_client() as client:
    assert client.get('/').status_code == 200
    assert client.get('/api/weather_warnings').status_code == 200
    assert client.get('/shelters').status_code == 200
print('ok')
PY
```

気象庁APIの取得に失敗した場合も、ホーム画面にはエラー状態を表示して操作を継続できます。
