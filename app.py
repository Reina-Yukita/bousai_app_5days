from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from urllib.parse import urlparse, urljoin
from functools import wraps
from werkzeug.utils import secure_filename
import gzip
import json
import os
import random
import urllib.error
import urllib.request
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

# app.py はプロジェクト直下に置く。
# 実体（templates / static / data）は bousai_app/ 配下にあるので、そこを参照する。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'bousai_app')

app = Flask(
    __name__,
    template_folder=os.path.join(APP_DIR, 'templates'),
    static_folder=os.path.join(APP_DIR, 'static'),
)
app.secret_key = os.environ.get('SECRET_KEY', 'development-secret-key')

# 管理者認証情報
ADMIN_CREDENTIALS = {
    'admin': '123'
}

# ────────────────────────────────
# 気象警報・注意報設定
PREFECTURE_CODE = "020000"  # 青森県
AREA_NAME = "青森市"

# 青森市の市区町村コード
AREA_CODE = "0220100"

# 土砂災害警戒情報（VXWW50）の対象地域設定
LANDSLIDE_PREFECTURE_CODE = "020"
LANDSLIDE_AREA_NAME = "青森市"
LANDSLIDE_AREA_CODE = "220100"
LANDSLIDE_DATA_TYPE = "VXWW50"
JMA_XML_FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/regular.xml"

WARNING_URL = (
    f"https://www.jma.go.jp/bosai/warning/data/r8/{PREFECTURE_CODE}.json"
)

JST = timezone(timedelta(hours=9))

# 警報・注意報のコード一覧
WARNING_CODES = {
    "00": "解除",
    "02": "暴風雪警報",
    "03": "レベル3大雨警報",
    "04": "洪水警報",
    "05": "暴風警報",
    "06": "大雪警報",
    "07": "波浪警報",
    "08": "レベル3高潮警報",
    "09": "レベル3土砂災害警報",
    "10": "レベル2大雨注意報",
    "12": "大雪注意報",
    "13": "風雪注意報",
    "14": "雷注意報",
    "15": "強風注意報",
    "16": "波浪注意報",
    "17": "融雪注意報",
    "18": "洪水注意報",
    "19": "レベル2高潮注意報",
    "20": "濃霧注意報",
    "21": "乾燥注意報",
    "22": "なだれ注意報",
    "23": "低温注意報",
    "24": "霜注意報",
    "25": "着氷注意報",
    "26": "着雪注意報",
    "27": "その他の注意報",
    "29": "レベル2土砂災害注意報",
    "32": "暴風雪特別警報",
    "33": "レベル5大雨特別警報",
    "35": "暴風特別警報",
    "36": "大雪特別警報",
    "37": "波浪特別警報",
    "38": "レベル5高潮特別警報",
    "39": "レベル5土砂災害特別警報",
    "43": "レベル4大雨危険警報",
    "48": "レベル4高潮危険警報",
    "49": "レベル4土砂災害危険警報"
}

WARNING_LEVELS = {
    "02": 3, "03": 3, "04": 3, "05": 3, "06": 3, "07": 3, "08": 3, "09": 3,
    "32": 5, "33": 5, "35": 5, "36": 5, "37": 5, "38": 5, "39": 5,
    "43": 4, "48": 4, "49": 4,
    "10": 2, "12": 2, "13": 2, "14": 2, "15": 2, "16": 2, "17": 2,
    "18": 2, "19": 2, "20": 2, "21": 2, "22": 2, "23": 2, "24": 2,
    "25": 2, "26": 2, "27": 2, "29": 2
}

WARNING_HAZARDS = {
    "02": "暴風雪", "03": "大雨", "04": "洪水", "05": "暴風", "06": "大雪",
    "07": "波浪", "08": "高潮", "09": "土砂災害", "10": "大雨", "12": "大雪",
    "13": "風雪", "14": "雷", "15": "強風", "16": "波浪", "17": "融雪",
    "18": "洪水", "19": "高潮", "20": "濃霧", "21": "乾燥", "22": "なだれ",
    "23": "低温", "24": "霜", "25": "着氷", "26": "着雪", "27": "その他",
    "29": "土砂災害"
}

# ────────────────────────────────
# サンプルデータの読み込み
DATA_FILE = os.path.join(APP_DIR, 'data', 'shelters.json')
INSTRUCTIONS_FILE = os.path.join(APP_DIR, 'data', 'instructions.json')
UPLOAD_DIR = os.path.join(app.static_folder, 'uploads')

def load_json(path, default):
    """JSONファイルを読み込む（存在しない・壊れている場合は default を返す）"""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

shelters = load_json(DATA_FILE, [])
instructions = load_json(INSTRUCTIONS_FILE, [])
SHELTER_GEOCODE_CACHE = {}

