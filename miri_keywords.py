"""
miri_keywords.py v2
────────────────────
변경사항:
  - 저작권 있는 특정 인물/캐릭터 키워드 제외 필터 추가
  - 배경색 white → 크로마키 그린 (#00B140) 으로 변경
  - fallback 데이터를 클로드 추천 프롬프트 리스트 기반으로 교체
  - JSON 저장 완료 메시지 명확화 (git push 오류와 구분)
  - 계절별 스테디셀러 프롬프트 강화

실행:
  python3 miri_keywords.py

cron (매일 12시):
  0 12 * * * cd /home/ubuntu/Desktop/miri_creator && python3 miri_keywords.py >> logs/cron.log 2>&1

필요 패키지:
  pip3 install requests beautifulsoup4 google-genai python-dotenv
"""

import os, json, re, time, datetime, logging, pathlib
import requests
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv
load_dotenv()

# ── 설정 ──────────────────────────────────────────
BASE_DIR    = pathlib.Path(__file__).parent
OUTPUT_DIR  = BASE_DIR / "data"
OUTPUT_FILE = OUTPUT_DIR / "keywords.json"
LOG_DIR     = BASE_DIR / "logs"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
GEMINI_MODEL   = "gemini-2.5-flash-lite"

# 크로마키 그린 배경 (배경 제거 툴에서 매직완드로 제거하기 쉬운 색)
BG_COLOR = "chroma key green background, hex color #00B140, 1:1 square aspect ratio"

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

# ── 저작권 필터 안내문 (모든 프롬프트에 공통 삽입) ──
COPYRIGHT_FILTER = """
⚠️ 저작권 주의사항 (반드시 지킬 것):
- 특정 실존 인물 이름 절대 사용 금지 (예: 손흥민, 아이유, 방탄소년단 등)
- 저작권 있는 특정 캐릭터 절대 사용 금지 (예: 미키마우스, 피카츄, 도라에몽 등)
- 대신 일반적 묘사 사용:
  - 특정 인물 → "뛰어노는 어린이", "축구하는 남자아이" 등 일반 묘사
  - 특정 캐릭터 → "둥근 귀의 작은 생쥐", "노란 전기 동물" 등 일반 묘사
"""


def gemini_ask(prompt: str) -> str:
    """Gemini API 호출 공통 함수"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return resp.text.strip()


def parse_json_response(text: str) -> list:
    """Gemini 응답에서 JSON 파싱 (마크다운 펜스 제거)"""
    text = re.sub(r"^```json\s*|^```\s*|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


# ═══════════════════════════════════════════════════
# 1. 계절 판단
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
# 2. Google Trends 수집 (②③ 공유)
# ═══════════════════════════════════════════════════
def fetch_google_trends(limit: int = 20) -> list[dict]:
    """Google Trends 한국 일간 트렌드 RSS 수집"""
    try:
        url = "https://trends.google.com/trending/rss?geo=KR"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; MiriCreatorBot/1.0)"}
        res = requests.get(url, headers=headers, timeout=10, proxies=PROXIES)
        soup = BeautifulSoup(res.content, "xml")
        items = soup.find_all("item")[:limit]
        trends = []
        for it in items:
            title = it.find("title")
            traffic = it.find("ht:approx_traffic")
            if title:
                trends.append({
                    "keyword": title.text.strip(),
                    "traffic": traffic.text.strip() if traffic else "?"
                })
        log.info(f"  Google Trends 수집: {len(trends)}개")
        return trends
    except Exception as e:
        log.warning(f"  Google Trends 수집 실패: {e}")
        return []


# ═══════════════════════════════════════════════════
# 3. 스테디셀러 키워드 (Gemini + 계절 + 한국 이벤트)
# ═══════════════════════════════════════════════════
def get_steady_keywords(season_ctx: dict) -> list[dict]:
    """계절/한국 이벤트 기반 스테디셀러 키워드 3개 생성"""
    log.info("📌 스테디셀러 키워드 생성 중...")

    m = season_ctx["month"]

    # 월별 힌트 (클로드 추천 리스트 기반)
    monthly_hint = {
        1:  "새해, 설날, 새해 카운트다운, 연하장",
        2:  "발렌타인데이, 겨울 감성, 눈꽃",
        3:  "입학식, 새학기, 봄 시작, 벚꽃, 유치원/초등학교",
        4:  "봄 결혼식, 웨딩 일러스트, 청첩장, 벚꽃",
        5:  "어린이날, 어버이날, 스승의날, 가정의달",
        6:  "우산, 수국, 장마, 현충일",
        7:  "여름방학, 해변, 수박, 아이스크림, 수영",
        8:  "여름방학, 피서, 해변, 열대과일, 선풍기",
        9:  "추석, 송편, 보름달, 가을 정취, 코스모스",
        10: "할로윈, 단풍, 가을 감성, 고구마",
        11: "단풍, 낙엽, 가을 끝, 겨울 준비",
        12: "크리스마스, 연말, 새해 카운트다운, 산타",
    }.get(m, "계절 감성")

    prompt = f"""
