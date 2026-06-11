"""
miri_keywords.py
────────────────
라즈베리파이 서버에서 매일 낮 12시에 실행되는 키워드 수집 스크립트.

수집 내용:
  ① 스테디셀러 3개 — 계절/월별 수요가 높은 키워드
  ② 요즘 핫한 키워드 3개 — Google 트렌드 / SNS 트렌드 기반
  ③ 미리캔버스 판매 TOP 키워드 3개 — 미리캔버스 사이트 스크래핑

결과물:
  - data/keywords.json 파일 생성 (GitHub Pages index.html 이 읽음)

실행 방법:
  1) 수동: python3 miri_keywords.py
  2) 자동 (cron): crontab -e 에 아래 추가
     0 12 * * * /usr/bin/python3 /home/pi/miri_creator/miri_keywords.py >> /home/pi/miri_creator/logs/run.log 2>&1

필요 패키지 설치:
  pip3 install requests beautifulsoup4 google-genai
"""

import os, json, re, time, datetime, logging, pathlib
import requests
from bs4 import BeautifulSoup
from google import genai

# ── 설정 ──────────────────────────────────────────
BASE_DIR    = pathlib.Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "data"
OUTPUT_FILE = OUTPUT_DIR / "keywords.json"
LOG_DIR     = BASE_DIR / "logs"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDgArz43B7euy6WFU7l53C51ZFzjfC8rdQ")
GEMINI_MODEL   = "gemini-2.0-flash"

PROXIES = None

# ── 로깅 설정 ─────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def gemini_ask(prompt: str) -> str:
    """Gemini API 호출 공통 함수 (새 SDK)"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return resp.text.strip()


def parse_json_response(text: str) -> list:
    """Gemini 응답에서 JSON 파싱"""
    text = re.sub(r"^```json\s*|^```\s*|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


# ═══════════════════════════════════════════════════
# 1. 계절 / 월 판단
# ═══════════════════════════════════════════════════
def get_season_context() -> dict:
    now = datetime.datetime.now()
    m = now.month
    if   m in (3, 4, 5):  season = "봄";   emoji = "🌸"
    elif m in (6, 7, 8):  season = "여름"; emoji = "☀️"
    elif m in (9, 10, 11):season = "가을"; emoji = "🍂"
    else:                  season = "겨울"; emoji = "❄️"
    return {"month": m, "season": season, "emoji": emoji, "year": now.year}


# ═══════════════════════════════════════════════════
# 2. 스테디셀러 키워드 (Gemini AI 기반 계절 추천)
# ═══════════════════════════════════════════════════
def get_steady_keywords(season_ctx: dict) -> list[dict]:
    log.info("📌 스테디셀러 키워드 생성 중...")

    prompt = f"""
당신은 한국 디자인 플랫폼 '미리캔버스'에서 PNG 일러스트 스티커를 판매하는 전문가입니다.
지금은 {season_ctx['year']}년 {season_ctx['month']}월 ({season_ctx['season']} 시즌)입니다.

이 계절에 미리캔버스에서 꾸준히 잘 팔리는 일러스트 이미지 키워드 3개를 추천해주세요.

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어)",
    "prompt": "Gemini 이미지 생성 프롬프트 (영어, 2D flat illustration, white background 형식)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

프롬프트 규칙:
- 반드시 2D flat illustration style 명시
- White background, clean outlines 포함
- no floor, no shadow, no ground element 포함
- 귀엽고 밝은 색상, 심플한 디자인

해시태그 규칙:
- 10개 이하, 한국어 7개 + 영어 3개 조합
- 미리캔버스 검색에 최적화
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        for it in items:
            it["type"] = "steady"
        log.info(f"  ✅ 스테디셀러 {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 스테디셀러 생성 실패: {e}")
        return _fallback_steady(season_ctx)