FACILITY_OPTIONS = {
    'shortest': '最短',
    'barrier_free': 'バリアフリー',
    'parking': '駐車場あり',
    'nursing_room': '授乳室あり',
    'pets_allowed': 'ペット可',
    'universal_design': 'ユニバーサルデザイン',
    'prayer_room': '礼拝室あり',
    'air_conditioning': '空調完備',
    'large_facility': '大規模施設',
}
RANDOM_FACILITY_KEYS = tuple(
    key for key in FACILITY_OPTIONS if key not in ('shortest', 'large_facility')
)
AVAILABILITY_OPTIONS = ('満員', '余裕あり', '普通')
SUPPORTED_LANGUAGES = {
    'ja': '日本語',
    'en': 'English',
    'zh': '中文',
    'ko': '한국어',
}
LANGUAGE_TEXTS = {
    'ja': {
        'language': '言語',
        'nav_home': 'ホーム',
        'nav_shelter_search': '避難所検索',
        'nav_board': 'お知らせ',
        'nav_register': '避難所登録',
        'nav_login': 'ログイン',
        'nav_logout': 'ログアウト',
        'hero_kicker': '防災・気象情報',
        'brand': '青森市防災web',
        'location_label': '青森市',
        'status_ok': '現在、警報・注意報はありません',
        'status_warning': '警報・注意報あり',
        'status_fetch_error': '気象情報を取得できません',
        'alert_title': '警報・注意報があります',
        'alert_status': '発表状態を確認してください',
        'alert_detail': '詳細を見る →',
        'menu_button': 'メニューを開く',
        'home_weather_status': 'CURRENT STATUS',
        'home_weather_title': '青森市の状況',
        'home_weather_subtitle': 'いま確認できる気象情報',
        'home_weather_loading': '気象情報を読み込んでいます...',
        'home_map_title': '避難所マップ',
        'home_map_subtitle': '現在地周辺の避難所を確認',
        'home_map_link': '一覧を見る →',
        'home_quick_access': '防災情報にすぐアクセス',
        'home_quick_access_label': 'QUICK ACCESS',
        'home_find_shelter': '避難所を探す',
        'home_find_shelter_desc': '開設状況や場所を確認',
        'home_data_view': 'データを見る',
        'home_data_view_desc': '気象・防災情報を確認',
        'home_board': 'みんなの防災情報',
        'home_board_desc': '地域からのお知らせ',
        'home_plan': '青森県防災ハンドブック',
        'home_plan_desc': '外部リンク',
        'search_heading': '避難所検索',
        'search_location_getting': '現在地を取得中...',
        'search_location_refresh': '現在地を再取得',
        'search_town_label': '避難所町名',
        'search_select_none': '選択なし',
        'search_name_label': '避難所名',
        'search_name_placeholder': '避難所名を入力',
        'search_button': '検索',
        'search_conditions': '条件選択',
        'search_status_unknown': '市区町村名不明',
    },
    'en': {
        'language': 'Language',
        'nav_home': 'Home',
        'nav_shelter_search': 'Shelters',
        'nav_board': 'Alerts',
        'nav_register': 'Register',
        'nav_login': 'Login',
        'nav_logout': 'Logout',
        'hero_kicker': 'Disaster & Weather Info',
        'brand': 'Disaster App',
        'location_label': 'Aomori City',
        'status_ok': 'No warnings or advisories currently',
        'status_warning': 'Warnings/advisories issued',
        'status_fetch_error': 'Weather information unavailable',
        'alert_title': 'Warnings or advisories issued',
        'alert_status': 'Check current conditions',
        'alert_detail': 'See details →',
        'menu_button': 'Open menu',
        'home_weather_status': 'CURRENT STATUS',
        'home_weather_title': 'Aomori City Conditions',
        'home_weather_subtitle': 'Current weather information',
        'home_weather_loading': 'Loading weather information...',
        'home_map_title': 'Shelter Map',
        'home_map_subtitle': 'Check nearby shelters',
        'home_map_link': 'View list →',
        'home_quick_access': 'Quick access to disaster information',
        'home_quick_access_label': 'QUICK ACCESS',
        'home_find_shelter': 'Find a shelter',
        'home_find_shelter_desc': 'Check opening status and location',
        'home_data_view': 'View data',
        'home_data_view_desc': 'Check weather and disaster information',
        'home_board': 'Community disaster info',
        'home_board_desc': 'Announcements from the region',
        'home_plan': 'My family evacuation plan',
        'home_plan_desc': 'Register and review evacuation destinations',
        'search_heading': 'Shelter Search',
        'search_location_getting': 'Getting current location...',
        'search_location_refresh': 'Refresh location',
        'search_town_label': 'Shelter district',
        'search_select_none': 'No selection',
        'search_name_label': 'Shelter name',
        'search_name_placeholder': 'Enter shelter name',
        'search_button': 'Search',
        'search_conditions': 'Filter options',
        'search_status_unknown': 'Location unknown',
    },
    'zh': {
        'language': '语言',
        'nav_home': '首页',
        'nav_shelter_search': '避难所搜索',
        'nav_board': '公告',
        'nav_register': '登记避难所',
        'nav_login': '登录',
        'nav_logout': '退出',
        'hero_kicker': '灾害与天气信息',
        'brand': '灾害应用',
        'location_label': '青森市',
        'status_ok': '目前没有警报或注意事项',
        'status_warning': '已发布警报/注意事项',
        'status_fetch_error': '无法获取天气信息',
        'alert_title': '已发布警报/注意事项',
        'alert_status': '请确认当前状态',
        'alert_detail': '查看详情 →',
        'menu_button': '打开菜单',
        'home_weather_status': 'CURRENT STATUS',
        'home_weather_title': '青森市现状',
        'home_weather_subtitle': '当前可查看的天气信息',
        'home_weather_loading': '正在读取天气信息...',
        'home_map_title': '避难所地图',
        'home_map_subtitle': '查看周边避难所',
        'home_map_link': '查看列表 →',
        'home_quick_access': '快速访问防灾信息',
        'home_quick_access_label': 'QUICK ACCESS',
        'home_find_shelter': '寻找避难所',
        'home_find_shelter_desc': '查看开放状态和地点',
        'home_data_view': '查看数据',
        'home_data_view_desc': '查看天气和防灾信息',
        'home_board': '大家的防灾信息',
        'home_board_desc': '来自地区的公告',
        'home_plan': '我家的避难计划',
        'home_plan_desc': '登记与确认避难地点',
        'search_heading': '避难所搜索',
        'search_location_getting': '正在获取当前位置...',
        'search_location_refresh': '重新获取当前位置',
        'search_town_label': '避难所町名',
        'search_select_none': '不选择',
        'search_name_label': '避难所名称',
        'search_name_placeholder': '输入避难所名称',
        'search_button': '搜索',
        'search_conditions': '筛选条件',
        'search_status_unknown': '未知市区町村',
    },
    'ko': {
        'language': '언어',
        'nav_home': '홈',
        'nav_shelter_search': '대피소 검색',
        'nav_board': '공지',
        'nav_register': '대피소 등록',
        'nav_login': '로그인',
        'nav_logout': '로그아웃',
        'hero_kicker': '재난 및 기상 정보',
        'brand': '재난 앱',
        'location_label': '아오모리시',
        'status_ok': '현재 경보·주의보가 없습니다',
        'status_warning': '경보·주의보 발령 중',
        'status_fetch_error': '기상 정보를 가져올 수 없습니다',
        'alert_title': '경보·주의보가 발령되었습니다',
        'alert_status': '발표 상태를 확인하세요',
        'alert_detail': '자세히 보기 →',
        'menu_button': '메뉴 열기',
        'home_weather_status': 'CURRENT STATUS',
        'home_weather_title': '아오모리시 현황',
        'home_weather_subtitle': '현재 확인할 수 있는 기상 정보',
        'home_weather_loading': '기상 정보를 불러오는 중...',
        'home_map_title': '대피소 지도',
        'home_map_subtitle': '현재 위치 주변 대피소 확인',
        'home_map_link': '목록 보기 →',
        'home_quick_access': '재난 정보에 즉시 접근',
        'home_quick_access_label': 'QUICK ACCESS',
        'home_find_shelter': '대피소 찾기',
        'home_find_shelter_desc': '운영 상태와 위치 확인',
        'home_data_view': '데이터 보기',
        'home_data_view_desc': '기상·재난 정보 확인',
        'home_board': '우리 지역의 재난 정보',
        'home_board_desc': '지역에서 전달된 공지',
        'home_plan': '우리 집 대피 계획',
        'home_plan_desc': '대피 장소 등록 및 확인',
        'search_heading': '대피소 검색',
        'search_location_getting': '현재 위치를 가져오는 중...',
        'search_location_refresh': '현재 위치 다시 찾기',
        'search_town_label': '대피소 시/구',
        'search_select_none': '선택 안 함',
        'search_name_label': '대피소명',
        'search_name_placeholder': '대피소명을 입력하세요',
        'search_button': '검색',
        'search_conditions': '조건 선택',
        'search_status_unknown': '시/구 정보를 알 수 없음',
    }
}