당신은 한국 디자인 플랫폼 '미리캔버스'에서 PNG 일러스트 스티커를 판매하는 전문가입니다.
지금은 {season_ctx['year']}년 {season_ctx['month']}월 ({season_ctx['season']} 시즌)입니다.

이달의 주요 테마: {monthly_hint}

위 테마를 참고해서 이 시기에 미리캔버스에서 꾸준히 잘 팔리는 일러스트 키워드 3개를 추천해주세요.

{COPYRIGHT_FILTER}

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어)",
    "prompt": "이미지 생성 프롬프트 (영어, 2D flat illustration, {BG_COLOR} 형식)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

이미지 프롬프트 규칙:
- 2D flat illustration style 명시
- {BG_COLOR} 포함
- clean black outlines on all subjects 포함
- no floor, no shadow, no ground element 포함
- 귀엽고 밝은 색상, 심플한 디자인
- 저작권 있는 특정 인물/캐릭터 절대 사용 금지

해시태그 규칙:
- 10개 이하, 한국어 7개 + 영어 3개 조합
- 미리캔버스 검색 최적화 (프레임, 배너, 섬네일 등 플랫폼 키워드 활용)
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
# 4. 핫 키워드 (Google Trends → Gemini 선별)
# ═══════════════════════════════════════════════════
def get_hot_keywords(trends: list[dict]) -> list[dict]:
    """Google Trends 실시간 데이터에서 핫 키워드 3개 선별"""
    log.info("🔥 핫 키워드 생성 중...")

    trends_text = "\n".join([f"- {t['keyword']} ({t.get('traffic','?')} 검색)" for t in trends[:15]])
    if not trends_text:
        trends_text = "- 소금빵\n- 감성캠핑\n- 레트로 디자인"

    prompt = f"""
한국의 요즘 인기 검색어 목록입니다:
{trends_text}

{COPYRIGHT_FILTER}

이 중에서 미리캔버스 PNG 일러스트 스티커로 만들기 적합한 키워드 3개를 골라주세요.
(추상적/정치적 키워드 제외, 사물/음식/자연 등 시각화 가능한 것 우선)
(특정 인물명/캐릭터명이 트렌드에 있어도 반드시 제외)

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어)",
    "prompt": "이미지 생성 프롬프트 (영어, 2D flat illustration, {BG_COLOR} 형식)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

이미지 프롬프트 규칙:
- 2D flat illustration style 명시
- {BG_COLOR} 포함
- clean black outlines on all subjects 포함
- no floor, no shadow, no ground element 포함
- 귀엽고 밝은 색상
- 저작권 있는 특정 인물/캐릭터 절대 사용 금지
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
# 5. 트렌드 TOP (Google Trends → Gemini, 중복 제외)
# ═══════════════════════════════════════════════════
def get_miri_top_keywords(trends: list[dict], hot_keywords: list[dict]) -> list[dict]:
    """Google Trends에서 핫 키워드와 중복 없는 TOP 3 선별"""
    log.info("🏆 트렌드 TOP 키워드 생성 중...")

    hot_kw_names = [it.get("keyword", "") for it in hot_keywords]
    trends_text = "\n".join([f"- {t['keyword']} ({t.get('traffic','?')} 검색)" for t in trends[:20]])
    if not trends_text:
        trends_text = "- 수박\n- 바다\n- 아이스크림"

    already_picked = ", ".join(hot_kw_names) if hot_kw_names else "없음"

    prompt = f"""