# ═══════════════════════════════════════════════════
# 3. 요즘 핫한 키워드 (Google Trends RSS)
# ═══════════════════════════════════════════════════
def get_hot_keywords() -> list[dict]:
    log.info("🔥 핫 키워드 수집 중...")
    raw_trends = []

    try:
        url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=KR"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; MiriCreatorBot/1.0)"}
        res = requests.get(url, headers=headers, timeout=10, proxies=PROXIES)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all("item")[:15]
        for it in items:
            title = it.find("title")
            traffic = it.find("ht:approx_traffic")
            if title:
                raw_trends.append({
                    "keyword": title.text.strip(),
                    "traffic": traffic.text.strip() if traffic else "?"
                })
        log.info(f"  Google Trends 수집: {len(raw_trends)}개")
    except Exception as e:
        log.warning(f"  Google Trends 수집 실패: {e}")

    return _generate_hot_with_gemini(raw_trends)


def _generate_hot_with_gemini(raw_trends: list) -> list[dict]:
    trends_text = "\n".join([f"- {t['keyword']} ({t.get('traffic','?')} 검색)" for t in raw_trends[:15]])
    if not trends_text:
        trends_text = "- 소금빵\n- 감성캠핑\n- 레트로 디자인"

    prompt = f"""
한국의 요즘 인기 검색어 목록입니다:
{trends_text}

이 중에서 미리캔버스 PNG 일러스트 스티커로 만들기 적합한 키워드 3개를 골라주세요.
(추상적/정치적/인물명 키워드는 제외, 사물/음식/캐릭터/자연 등 시각화 가능한 것 우선)

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어)",
    "prompt": "Gemini 이미지 생성 프롬프트 (영어, 2D flat illustration, white background 형식)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

프롬프트 규칙:
- 반드시 2D flat illustration style 명시
- White background, clean outlines 포함
- no floor, no shadow, no ground element 포함
- 귀엽고 밝은 색상
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        for it in items:
            it["type"] = "hot"
        log.info(f"  ✅ 핫 키워드 {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 핫 키워드 생성 실패: {e}")
        return _fallback_hot()


# ═══════════════════════════════════════════════════
# 4. 미리캔버스 판매 TOP 키워드 (스크래핑)
# ═══════════════════════════════════════════════════
def get_miri_top_keywords() -> list[dict]:
    log.info("🏆 미리캔버스 TOP 키워드 수집 중...")
    raw_keywords = []

    try:
        url = "https://www.miricanvas.com/explore/elements"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.miricanvas.com/"
        }
        res = requests.get(url, headers=headers, timeout=15, proxies=PROXIES)
        soup = BeautifulSoup(res.text, "html.parser")

        selectors = [
            "button.tag__text", ".keyword-chip", ".trending-tag",
            "a[data-tracking='popular_keyword']", ".popular-keyword-item",
            "[class*='keyword'] span", "[class*='tag'] span",
        ]
        for sel in selectors:
            tags = soup.select(sel)
            if tags:
                raw_keywords = [t.get_text(strip=True) for t in tags[:20] if t.get_text(strip=True)]
                if raw_keywords:
                    log.info(f"  셀렉터 '{sel}'로 {len(raw_keywords)}개 추출")
                    break

        if not raw_keywords:
            for el in soup.find_all(["button", "a", "span"]):
                t = el.get_text(strip=True)
                if 1 < len(t) <= 10 and re.search(r"[가-힣]", t):
                    raw_keywords.append(t)
            raw_keywords = list(dict.fromkeys(raw_keywords))[:20]

        log.info(f"  미리캔버스 후보 키워드: {raw_keywords[:5]}...")

    except Exception as e:
        log.warning(f"  미리캔버스 스크래핑 실패: {e}")

    return _generate_miri_with_gemini(raw_keywords)


def _generate_miri_with_gemini(raw_keywords: list) -> list[dict]:
    kw_text = ", ".join(raw_keywords[:20]) if raw_keywords else "수박, 바다, 여름, 꽃, 아이스크림"

    prompt = f"""
미리캔버스 사이트에서 수집된 인기 키워드 후보입니다:
{kw_text}