def get_current_language():
    language = session.get('lang', 'ja')
    if language not in SUPPORTED_LANGUAGES:
        return 'ja'
    return language


def translate_text(key, default=''):
    texts = LANGUAGE_TEXTS.get(get_current_language(), LANGUAGE_TEXTS['ja'])
    return texts.get(key, default or LANGUAGE_TEXTS['ja'].get(key, key))


@app.context_processor
def shelter_options_context():
    current_lang = get_current_language()
    return {
        'facility_options': FACILITY_OPTIONS,
        'availability_options': AVAILABILITY_OPTIONS,
        'supported_languages': SUPPORTED_LANGUAGES,
        'current_language': current_lang,
        't': translate_text,
    }

def save_instructions():
    """指示ボードのデータをファイルに保存する"""
    try:
        with open(INSTRUCTIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def normalize_instruction(instruction):
    """旧形式の発信データをボード表示用の形式にそろえる"""
    shelter_names = instruction.get('shelters')
    if shelter_names is None:
        shelter = instruction.get('shelter', '')
        shelter_names = [shelter] if shelter else []
    elif isinstance(shelter_names, str):
        shelter_names = [shelter_names] if shelter_names else []

    status = instruction.get('status', '発信中')
    if status not in ('発信中', '解除済'):
        status = '解除済' if status in ('解除', '完了') else '発信中'
    urgency = instruction.get('urgency', '低')
    if urgency not in ('高', '中', '低'):
        urgency = '低'
    created_at = instruction.get('created_at', '')
    updated_at = instruction.get('updated_at', created_at)
    resolved_at = instruction.get('resolved_at')
    return {
        'id': instruction.get('id'),
        'content': instruction.get('content', ''),
        'area': instruction.get('area', '未設定'),
        'shelters': shelter_names,
        'status': status,
        'resolved_at': resolved_at,
        'created_at': created_at,
        'updated_at': updated_at,
        'created_at_display': format_board_datetime(created_at),
        'resolved_at_display': format_board_datetime(resolved_at),
        'urgency': urgency,
        'translations': instruction.get('translations', {}),
    }


def current_instruction_time():
    return datetime.now(JST).isoformat(timespec='minutes')


def format_board_datetime(value):
    """表示用の日時文字列を「年月日時刻」で返す"""
    if not value:
        return '－'
    if isinstance(value, datetime):
        dt = value
    else:
        value_str = str(value)
        try:
            dt = datetime.fromisoformat(value_str.replace('Z', '+00:00'))
        except ValueError:
            return value_str
    if dt.tzinfo is not None:
        dt = dt.astimezone(JST)
    else:
        dt = dt.replace(tzinfo=JST)
    return dt.strftime('%Y年%-m月%-d日 %H:%M')


def board_instructions():
    return [normalize_instruction(instruction) for instruction in instructions
            if instruction.get('target', '住民') == '住民']


def home_board_instructions():
    return [instruction for instruction in board_instructions()
            if instruction['urgency'] == '高']


def selected_instruction_ids(form):
    return {value for value in form.getlist('selected_ids') if value}

def save_shelters():
    """避難所データをファイルに保存する"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(shelters, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def geocode_shelter(shelter):
    """国土地理院の住所検索APIで避難所住所を座標に変換する"""
    address = (shelter.get('address') or '').strip()
    if not address:
        return None
    if address in SHELTER_GEOCODE_CACHE:
        return SHELTER_GEOCODE_CACHE[address]

    query = urlencode({'q': address})
    try:
        request = urllib.request.Request(
            f'https://msearch.gsi.go.jp/address-search/AddressSearch?{query}',
            headers={'Accept': 'application/json', 'User-Agent': 'bousai-app/1.0'},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            results = json.loads(response.read())
        coordinates = results[0].get('geometry', {}).get('coordinates', []) if results else []
        if len(coordinates) < 2:
            return None
        point = {'latitude': float(coordinates[1]), 'longitude': float(coordinates[0])}
        SHELTER_GEOCODE_CACHE[address] = point
        return point
    except (OSError, ValueError, TypeError, IndexError, json.JSONDecodeError):
        return None


def shelter_map_points(selected_ids=None):
    """住所から得た座標だけを地図表示用の形式で返す"""
    source = current_shelters()
    if selected_ids is not None:
        source = [shelter for shelter in source if str(shelter.get('id')) in selected_ids]

    def add_coordinates(shelter):
        point = geocode_shelter(shelter)
        if not point:
            return None
        return {'id': shelter.get('id'), 'name': shelter.get('name', ''), **point}

    with ThreadPoolExecutor(max_workers=8) as executor:
        points = executor.map(add_coordinates, source)
    return [point for point in points if point]

def current_shelters():
    """検索・一覧表示用に保存済みの最新避難所データを返す"""
    return load_json(DATA_FILE, shelters)


def shelter_form_data(form, image_path=''):
    """登録・編集フォームの値を保存用の辞書に整える"""
    data = {
        'name': form.get('name', '').strip(),
        'district': form.get('district', '').strip(),
        'address': form.get('address', '').strip(),
        'phone': form.get('phone', '').strip(),
        'map_image': image_path or form.get('map_image', '').strip(),
        'capacity': form.get('capacity', '').strip(),
        'features': form.getlist('features'),
        'supplies': form.get('supplies', '').strip(),
        'availability': form.get('availability', '普通'),
    }
    if data['availability'] not in AVAILABILITY_OPTIONS:
        data['availability'] = '普通'
    selected_facilities = set(form.getlist('facilities'))
    data.update({key: key in selected_facilities for key in FACILITY_OPTIONS})
    data['large_facility'] = is_large_facility(data['capacity'])
    return data


def is_large_facility(capacity):
    """最大収容人数が1000人以上の避難所を大規模施設として扱う"""
    try:
        return int(str(capacity).strip()) >= 1000
    except (TypeError, ValueError):
        return False


def normalize_shelter(shelter, index=0):
    """旧データを検索結果表示用の既定値付き形式にする"""
    normalized = dict(shelter)
    normalized['availability'] = (
        shelter.get('availability')
        if shelter.get('availability') in AVAILABILITY_OPTIONS else '普通'
    )
    normalized['supplies'] = (
        shelter.get('supplies')
        if shelter.get('supplies') in ('十分足りている', '足りている', '足りていない', '全く足りていない')
        else '十分足りている'
    )
    normalized.update({key: bool(shelter.get(key, False)) for key in FACILITY_OPTIONS})
    randomizer = random.Random(f"shelter-facilities:{shelter.get('id', index)}")
    normalized.update({key: randomizer.choice((False, True)) for key in RANDOM_FACILITY_KEYS})
    normalized['large_facility'] = is_large_facility(shelter.get('capacity'))
    normalized['_registration_order'] = index
    return normalized


def search_shelters(args):
    """入力された条件で避難所を検索し、一致数の降順で安定ソートする"""
    keyword = args.get('name', '').strip()
    district = args.get('district', '').strip()
    municipality = args.get('municipality', '').strip()
    selected = [key for key in args.getlist('facility') if key in FACILITY_OPTIONS]
    results = []
    for index, shelter in enumerate(current_shelters()):
        item = normalize_shelter(shelter, index)
        if keyword and keyword not in item.get('name', ''):
            continue
        if district and district not in item.get('district', ''):
            continue
        if municipality and municipality not in item.get('address', ''):
            continue
        item['_matched_facilities'] = sum(item[key] for key in selected)
        item['_selected_facilities'] = selected
        results.append(item)
    results.sort(key=lambda item: (-item['_matched_facilities'], item['_registration_order']))
    return results, keyword, selected, district, municipality


def validate_shelter_data(data):
    """避難所名を検証する。追加項目は任意で登録できる。"""
    if not data.get('name'):
        return '避難所名を入力してください。'
    if data.get('phone') and not data['phone'].isdigit():
        return '電話番号は数値で入力してください。'
    if data.get('capacity') and not data['capacity'].isdigit():
        return '最大収容人数は数値で入力してください。'
    return ''


def shelter_name_exists(name, exclude_id=None):
    """同名の避難所が登録済みか確認する"""
    return any(
        shelter.get('name') == name and shelter.get('id') != exclude_id
        for shelter in shelters
    )


def shelter_matches_area(shelter, area):
    """避難所の町名または住所に対象地域が含まれるか判定する"""
    if area in ('全域', '青森市全域'):
        return True
    area = (area or '').strip()
    if not area:
        return False
    district = (shelter.get('district') or '').strip()
    address = (shelter.get('address') or '').strip()
    return area in district or area in address


def save_uploaded_map(upload):
    """アップロードされた地図画像を static/uploads に保存する"""
    if not upload or not upload.filename:
        return ''
    extension = os.path.splitext(secure_filename(upload.filename))[1].lower()
    if extension not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
        return ''
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"map_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{extension}"
    upload.save(os.path.join(UPLOAD_DIR, filename))
    return url_for('static', filename=f'uploads/{filename}')
# ────────────────────────────────

# ────────────────────────────────
# 認証関連の設定とヘルパー関数
def is_safe_url(target):
    """リダイレクト先URLが安全かどうかチェック"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def login_required(f):
    """認証が必要なページに付けるデコレータ"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            # 現在のURLをnextパラメータとしてログイン画面にリダイレクト
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def get_japan_time():
    """日本時間（JST）の現在時刻を取得する"""
    return datetime.now(JST).strftime("%Y年%m月%d日 %H:%M")


def format_report_time(iso_str):
    """気象庁の発表時刻（ISO形式）をJSTの表示用文字列に変換する"""
    if not iso_str:
        return "不明"
    try:
        parsed = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        if parsed.tzinfo:
            parsed = parsed.astimezone(JST)
        return parsed.strftime("%Y年%m月%d日 %H:%M")
    except ValueError:
        return iso_str


def filter_shelters(district=None):
    """district 指定があれば一致する避難所のみ、なければ全件を返す"""
    return [s for s in shelters if not district or s.get('district') == district]


def parse_area_warnings(warning_data):
    """気象庁の新形式JSONから対象市区町村の発表・継続中の情報を抽出する"""
    if not isinstance(warning_data, list):
        raise ValueError("気象庁の警報・注意報データが新形式の配列ではありません")

    warnings = []
    seen_codes = set()
    report_datetimes = []

    for report in warning_data:
        if not isinstance(report, dict):
            continue

        report_datetime = report.get("reportDatetime")
        if isinstance(report_datetime, str) and report_datetime:
            report_datetimes.append(report_datetime)

        warning = report.get("warning")
        if not isinstance(warning, dict):
            continue

        class20_items = warning.get("class20Items", [])
        if not isinstance(class20_items, list):
            continue

        area = next(
            (
                item for item in class20_items
                if isinstance(item, dict)
                and item.get("areaCode") == AREA_CODE
            ),
            None
        )
        if not area:
            continue

        kinds = area.get("kinds", [])
        if not isinstance(kinds, list):
            continue

        for kind in kinds:
            if not isinstance(kind, dict):
                continue

            status = kind.get("status", "")
            code = kind.get("code", "")
            if status not in ("発表", "継続") or not code or code in seen_codes:
                continue

            warnings.append({
                "name": WARNING_CODES.get(
                    code,
                    f"不明な警報・注意報 (コード: {code})"
                ),
                "code": code,
                "status": status,
                "level": WARNING_LEVELS.get(code, 2),
                "hazard": WARNING_HAZARDS.get(code, "気象")
            })
            seen_codes.add(code)

    latest_report_datetime = max(report_datetimes, default="")
    return warnings, latest_report_datetime


def get_weather_warnings():
    """対象市区町村の警報・注意報を取得する"""
    try:
        # 青森県の新形式（令和8年～）警報・注意報データを取得
        with urllib.request.urlopen(url=WARNING_URL, timeout=10) as res:
            warning_data = json.loads(res.read())

        warnings, report_datetime = parse_area_warnings(warning_data)

        return {
            "area_name": AREA_NAME,
            "warnings": warnings,
            "report_time": format_report_time(report_datetime),
            "last_fetch_time": get_japan_time(),
            "map": {"city": AREA_NAME, "lat": 40.8246, "lon": 140.7400, "zoom": 11, "radius_km": 18}
        }

    except Exception:
        return {
            "area_name": AREA_NAME,
            "warnings": [],
            "report_time": "取得失敗",
            "last_fetch_time": get_japan_time(),
            "map": {"city": AREA_NAME, "lat": 40.8246, "lon": 140.7400, "zoom": 11, "radius_km": 18},
            "error": True
        }


def _xml_local_name(tag):
    """namespace付きXMLタグからローカル名を取り出す"""
    return tag.rsplit('}', 1)[-1]


def _xml_text(element, name):
    """要素の直下から指定名のテキストを取得する"""
    child = next(
        (item for item in list(element)
         if _xml_local_name(item.tag) == name),
        None
    )
    return (child.text or '').strip() if child is not None else ''


def _empty_landslide_warning():
    return {
        "area_name": LANDSLIDE_AREA_NAME,
        "area_code": LANDSLIDE_AREA_CODE,
        "status": "",
        "kind": "",
        "kind_code": "",
        "report_time": "不明",
        "headline": "",
        "is_warning": False,
        "last_fetch_time": get_japan_time()
    }


def _get_latest_landslide_xml_url():
    """JMAの定期フィードからVXWW50の最新XML URLを取得する"""
    with urllib.request.urlopen(JMA_XML_FEED_URL, timeout=10) as res:
        feed_root = ET.fromstring(res.read())

    candidates = []
    for entry in feed_root.iter():
        if _xml_local_name(entry.tag) != 'entry':
            continue
        entry_text = ' '.join(text.strip() for text in entry.itertext() if text.strip())
        if LANDSLIDE_DATA_TYPE not in entry_text:
            continue
        for link in entry.iter():
            if _xml_local_name(link.tag) != 'link':
                continue
            href = link.attrib.get('href', '')
            if href.endswith(('.xml.gz', '.xml')):
                candidates.append(href)

    return candidates[0] if candidates else ''


def get_landslide_warning():
    """青森市の土砂災害警戒情報（VXWW50）を取得する"""
    result = _empty_landslide_warning()
    try:
        xml_url = _get_latest_landslide_xml_url()
        if not xml_url:
            return result

        with urllib.request.urlopen(xml_url, timeout=10) as res:
            compressed_xml = res.read()
        xml_bytes = gzip.decompress(compressed_xml)
        root = ET.fromstring(xml_bytes)

        head = next(
            (element for element in root.iter()
             if _xml_local_name(element.tag) == 'Head'),
            root
        )
        body = next(
            (element for element in root.iter()
             if _xml_local_name(element.tag) == 'Body'),
            root
        )
        result["report_time"] = format_report_time(_xml_text(head, 'ReportDateTime'))
        result["headline"] = _xml_text(head, 'Headline')
        result["status"] = _xml_text(head, 'InfoKind') or _xml_text(body, 'Status')

        for area in body.iter():
            if _xml_local_name(area.tag) != 'Area':
                continue
            if _xml_text(area, 'Code') != LANDSLIDE_AREA_CODE:
                continue

            result["area_name"] = _xml_text(area, 'Name') or LANDSLIDE_AREA_NAME
            parent = next(
                (element for element in body.iter()
                 if area in list(element)),
                None
            )
            kind = next(
                (element for element in (list(parent) if parent is not None else [])
                 if _xml_local_name(element.tag) == 'Kind'),
                None
            )
            if kind is not None:
                result["kind"] = _xml_text(kind, 'Name')
                result["kind_code"] = _xml_text(kind, 'Code')
            result["is_warning"] = result["status"] in ('発表', '継続') or result["kind"] == '警戒'
            return result

        return result
    except (OSError, ET.ParseError, ValueError, urllib.error.URLError):
        return result


# トップページ：templates/index.html を返す（住民向け指示も表示する）
@app.route('/set_language', methods=['GET', 'POST'])
def set_language():
    language = request.values.get('lang', 'ja')
    if language in SUPPORTED_LANGUAGES:
        session['lang'] = language
    next_url = request.values.get('next') or request.referrer or url_for('index')
    if next_url and is_safe_url(next_url):
        return redirect(next_url)
    return redirect(url_for('index'))


@app.route('/')
def index():
    return render_template('index.html', instructions=home_board_instructions())


@app.route('/api/shelter_locations')
def shelter_locations():
    requested_ids = request.args.get('ids')
    selected_ids = set(requested_ids.split(',')) if requested_ids else None
    return jsonify(shelter_map_points(selected_ids))

# ログインページ
@app.route('/login', methods=['GET', 'POST'])
def login():
    # リダイレクト先を取得（デフォルトは避難所登録画面）
    next_url = request.args.get('next') or request.form.get('next')

    # 安全でないURLの場合はデフォルトページにリダイレクト
    if not next_url or not is_safe_url(next_url):
        next_url = url_for('shelter_register')

    if request.method == 'POST':
        password = request.form.get('password', '').strip()

        # 認証チェック
        username = next(
            (name for name, registered_password in ADMIN_CREDENTIALS.items()
             if registered_password == password),
            None
        )
        if username:
            session['logged_in'] = True
            session['username'] = username
            # ログイン成功後は指定されたページにリダイレクト
            return redirect(next_url)
        return render_template('login.html', error=True, message="パスワードが正しくありません。", next=next_url)

    # ログイン済みの場合は指定されたページにリダイレクト
    if session.get('logged_in'):
        return redirect(next_url)

    return render_template('login.html', next=next_url)

# ログアウト
@app.route('/logout')
def logout():
    current_lang = get_current_language()
    session.clear()
    session['lang'] = current_lang
    return redirect(url_for('index'))

# 避難所登録ページ
@app.route('/shelter_register', methods=['GET', 'POST'])
@login_required
def shelter_register():
    if request.method == 'POST':
        mode = request.form.get('mode')
        if mode == 'new':
            return redirect(url_for('shelter_form', mode='new'))
        if mode == 'edit':
            return redirect(url_for('shelter_edit_search'))
    return render_template('shelter_register.html', page='choice')


@app.route('/shelter_register/edit_search', methods=['GET', 'POST'])
@login_required
def shelter_edit_search():
    keyword = request.values.get('keyword', '').strip()
    current = current_shelters()
    results = [shelter for shelter in current if keyword in shelter.get('name', '')] if keyword else []
    return render_template('shelter_register.html', page='edit_search', keyword=keyword, results=results)


@app.route('/shelter_register/form/<mode>', methods=['GET', 'POST'])
@login_required
def shelter_form(mode):
    if mode not in ('new', 'edit'):
        return redirect(url_for('shelter_register'))

    shelter = {}
    if mode == 'edit':
        shelter_id = request.values.get('shelter_id', type=int)
        shelter = next((item for item in shelters if item.get('id') == shelter_id), None)
        if not shelter:
            return redirect(url_for('shelter_edit_search'))
        shelter = normalize_shelter(shelter)

    if request.method == 'POST':
        image_path = save_uploaded_map(request.files.get('map_image')) or shelter.get('map_image', '')
        data = shelter_form_data(request.form, image_path)
        error = validate_shelter_data(data)
        if not error and shelter_name_exists(data['name'], shelter.get('id')):
            error = f'「{data["name"]}」はすでに登録されています。'
        if error:
            return render_template('shelter_register.html', page='form', mode=mode, shelter={**shelter, **data}, error=error)
        data['id'] = shelter.get('id', '')
        return render_template('shelter_register.html', page='confirm', mode=mode, shelter=data)

    return render_template('shelter_register.html', page='form', mode=mode, shelter=shelter)


@app.route('/shelter_register/complete', methods=['POST'])
@login_required
def shelter_complete():
    mode = request.form.get('mode', 'new')
    data = shelter_form_data(request.form)
    error = validate_shelter_data(data)
    shelter_id = request.form.get('shelter_id', type=int)
    if not error and shelter_name_exists(data['name'], shelter_id if mode == 'edit' else None):
        error = f'「{data["name"]}」はすでに登録されています。'
    if error:
        return render_template('shelter_register.html', page='form', mode=mode, shelter=data, error=error)

    if mode == 'edit':
        target = next((item for item in shelters if item.get('id') == shelter_id), None)
        if not target:
            return redirect(url_for('shelter_edit_search'))
        target.update(data)
    else:
        data['id'] = max((shelter.get('id', 0) for shelter in shelters), default=0) + 1
        shelters.append(data)

    if not save_shelters():
        return render_template('shelter_register.html', page='confirm', mode=mode, shelter=data, error='避難所の保存に失敗しました。')
    return render_template('shelter_register.html', page='complete', mode=mode, shelter=data)


@app.route('/shelter_register/delete', methods=['POST'])
@login_required
def shelter_delete():
    shelter_id = request.form.get('shelter_id', type=int)
    target_index = next(
        (index for index, shelter in enumerate(shelters) if str(shelter.get('id')) == str(shelter_id)),
        None,
    )
    if target_index is None:
        return redirect(url_for('shelter_edit_search'))

    deleted_shelter = shelters.pop(target_index)
    if not save_shelters():
        shelters.insert(target_index, deleted_shelter)
        return render_template(
            'shelter_register.html',
            page='form',
            mode='edit',
            shelter=deleted_shelter,
            error='避難所の削除に失敗しました。',
        )
    return redirect(url_for('shelter_edit_search'))

# 避難所検索ページ
@app.route('/shelter_search')
def shelter_search():
    has_search = bool(request.args)
    if has_search:
        results, keyword, selected, district, municipality = search_shelters(request.args)
        return render_template(
            'search_results.html', results=results, keyword=keyword,
            selected_facilities=selected, facility_options=FACILITY_OPTIONS,
            selected_district=district, selected_municipality=municipality,
        )
    shelter_towns = sorted({shelter.get('district', '').strip() for shelter in shelters if shelter.get('district')})
    return render_template(
        'shelter_search.html',
        facility_options=FACILITY_OPTIONS,
        shelter_towns=shelter_towns,
    )

# 全施設一覧ページ
@app.route('/all_shelters')
def all_shelters():
    results = [normalize_shelter(shelter, index) for index, shelter in enumerate(current_shelters())]
    for item in results:
        item['_matched_facilities'] = 0
        item['_selected_facilities'] = []
    return render_template(
        'search_results.html', results=results, keyword='',
        selected_facilities=[], facility_options=FACILITY_OPTIONS,
    )


@app.route('/board')
def board():
    current = current_shelters()
    return render_board_page(
        current,
        error=request.args.get('error'),
    )


def render_board_page(current, error=None, form_data=None):
    shelter_towns = sorted({shelter.get('district', '').strip() for shelter in current if shelter.get('district')})
    return render_template(
        'board.html',
        instructions=board_instructions(),
        shelters=current,
        areas=['全域', *shelter_towns],
        error=error,
        form_data=form_data if form_data is not None else request.form,
        templates=(
            '今すぐ避難してください。',
            '周辺の安全を確認してください。',
            '不要不急の外出は控えてください。',
            '道路の通行止めや崩れがないか確認してください。',
            '避難先の状況を確認し、指示に従って行動してください。',
        ),
    )


@app.route('/board/create', methods=['POST'])
@login_required
def board_create():
    current = current_shelters()
    translation_fields = {
        'ja': request.form.get('content', '').strip(),
        'en': request.form.get('content_en', '').strip(),
        'zh': request.form.get('content_zh', '').strip(),
        'ko': request.form.get('content_ko', '').strip(),
    }
    areas = request.form.getlist('areas')
    available_areas = {shelter.get('district', '').strip() for shelter in current if shelter.get('district')}
    selected_areas = [area for area in areas if area in ('全域', '青森市全域') or area in available_areas]
    if '全域' in selected_areas or '青森市全域' in selected_areas:
        selected_areas = ['全域']
    if request.form.get('input_mode') == 'template':
        content = request.form.get('template_content', '').strip()
        urgency = '高' if content == '今すぐ避難してください。' else '中'
        translations = {}
    else:
        content = translation_fields['ja'] or translation_fields['en'] or translation_fields['zh'] or translation_fields['ko']
        urgency = request.form.get('urgency', '低')
        translations = {lang: text for lang, text in translation_fields.items() if text}
    if urgency not in ('高', '中', '低'):
        urgency = '低'
    if not content:
        return render_board_page(current, error='content', form_data=request.form)
    if not selected_areas:
        return render_board_page(current, error='area', form_data=request.form)

    selected_shelter_names = [
        name for name in request.form.getlist('shelters')
        if any(
            shelter.get('name') == name and any(shelter_matches_area(shelter, area) for area in selected_areas)
            for shelter in current
        )
    ]

    now = current_instruction_time()
    instructions.insert(0, {
        'id': max((item.get('id', 0) for item in instructions), default=0) + 1,
        'target': '住民',
        'content': content,
        'area': '、'.join(selected_areas),
        'shelters': selected_shelter_names,
        'status': '発信中',
        'resolved_at': None,
        'created_at': now,
        'updated_at': now,
        'urgency': urgency,
        'translations': translations,
    })
    save_instructions()
    return redirect(url_for('board'))


@app.route('/board/resolve', methods=['POST'])
@login_required
def board_resolve():
    selected_ids = selected_instruction_ids(request.form)
    now = current_instruction_time()
    for instruction in instructions:
        if str(instruction.get('id')) in selected_ids:
            instruction['status'] = '解除済'
            instruction['resolved_at'] = now
            instruction['updated_at'] = now
    save_instructions()
    return redirect(url_for('board'))


@app.route('/board/delete', methods=['POST'])
@login_required
def board_delete():
    selected_ids = selected_instruction_ids(request.form)
    instructions[:] = [instruction for instruction in instructions
                       if str(instruction.get('id')) not in selected_ids]
    save_instructions()
    return redirect(url_for('board'))

# 検索結果ページ：templates/search_results.html を返す
@app.route('/search_results')
def search_results():
    results, keyword, selected, district, municipality = search_shelters(request.args)
    return render_template(
        'search_results.html', results=results, keyword=keyword,
        selected_facilities=selected, facility_options=FACILITY_OPTIONS,
        selected_district=district, selected_municipality=municipality,
    )

# JSON API：/shelters?district=地区名
@app.route('/shelters', methods=['GET'])
def get_shelters():
    results = filter_shelters(request.args.get('district'))

    if not results:
        # 見つからなければエラー JSON を返す
        return jsonify({'error': 'No shelters found'}), 404

    # 見つかったらリストを JSON で返す
    return jsonify(results)

# 気象警報・注意報API
@app.route('/api/weather_warnings')
def api_weather_warnings():
    """気象警報・注意報をJSON形式で返すAPI"""
    return jsonify(get_weather_warnings())

if __name__ == '__main__':
    app.run(debug=True, port=5000)