한국 구글 트렌드 인기 검색어입니다:
{trends_text}

이미 선택된 키워드 (중복 제외 필수): {already_picked}

{COPYRIGHT_FILTER}

위 목록에서 미리캔버스 PNG 일러스트 스티커로 만들기 좋은 키워드 3개를 골라주세요.
- 이미 선택된 키워드와 절대 겹치지 않게 선택
- 특정 인물명/캐릭터명 제외
- 목록에 적합한 것이 부족하면 계절감 있는 일반 키워드로 자유롭게 채우기

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어)",
    "prompt": "이미지 생성 프롬프트 (영어, 2D flat illustration, {BG_COLOR} 형식)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

이미지 프롬프트 규칙:
- 2D flat illustration style 명시
- {BG_COLOR} 포함
- clean black outlines on all subjects 포함
- no floor, no shadow, no ground element 포함
- 귀엽고 밝은 색상
- 저작권 있는 특정 인물/캐릭터 절대 사용 금지
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        for it in items:
            it["type"] = "miri"
        log.info(f"  ✅ 트렌드 TOP {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 트렌드 TOP 생성 실패: {e}")
        return _fallback_miri()


# ═══════════════════════════════════════════════════
# 6. JSON 저장
# ═══════════════════════════════════════════════════
def save_json(items: list) -> None:
    """keywords.json 저장 후 명확한 완료 메시지 출력"""
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

    # git push 오류와 구분되도록 명확한 완료 메시지
    log.info("─" * 50)
    log.info(f"✅ JSON 저장 완료!")
    log.info(f"   파일: {OUTPUT_FILE}")
    log.info(f"   항목: {len(items)}개")
    log.info(f"   갱신: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"   다음: {next_update.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("─" * 50)


# ═══════════════════════════════════════════════════
# 7. Git Push (선택)
# ═══════════════════════════════════════════════════
def git_push() -> None:
    import subprocess
    log.info("📤 GitHub push 시도 중...")
    try:
        subprocess.run(["git", "-C", str(BASE_DIR), "add", "data/keywords.json"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "commit", "-m",
                        f"auto: update keywords {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "stash"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "pull", "--rebase", "origin", "main"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "stash", "pop"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "push"], check=True)
        log.info("🚀 GitHub push 완료!")
    except Exception as e:
        log.warning(f"⚠️  Git push 실패 (JSON 저장은 완료됨): {e}")


# ═══════════════════════════════════════════════════
# Fallback 데이터 (클로드 추천 프롬프트 리스트 기반)
# ═══════════════════════════════════════════════════

# 크로마키 배경 공통 suffix
_BG = f"{BG_COLOR}, clean black outlines on all subjects, no floor, no shadow, no ground element"

def _fallback_steady(ctx: dict) -> list[dict]:
    """Gemini 실패 시 월별 하드코딩 기본값 (클로드 추천 리스트 기반)"""
    m = ctx["month"]
    defaults = {
        1: [  # 새해/설날
            ("새해 풍경", f"New Year decorations with golden bell and star confetti. 2D flat illustration, {_BG}.", "새해, 설날, 연하장, 새해복, 황금, 별, 일러스트, New Year, celebration, confetti"),
            ("설날 한복", f"Traditional Korean hanbok outfit in festive colors, cute chibi style. 2D flat illustration, {_BG}.", "설날, 한복, 전통, 명절, 귀여운, 한국, 일러스트, Hanbok, Korean traditional, holiday"),
            ("복주머니", f"Traditional Korean lucky money pouch in red and gold. 2D flat illustration, {_BG}.", "복주머니, 세뱃돈, 설날, 행운, 빨강, 황금, 일러스트, lucky pouch, Korean New Year, fortune"),
        ],
        2: [  # 발렌타인
            ("하트 초콜릿", f"Heart-shaped chocolate box with ribbon. 2D flat illustration, {_BG}.", "초콜릿, 발렌타인, 하트, 선물, 달콤, 사랑, 일러스트, chocolate, Valentine, heart"),
            ("겨울 눈꽃", f"Delicate snowflake crystal pattern. 2D flat illustration, {_BG}.", "눈꽃, 겨울, 결정, 하얀, 크리스탈, 일러스트, snowflake, winter, crystal"),
            ("따뜻한 코코아", f"Steaming hot cocoa mug with marshmallows. 2D flat illustration, {_BG}.", "코코아, 겨울음료, 마시멜로, 따뜻한, 머그컵, 일러스트, hot cocoa, winter drink, cozy"),
        ],
        3: [  # 입학/봄
            ("입학 꽃다발", f"Colorful flower bouquet for school entrance ceremony, cheerful and bright. 2D flat illustration, {_BG}.", "입학, 꽃다발, 새학기, 봄, 화사한, 학교, 일러스트, school entrance, bouquet, spring"),
            ("벚꽃", f"Pink cherry blossom branch with petals falling. 2D flat illustration, {_BG}.", "벚꽃, 봄, 분홍, 꽃잎, 나뭇가지, 화사한, 일러스트, cherry blossom, spring, pink"),
            ("책가방", f"Cute colorful school backpack with stationery. 2D flat illustration, {_BG}.", "책가방, 새학기, 학교, 귀여운, 문구, 입학, 일러스트, school bag, backpack, stationery"),
        ],
        4: [  # 봄/웨딩
            ("웨딩 부케", f"Elegant wedding bouquet with white roses and ribbons. 2D flat illustration, {_BG}.", "웨딩, 부케, 결혼, 장미, 흰색, 청첩장, 일러스트, wedding bouquet, bridal, roses"),
            ("봄꽃 화환", f"Spring flower wreath with tulips and daisies. 2D flat illustration, {_BG}.", "봄꽃, 화환, 튤립, 데이지, 봄, 꽃, 일러스트, spring wreath, flower, tulip"),
            ("나비", f"Colorful butterfly with detailed wing pattern. 2D flat illustration, {_BG}.", "나비, 봄, 날개, 화사한, 곤충, 자연, 일러스트, butterfly, spring, colorful wings"),
        ],
        5: [  # 가정의달
            ("어린이날 풍선", f"Colorful balloons and confetti for children's day celebration. 2D flat illustration, {_BG}.", "어린이날, 풍선, 색종이, 파티, 축하, 오월, 일러스트, Children's Day, balloon, celebration"),
            ("카네이션", f"Red and pink carnation flower for parents' day. 2D flat illustration, {_BG}.", "카네이션, 어버이날, 스승의날, 감사, 빨강, 분홍, 일러스트, carnation, Parents Day, gratitude"),
            ("가족 피크닉 소품", f"Picnic basket with checkered blanket and fruits. 2D flat illustration, {_BG}.", "피크닉, 가족, 나들이, 바구니, 봄, 소풍, 일러스트, picnic, family, basket"),
        ],
        6: [  # 장마/우산
            ("우산", f"Colorful rain umbrella with raindrops. 2D flat illustration, {_BG}.", "우산, 장마, 비, 여름, 색깔, 빗방울, 일러스트, umbrella, rainy season, colorful"),
            ("수국", f"Blue and purple hydrangea flower cluster. 2D flat illustration, {_BG}.", "수국, 꽃, 파랑, 보라, 장마, 여름꽃, 일러스트, hydrangea, flower, purple blue"),
            ("개구리", f"Cute green frog sitting on lily pad in rain. 2D flat illustration, {_BG}.", "개구리, 장마, 비, 귀여운, 초록, 연잎, 일러스트, frog, rain, cute green"),
        ],
        7: [  # 여름방학
            ("수박", f"Fresh sliced watermelon with seeds, vibrant red and green. 2D flat illustration, {_BG}.", "수박, 여름, 과일, 빨강, 초록, 시원한, 일러스트, watermelon, summer fruit, fresh"),
            ("아이스크림", f"Colorful ice cream cone with double scoop. 2D flat illustration, {_BG}.", "아이스크림, 여름, 콘, 달콤, 디저트, 파스텔, 일러스트, ice cream, summer, sweet"),
            ("해바라기", f"Bright yellow sunflower in full bloom. 2D flat illustration, {_BG}.", "해바라기, 꽃, 노랑, 여름꽃, 밝은, 식물, 일러스트, sunflower, yellow, summer flower"),
        ],
        8: [  # 여름 피서
            ("파도", f"Cute stylized ocean wave with foam and sparkles. 2D flat illustration, {_BG}.", "파도, 바다, 여름, 파란색, 시원한, 해양, 일러스트, wave, ocean, summer sea"),
            ("튜브", f"Colorful inflatable swimming ring/tube. 2D flat illustration, {_BG}.", "튜브, 수영, 여름, 바다, 수영장, 파스텔, 일러스트, swim ring, summer, pool"),
            ("열대과일", f"Tropical fruits collection: mango, pineapple, coconut. 2D flat illustration, {_BG}.", "열대과일, 망고, 파인애플, 코코넛, 여름, 과일, 일러스트, tropical fruit, mango, pineapple"),
        ],
        9: [  # 추석
            ("송편", f"Traditional Korean rice cake songpyeon in various colors. 2D flat illustration, {_BG}.", "송편, 추석, 명절, 한국, 전통음식, 오색, 일러스트, songpyeon, Chuseok, Korean rice cake"),
            ("보름달", f"Round full moon with soft golden glow and rabbit silhouette. 2D flat illustration, {_BG}.", "보름달, 추석, 달, 토끼, 황금, 가을, 일러스트, full moon, Chuseok, harvest moon"),
            ("단풍", f"Colorful autumn maple leaves in red and orange. 2D flat illustration, {_BG}.", "단풍, 가을, 빨강, 주황, 낙엽, 나뭇잎, 일러스트, autumn leaf, maple, fall colors"),
        ],
        10: [  # 할로윈
            ("호박 랜턴", f"Jack-o-lantern pumpkin with carved face and candle glow. 2D flat illustration, {_BG}.", "할로윈, 호박, 랜턴, 주황, 유령, 무서운, 일러스트, Halloween, pumpkin, jack-o-lantern"),
            ("단풍나무", f"Autumn maple tree with colorful red and orange leaves. 2D flat illustration, {_BG}.", "단풍, 나무, 가을, 빨강, 주황, 노랑, 일러스트, maple tree, autumn, fall"),
            ("도토리", f"Cute acorn with cap, autumn forest element. 2D flat illustration, {_BG}.", "도토리, 가을, 귀여운, 숲, 갈색, 자연, 일러스트, acorn, autumn, forest"),
        ],
        11: [  # 가을 끝
            ("낙엽", f"Scattered autumn leaves in warm colors. 2D flat illustration, {_BG}.", "낙엽, 가을, 단풍, 낙엽놀이, 주황, 갈색, 일러스트, fallen leaves, autumn, warm colors"),
            ("감", f"Ripe orange persimmon fruit with green stem. 2D flat illustration, {_BG}.", "감, 가을과일, 주황, 과일, 추석, 달콤, 일러스트, persimmon, autumn fruit, orange"),
            ("코스모스", f"Pink and white cosmos flowers swaying gently. 2D flat illustration, {_BG}.", "코스모스, 꽃, 가을꽃, 분홍, 흰색, 들꽃, 일러스트, cosmos, autumn flower, pink"),
        ],
        12: [  # 크리스마스
            ("크리스마스트리", f"Decorated Christmas tree with colorful ornaments, lights and star on top. 2D flat illustration, {_BG}.", "크리스마스, 트리, 산타, 겨울, 선물, 별, 일러스트, Christmas tree, holiday, xmas"),
            ("눈사람", f"Cheerful snowman with red scarf and hat, button eyes. 2D flat illustration, {_BG}.", "눈사람, 겨울, 눈, 귀여운, 크리스마스, 스카프, 일러스트, snowman, winter, cute"),
            ("선물 상자", f"Colorful wrapped gift boxes with ribbons and bows. 2D flat illustration, {_BG}.", "선물, 크리스마스, 리본, 상자, 빨강, 초록, 일러스트, gift box, Christmas present, ribbon"),
        ],
    }
    items = []
    for i, (kw, pt, ht) in enumerate(defaults.get(m, defaults[7])):
        items.append({"rank": i+1, "keyword": kw, "prompt": pt, "hashtags": ht, "type": "steady"})
    return items


def _fallback_hot() -> list[dict]:
    """핫 키워드 생성 실패 시 기본값"""
    return [
        {"rank":1,"keyword":"소금빵","prompt":f"Golden buttery salt bread roll, freshly baked and glossy. 2D flat illustration, {_BG}.","hashtags":"소금빵, 빵, 베이커리, 카페, 맛있는, 디저트, 일러스트, salt bread, bakery, butter bread","type":"hot"},
        {"rank":2,"keyword":"감성 캠핑","prompt":f"Cozy camping lantern with warm glow, minimalist style. 2D flat illustration, {_BG}.","hashtags":"캠핑, 랜턴, 감성캠핑, 아웃도어, 자연, 여름캠핑, 일러스트, camping lantern, outdoor, cozy","type":"hot"},
        {"rank":3,"keyword":"플래너 소품","prompt":f"Cute stationery items: notebook, pen, sticky notes, paper clips. 2D flat illustration, {_BG}.","hashtags":"플래너, 다이어리, 문구, 스티커, 귀여운, 공부, 일러스트, planner, stationery, diary","type":"hot"},
    ]


def _fallback_miri() -> list[dict]:
    """트렌드 TOP 생성 실패 시 기본값"""
    return [
        {"rank":1,"keyword":"감성 카페","prompt":f"Cute coffee cup with latte art and steam. 2D flat illustration, {_BG}.","hashtags":"카페, 커피, 라떼, 감성, 음료, 카페인, 일러스트, cafe, coffee, latte art","type":"miri"},
        {"rank":2,"keyword":"고양이","prompt":f"Cute sitting cat with simple round eyes and soft fur pattern. 2D flat illustration, {_BG}.","hashtags":"고양이, 귀여운, 반려동물, 캐릭터, 동물, 일러스트, cat, cute, pet illustration","type":"miri"},
        {"rank":3,"keyword":"플래너 배경","prompt":f"Minimalist weekly planner layout elements with small decorative icons. 2D flat illustration, {_BG}.","hashtags":"플래너, 다이어리, 배경, 미니멀, 일정, 스케줄, 일러스트, planner background, weekly, minimal","type":"miri"},
    ]


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════
def run():
    log.info("=" * 50)
    log.info("🚀 Miri Creator 키워드 수집 시작")
    log.info(f"   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    season_ctx = get_season_context()
    log.info(f"🌍 현재 시즌: {season_ctx['season']} ({season_ctx['month']}월) {season_ctx['emoji']}")

    # Google Trends 한 번만 수집 → ②③ 공유
    trends = fetch_google_trends(limit=20)

    all_items = []

    # ① 스테디셀러
    steady = get_steady_keywords(season_ctx)
    all_items.extend(steady)
    time.sleep(2)

    # ② 핫 키워드
    hot = get_hot_keywords(trends)
    all_items.extend(hot)
    time.sleep(2)

    # ③ 트렌드 TOP (중복 제외)
    miri = get_miri_top_keywords(trends, hot)
    all_items.extend(miri)

    log.info(f"\n📊 수집 결과: 스테디 {len(steady)}개 / 핫 {len(hot)}개 / 트렌드TOP {len(miri)}개")
    log.info(f"   총 {len(all_items)}개 항목")

    # JSON 저장 (명확한 완료 메시지 포함)
    save_json(all_items)

    # Git push (HTTPS 토큰 설정 후 주석 해제)
    git_push()

    log.info("🎉 모든 작업 완료!\n")


if __name__ == "__main__":
    run()