이 중에서 PNG 일러스트 스티커로 만들기 가장 좋은 상위 3개 키워드를 골라주세요.
(판매 가능성, 시각화 적합성, 중복 없이 다양성 있게 선택)

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어)",
    "prompt": "Gemini 이미지 생성 프롬프트 (영어, 2D flat illustration, white background 형식)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        for it in items:
            it["type"] = "miri"
        log.info(f"  ✅ 미리 TOP {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 미리 TOP 생성 실패: {e}")
        return _fallback_miri()


# ═══════════════════════════════════════════════════
# 5. JSON 저장
# ═══════════════════════════════════════════════════
def save_json(items: list) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    next_update = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if next_update <= now:
        next_update += datetime.timedelta(days=1)

    payload = {
        "updatedAt":    now.isoformat(),
        "nextUpdateAt": next_update.isoformat(),
        "items":        items,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info(f"💾 저장 완료: {OUTPUT_FILE}  ({len(items)}개 항목)")


# ═══════════════════════════════════════════════════
# 6. Git Push (선택)
# ═══════════════════════════════════════════════════
def git_push() -> None:
    import subprocess
    try:
        subprocess.run(["git", "-C", str(BASE_DIR), "add", "data/keywords.json"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "commit", "-m",
                        f"auto: update keywords {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "push"], check=True)
        log.info("🚀 GitHub push 완료!")
    except Exception as e:
        log.warning(f"  Git push 실패 (수동 push 필요): {e}")


# ═══════════════════════════════════════════════════
# Fallback 데이터
# ═══════════════════════════════════════════════════
def _fallback_steady(ctx: dict) -> list[dict]:
    season = ctx["season"]
    defaults = {
        "봄":  [("봄꽃", "Spring flowers bouquet with pink cherry blossoms and tulips. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "봄꽃, 벚꽃, 튤립, 봄, 꽃다발, 화사한, 일러스트, spring flower, cherry blossom, floral"),
                ("입학", "Happy child holding flowers on first day of school. 2D flat illustration, white background, clean outlines, no floor, no shadow, cute kawaii style.", "입학, 학교, 어린이, 봄, 유치원, 초등학교, 일러스트, entrance ceremony, school, child"),
                ("딸기", "Fresh red strawberry with green leaves, plump and shiny. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "딸기, 과일, 봄과일, 빨강, 달콤, 일러스트, strawberry, spring fruit, red berry")],
        "여름": [("수박", "Sliced watermelon, juicy red inside with black seeds. 2D flat illustration, white background, clean outlines, no floor, no shadow, vibrant colors.", "수박, 여름과일, 과일, 여름, 달콤, 빨강, 초록, 일러스트, watermelon, summer fruit"),
                 ("해바라기", "Bright yellow sunflower in full bloom. 2D flat illustration, white background, clean outlines, no floor, no shadow, cheerful and bold.", "해바라기, 꽃, 여름꽃, 노랑, 식물, 일러스트, 밝은, sunflower, yellow flower, summer"),
                 ("아이스크림", "Colorful ice cream cone with two scoops, pastel colors. 2D flat illustration, white background, clean outlines, no floor, no shadow, cute kawaii style.", "아이스크림, 여름, 디저트, 달콤, 콘, 귀여운, 파스텔, 일러스트, ice cream, summer dessert")],
        "가을": [("단풍", "Colorful autumn maple leaves, red and orange tones. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "단풍, 가을, 낙엽, 빨강, 주황, 노랑, 나뭇잎, 일러스트, autumn leaf, maple"),
                 ("감", "Ripe orange persimmon fruit with green stem. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "감, 가을과일, 주황, 과일, 추석, 달콤, 일러스트, persimmon, autumn fruit, orange"),
                 ("코스모스", "Pink cosmos flowers in gentle arrangement. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "코스모스, 꽃, 가을꽃, 분홍, 야생화, 일러스트, cosmos, pink flower, autumn")],
        "겨울": [("눈사람", "Cheerful snowman with scarf and hat, cute and round. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "눈사람, 겨울, 눈, 귀여운, 크리스마스, 스카프, 일러스트, snowman, winter, cute"),
                 ("크리스마스트리", "Decorated Christmas tree with colorful ornaments and star on top. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "크리스마스, 트리, 산타, 겨울, 선물, 별, 일러스트, Christmas tree, holiday, xmas"),
                 ("귤", "Fresh tangerine/mandarin with green leaf. 2D flat illustration, white background, clean outlines, no floor, no shadow.", "귤, 겨울과일, 주황, 과일, 달콤, 일러스트, tangerine, mandarin, winter fruit")],
    }
    items = []
    for i, (kw, pt, ht) in enumerate(defaults.get(season, defaults["여름"])):
        items.append({"rank": i+1, "keyword": kw, "prompt": pt, "hashtags": ht, "type": "steady"})
    return items

def _fallback_hot() -> list[dict]:
    return [
        {"rank":1,"keyword":"소금빵","prompt":"Golden buttery salt bread, freshly baked and glossy. 2D flat illustration, white background, clean outlines, no floor, no shadow, warm tones.","hashtags":"소금빵, 빵, 베이커리, 카페, 맛있는, 디저트, 일러스트, salt bread, bakery, butter bread","type":"hot"},
        {"rank":2,"keyword":"감성 캠핑","prompt":"Cozy camping lantern glowing softly, minimalist aesthetic. 2D flat illustration, white background, clean outlines, no floor, no shadow, warm earthy tones.","hashtags":"캠핑, 랜턴, 감성캠핑, 아웃도어, 자연, 여름캠핑, 일러스트, camping lantern, outdoor, hygge","type":"hot"},
        {"rank":3,"keyword":"레트로 아이스크림","prompt":"Retro-style ice cream bar on stick with pastel colors and vintage pattern. 2D flat illustration, white background, clean outlines, no floor, no shadow.","hashtags":"아이스크림, 레트로, 여름, 복고, 디저트, 달콤, 파스텔, 일러스트, retro ice cream, vintage summer","type":"hot"},
    ]

def _fallback_miri() -> list[dict]:
    return [
        {"rank":1,"keyword":"바다 파도","prompt":"Cute stylized ocean wave with foam and sparkles. 2D flat illustration, white background, clean outlines, no floor, no shadow, fresh blue tones.","hashtags":"바다, 파도, 여름, 파란색, 시원한, 해양, 스티커, 일러스트, ocean wave, summer sea","type":"miri"},
        {"rank":2,"keyword":"열대 식물","prompt":"Tropical monstera leaf and palm elements, lush green. 2D flat illustration, white background, clean outlines, no floor, no shadow, vibrant tropical colors.","hashtags":"열대식물, 몬스테라, 야자수, 초록, 식물, 여름, 일러스트, tropical plant, monstera, palm","type":"miri"},
        {"rank":3,"keyword":"여름 음료","prompt":"Refreshing iced drink with lemon slice and colorful straw, condensation on glass. 2D flat illustration, white background, clean outlines, no floor, no shadow.","hashtags":"음료, 여름음료, 아이스티, 레몬에이드, 시원한, 카페, 여름, 일러스트, summer drink, iced beverage","type":"miri"},
    ]


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════
def run():
    log.info("=" * 50)
    log.info(f"🚀 Miri Creator 키워드 수집 시작")
    log.info(f"   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    season_ctx = get_season_context()
    log.info(f"🌍 현재 시즌: {season_ctx['season']} ({season_ctx['month']}월) {season_ctx['emoji']}")

    all_items = []

    steady = get_steady_keywords(season_ctx)
    all_items.extend(steady)
    time.sleep(2)

    hot = get_hot_keywords()
    all_items.extend(hot)
    time.sleep(2)

    miri = get_miri_top_keywords()
    all_items.extend(miri)

    log.info(f"\n📊 수집 결과: 스테디 {len(steady)}개 / 핫 {len(hot)}개 / 미리TOP {len(miri)}개")
    log.info(f"   총 {len(all_items)}개 항목\n")

    save_json(all_items)

    git_push()  # ← 자동 push 원하면 주석 해제

    log.info("✅ 완료!\n")


if __name__ == "__main__":
    run()
