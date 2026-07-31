"""
miri_keywords.py v4
────────────────────
v3 → v4 변경사항 (핵심):
  - ⚠️ 복합 테마/장면 조합 방식 폐기 → "단일 요소(single element)" 방식으로 전환
    실사용 데이터 확인 결과: "개와고양이", "과학자", "프로그래머", "창고", "태양",
    "지구", "대나무숲", "퍼즐", "물음표" 등 배경 없는 단일 피사체가 훨씬 잘 팔림.
    반대로 "봄 벚꽃 청첩장 배경" 같은 복합 장면형은 실제로는 안 팔림.
  - evergreen_categories(복합 테마 문장) → SINGLE_ELEMENT_CATEGORIES(단일 명사 리스트)로 교체
  - 모든 Gemini 프롬프트에 "single isolated subject, no background scene,
    no other elements, no composed scene" 규칙 강제 삽입
  - 핫/트렌드 키워드도 "트렌드 단어 → 그릴 수 있는 단일 대상 하나로 변환" 지시 추가
  - fallback 데이터 전부 단일 요소 스타일로 교체

기존 유지사항 (v3와 동일):
  - 저작권 있는 특정 인물/캐릭터 키워드 제외 필터
  - 크로마키 그린(#00B140) 배경, 1:1 정사각형, 피사체 90% 구도
  - 사물/식물/음식은 NO face, 동물/캐릭터는 표정 허용
  - hand-drawn feel, NOT generic AI look
  - git push --autostash 방식

실행:
  python3 miri_keywords.py

cron (매일 12시):
  0 12 * * * cd /home/ubuntu/Desktop/miri_creator && python3 miri_keywords.py >> logs/cron.log 2>&1

필요 패키지:
  pip3 install requests beautifulsoup4 google-genai python-dotenv
"""

import os, json, re, time, datetime, logging, pathlib, random
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

# 이미지 생성 공통 배경/스타일 설정
BG_COLOR = (
    "chroma key green background hex color #00B140, "
    "1:1 square aspect ratio, "
    "subject fills 90% of the frame with minimal empty space, close-up composition, "
    "SINGLE ISOLATED SUBJECT ONLY — no background scene, no secondary objects, "
    "no composed scene, no environment/setting, just the one subject alone, "
    "kawaii chibi illustration style, rounded shapes, big eyes, simple cute face allowed on characters and animals, "
    "NO face only on inanimate objects like food/plants/objects, "
    "hand-drawn feel with clean black outlines, "
    "vibrant saturated colors, "
    "professional Korean sticker art style similar to LINE stickers"
)

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
- 특정 브랜드명 절대 사용 금지 (예: 에르메스, 나이키, 스타벅스 등)
- 대신 일반적 묘사 사용:
  - 특정 인물 → "뛰어노는 어린이", "축구하는 남자아이" 등 일반 묘사
  - 특정 캐릭터 → "둥근 귀의 작은 생쥐", "노란 전기 동물" 등 일반 묘사
  - 특정 브랜드 → "명품 핸드백", "운동화" 등 일반 묘사
"""

# ── 이미지 프롬프트 공통 규칙 ──
PROMPT_RULES = f"""
이미지 프롬프트 규칙 (반드시 모두 포함):
- ⭐ 반드시 "단일 피사체(single subject)" 하나만 그릴 것. 장면(scene)이나 배경 요소,
  두 개 이상의 서로 다른 대상을 조합한 구도는 절대 금지 (단, 같은 종류 2마리 조합은 예외 허용:
  예) 강아지+고양이처럼 실제로 잘 팔린 조합은 허용)
- kawaii chibi illustration style, rounded shapes
- {BG_COLOR}
- clean black outlines on all subjects
- no floor, no shadow, no ground element
- 동물/사람 캐릭터: 귀여운 큰 눈, 단순한 얼굴 표정 허용
- 사물/식물/음식: NO face, NO eyes, NO mouth
- 밝고 채도 높은 색상, 어린이도 좋아할 스타일
- LINE 스티커나 카카오 이모티콘 스타일 참고
- 저작권 있는 특정 인물/캐릭터/브랜드 절대 사용 금지
- 최소 700x700px 이상 퀄리티로 생성 가능한 디테일 수준
"""

# ═══════════════════════════════════════════════════
# ★ 단일 요소 카테고리 풀 (복합 테마 대신 사용)
#   실사용 데이터 기반: 동물/직업/자연물/건물/아이콘/사물/음식/탈것/게임요소
# ═══════════════════════════════════════════════════
SINGLE_ELEMENT_CATEGORIES = {
    "동물": [
        "강아지", "고양이", "토끼", "햄스터", "판다", "여우", "곰", "펭귄",
        "부엉이", "다람쥐", "거북이", "물고기", "공룡", "호랑이", "사자", "강아지와 고양이",
    ],
    "직업_캐릭터": [
        "과학자", "프로그래머", "의사", "간호사", "교사", "요리사", "소방관",
        "경찰관", "우체부", "농부", "화가", "음악가", "운동선수", "택배기사",
        "미용사", "약사", "회계사", "변호사",
    ],
    "자연_사물": [
        "태양", "달", "구름", "무지개", "번개", "지구", "별", "산",
        "나무", "대나무숲", "꽃", "단풍잎", "눈송이", "물방울",
    ],
    "건물_장소": [
        "창고", "집", "학교", "병원", "카페", "도서관", "공장", "농장",
    ],
    "아이콘_기호": [
        "물음표", "느낌표", "체크표시", "금지표시", "하트", "별표", "화살표",
        "말풍선", "돋보기", "톱니바퀴", "자물쇠", "전구", "시계",
    ],
    "사물_도구": [
        "우산", "가방", "책", "노트북", "커피잔", "안경", "카메라", "열쇠",
        "선물상자", "편지봉투", "핸드폰", "가위", "연필",
    ],
    "음식": [
        "케이크", "수박", "송편", "붕어빵", "떡볶이", "김밥", "라면",
        "아이스크림", "커피", "빵", "과일바구니",
    ],
    "탈것": [
        "자동차", "자전거", "비행기", "기차", "배", "오토바이",
    ],
    "퍼즐_게임요소": [
        "퍼즐조각", "체스말", "주사위", "카드", "트로피", "메달",
    ],
}

# ═══════════════════════════════════════════════════
# ★ 스테디셀러 전용: 아이들이 좋아할 귀여운 몬스터 카테고리
#   무섭지 않고 kawaii한 몬스터로 한정. 육아/교육 콘텐츠(포스터, 학습지,
#   유치원 안내문 등)에 포인트 요소로 자주 쓰이는 타입 위주.
# ═══════════════════════════════════════════════════
CUTE_MONSTER_KEYWORDS = [
    "액체괴물", "슬라임괴물", "꼬마유령", "눈알괴물", "뿔괴물", "털복숭이괴물",
    "우주괴물", "물방울괴물", "뾰족이괴물", "동글이괴물", "도깨비", "꼬마드래곤",
    "박쥐괴물", "마법사괴물", "구름괴물", "별괴물", "촉수괴물", "이빨괴물",
    "젤리괴물", "안경쓴괴물", "왕관쓴괴물", "날개달린괴물", "알사탕괴물", "무지개괴물",
]


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
# 1. 계절 판단 (유지)
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
# 2. Google Trends 수집 + 필터링 (유지)
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


def filter_trends(trends: list[dict]) -> list[dict]:
    """저작권/인물명/브랜드명/부정적 키워드 코드 레벨 필터링"""
    exclude_patterns = [
        r'에르메스|샤넬|루이비통|구찌|프라다|나이키|아디다스|스타벅스|맥도날드',  # 브랜드
        r'청장|장관|대통령|국회|정부|경찰|검찰|법원|의원|국무',                   # 정치/공직
        r'사망|사고|범죄|재판|수사|의혹|논란|충돌|폭행|피해|사건',               # 부정적 뉴스
        r'선수|배우|가수|아이돌|감독|코치',                                        # 특정 인물 직함
    ]
    filtered = []
    for t in trends:
        kw = t['keyword']
        excluded = any(re.search(p, kw) for p in exclude_patterns)
        if not excluded:
            filtered.append(t)
    log.info(f"  필터링 후: {len(filtered)}/{len(trends)}개")
    return filtered


# ═══════════════════════════════════════════════════
# 3. 스테디셀러 키워드 (★ 단일 요소 카테고리 기반으로 전면 교체)
# ═══════════════════════════════════════════════════
def get_steady_keywords(season_ctx: dict) -> list[dict]:
    """★ 귀여운 몬스터 카테고리에서 랜덤 3개 뽑아 프롬프트 생성 (아이들 타겟 스테디셀러)"""
    log.info("📌 스테디셀러(귀여운 몬스터) 키워드 생성 중...")

    # 매일 다른 조합, 같은 날은 같은 결과 (시드 고정)
    rnd = random.Random(datetime.datetime.now().strftime("%Y%m%d") + "_monster")
    picked = rnd.sample(CUTE_MONSTER_KEYWORDS, 3)
    picked_text = "\n".join([f"- {subj}" for subj in picked])

    prompt = f"""
당신은 한국 디자인 플랫폼 '미리캔버스'에서 PNG 일러스트 요소(element)를 판매하는 전문가입니다.

⭐ 스테디셀러 컨셉: "아이들이 좋아할 만한 귀여운 몬스터" 시리즈입니다.
유치원/초등학교 안내문, 학습지, 육아 콘텐츠, 어린이 포스터 등에 포인트로
붙여넣기 좋은 단일 몬스터 캐릭터를 만듭니다.

⭐ 매우 중요: 무섭거나 징그러운 몬스터가 아니라, 동글동글하고 사랑스러운
kawaii 스타일 몬스터여야 합니다 (픽사/지브리풍 귀여움, 공포/괴기 요소 절대 금지).
그리고 실제 판매 데이터상 배경 없이 몬스터 "하나만" 있는 단일 요소 클립아트가
장면형 이미지보다 훨씬 잘 팔립니다 (파포/포스터에 붙여쓰는 용도이기 때문).

오늘 다룰 몬스터 3개 (아래 그대로 사용, 서로 합치거나 장면으로 만들지 말 것):
{picked_text}

각 항목에 대해 절대 배경 장면 없이, 그 몬스터 "하나만" 그리는 프롬프트를 작성해주세요.
몸통 형태, 색상, 특징(뿔/눈/촉수 등)은 몬스터 이름에 어울리게 자유롭게 구체화해도 됩니다.

{COPYRIGHT_FILTER}

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어, 몬스터 이름)",
    "prompt": "이미지 생성 프롬프트 (영어, 단일 몬스터 캐릭터만)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

{PROMPT_RULES}
- 몬스터는 반드시 귀엽고 친근한 표정(웃는 눈, 동그란 눈 등)을 가질 것, 무서운 표정 금지

해시태그 규칙:
- 10개 이하, 한국어 7개 + 영어 3개 조합
- "몬스터, 괴물, 캐릭터, 어린이, 유치원, 귀여운" 등 육아/교육 검색어 위주로 포함
- 키워드 자체 + "일러스트/캐릭터/PNG/clipart" 조합도 포함
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        for it in items:
            it["type"] = "steady"
        log.info(f"  ✅ 스테디셀러(단일요소) {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 스테디셀러 생성 실패: {e}")
        return _fallback_steady(season_ctx)


# ═══════════════════════════════════════════════════
# 4. 핫 키워드 (★ 트렌드 단어 → 단일 대상으로 변환하도록 지시 추가)
# ═══════════════════════════════════════════════════
def get_hot_keywords(trends: list[dict]) -> list[dict]:
    """Google Trends 실시간 데이터에서 '단일 대상으로 그릴 수 있는' 핫 키워드 3개 선별"""
    log.info("🔥 핫 키워드(단일요소 변환) 생성 중...")

    trends_text = "\n".join([f"- {t['keyword']} ({t.get('traffic','?')} 검색)" for t in trends[:15]])
    if not trends_text:
        trends_text = "- 소금빵\n- 고양이\n- 우산"

    prompt = f"""
한국의 요즘 인기 검색어 목록입니다:
{trends_text}

{COPYRIGHT_FILTER}

⭐ 매우 중요: 이 트렌드 키워드들을 그대로 쓰지 말고, 각 트렌드에서 연상되는
"단일 사물/동물/음식/인물 캐릭터 하나"로 단순화해서 뽑아주세요.
예) "소금빵 챌린지" 트렌드 → "소금빵" (빵 하나만 그림, 챌린지 장면 X)
예) "제주도 여행" 트렌드 → "야자수" 또는 "여행가방" (여행 풍경 X, 단일 사물 O)

이 중에서 미리캔버스 PNG 일러스트 요소로 만들기 적합한, 단일 대상으로 단순화 가능한
키워드 3개를 골라주세요.
(추상적/정치적 키워드 제외, 복합 장면으로만 표현 가능한 것도 제외)
(특정 인물명/캐릭터명/브랜드명이 트렌드에 있어도 반드시 제외)
(적합한 것이 없으면 현재 계절에 맞는 단일 사물/동물 키워드로 자유롭게 생성)

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어, 단일 명사)",
    "prompt": "이미지 생성 프롬프트 (영어, 단일 피사체만)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

{PROMPT_RULES}
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        for it in items:
            it["type"] = "hot"
        log.info(f"  ✅ 핫 키워드(단일요소) {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 핫 키워드 생성 실패: {e}")
        return _fallback_hot()


# ═══════════════════════════════════════════════════
# 5. 트렌드 TOP (★ 동일하게 단일요소 변환 지시 추가, 중복 제외 유지)
# ═══════════════════════════════════════════════════
def get_miri_top_keywords(trends: list[dict], hot_keywords: list[dict]) -> list[dict]:
    """Google Trends에서 핫 키워드와 중복 없는, 단일 대상 변환 가능한 TOP 3 선별"""
    log.info("🏆 트렌드 TOP 키워드(단일요소 변환) 생성 중...")

    hot_kw_names = [it.get("keyword", "") for it in hot_keywords]
    trends_text = "\n".join([f"- {t['keyword']} ({t.get('traffic','?')} 검색)" for t in trends[:20]])
    if not trends_text:
        trends_text = "- 수박\n- 지구본\n- 자전거"

    already_picked = ", ".join(hot_kw_names) if hot_kw_names else "없음"

    prompt = f"""
한국 구글 트렌드 인기 검색어입니다:
{trends_text}

이미 선택된 키워드 (중복 제외 필수): {already_picked}

{COPYRIGHT_FILTER}

⭐ 매우 중요: 트렌드 키워드를 그대로 쓰지 말고, 연상되는 "단일 사물/동물/음식/인물 캐릭터 하나"로
단순화해서 뽑아주세요. 복합 장면(예: "~하는 풍경", "~축제 현장")은 절대 금지, 오직 단일 대상만.

위 목록에서 미리캔버스 PNG 일러스트 요소로 만들기 좋은, 단일 대상으로 변환 가능한 키워드
3개를 골라주세요.
- 이미 선택된 키워드와 절대 겹치지 않게 선택
- 특정 인물명/캐릭터명/브랜드명 제외
- 목록에 적합한 것이 부족하면 계절감 있는 단일 사물/동물 키워드로 자유롭게 채우기

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어, 단일 명사)",
    "prompt": "이미지 생성 프롬프트 (영어, 단일 피사체만)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

{PROMPT_RULES}
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        for it in items:
            it["type"] = "miri"
        log.info(f"  ✅ 트렌드 TOP(단일요소) {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 트렌드 TOP 생성 실패: {e}")
        return _fallback_miri()


# ═══════════════════════════════════════════════════
# 6. JSON 저장 (유지)
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

    log.info("─" * 50)
    log.info(f"✅ JSON 저장 완료!")
    log.info(f"   파일: {OUTPUT_FILE}")
    log.info(f"   항목: {len(items)}개")
    log.info(f"   갱신: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"   다음: {next_update.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("─" * 50)


# ═══════════════════════════════════════════════════
# 7. Git Push (유지)
# ═══════════════════════════════════════════════════
def git_push() -> None:
    """GitHub 자동 push (--autostash로 충돌 방지)"""
    import subprocess
    log.info("📤 GitHub push 시도 중...")
    try:
        subprocess.run(["git", "-C", str(BASE_DIR), "add", "data/keywords.json"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "commit", "-m",
                        f"auto: update keywords {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "pull", "--rebase", "--autostash", "origin", "main"], check=True)
        subprocess.run(["git", "-C", str(BASE_DIR), "push"], check=True)
        log.info("🚀 GitHub push 완료!")
    except Exception as e:
        log.warning(f"⚠️  Git push 실패 (JSON 저장은 완료됨): {e}")


# ═══════════════════════════════════════════════════
# ★ Fallback 데이터 (전부 단일 요소 스타일로 교체)
#   실제 잘 팔린 것들: 동물, 직업 캐릭터, 자연물, 건물, 아이콘 기반
# ═══════════════════════════════════════════════════

_BG = (
    f"{BG_COLOR}, "
    "clean black outlines on all subjects, "
    "no floor, no shadow, no ground element"
)

def _fallback_steady(ctx: dict) -> list[dict]:
    """Gemini 실패 시 기본값 - 귀여운 몬스터 3종 (아이들 타겟 스테디셀러)"""
    pool = [
        ("액체괴물", f"A single cute round liquid slime monster character, translucent gooey body, big friendly smiling eyes, no scary features, filling 90% of frame. 2D flat illustration, {_BG}.",
         "액체괴물, 슬라임, 몬스터, 괴물, 캐릭터, 어린이, 유치원, 귀여운, slime monster, cute character"),
        ("꼬마유령", f"A single tiny cute ghost character, round soft shape, big sparkly eyes, friendly smile, floating pose, no scary features, filling 90% of frame. 2D flat illustration, {_BG}.",
         "꼬마유령, 유령, 몬스터, 캐릭터, 어린이, 할로윈, 귀여운, little ghost, cute monster"),
        ("뿔괴물", f"A single small round monster character with two tiny cute horns, big friendly eyes, soft fuzzy body, no scary features, filling 90% of frame. 2D flat illustration, {_BG}.",
         "뿔괴물, 몬스터, 괴물, 캐릭터, 어린이, 유치원, 귀여운, horned monster, cute creature"),
        ("눈알괴물", f"A single round fluffy monster character with one big cute cyclops eye, friendly smile, soft fur texture, no scary features, filling 90% of frame. 2D flat illustration, {_BG}.",
         "눈알괴물, 몬스터, 괴물, 캐릭터, 어린이, 유치원, 귀여운, one eyed monster, cute character"),
        ("우주괴물", f"A single small round alien monster character with antennae, big sparkly eyes, pastel purple body, friendly smile, no scary features, filling 90% of frame. 2D flat illustration, {_BG}.",
         "우주괴물, 외계인, 몬스터, 캐릭터, 어린이, 유치원, 귀여운, space alien monster, cute character"),
        ("도깨비", f"A single cute round Korean dokkaebi goblin character with a small horn, big friendly eyes, soft rounded body, no scary features, filling 90% of frame. 2D flat illustration, {_BG}.",
         "도깨비, 몬스터, 괴물, 전래동화, 캐릭터, 어린이, 귀여운, dokkaebi, cute goblin character"),
    ]
    rnd = random.Random(ctx.get("month", 1))
    picks = rnd.sample(pool, 3)
    items = []
    for i, (kw, pt, ht) in enumerate(picks):
        items.append({"rank": i+1, "keyword": kw, "prompt": pt, "hashtags": ht, "type": "steady"})
    return items


def _fallback_hot() -> list[dict]:
    """핫 키워드 생성 실패 시 기본값 - 단일 요소"""
    return [
        {"rank":1,"keyword":"소금빵","prompt":f"A single golden buttery salt bread roll, no face, filling 90% of frame. 2D flat illustration, {_BG}.","hashtags":"소금빵, 빵, 베이커리, 사물, 음식, 일러스트, salt bread, bakery, food","type":"hot"},
        {"rank":2,"keyword":"강아지","prompt":f"A single sitting puppy, cute round eyes, simple face expression, filling 90% of frame. 2D flat illustration, {_BG}.","hashtags":"강아지, 반려동물, 동물, 캐릭터, 일러스트, puppy, dog, pet illustration","type":"hot"},
        {"rank":3,"keyword":"물음표","prompt":f"A single bold question mark icon, no face, simple shape, filling frame. 2D flat illustration, {_BG}.","hashtags":"물음표, 아이콘, 기호, 질문, 심볼, 일러스트, question mark, icon, symbol","type":"hot"},
    ]


def _fallback_miri() -> list[dict]:
    """트렌드 TOP 생성 실패 시 기본값 - 단일 요소"""
    return [
        {"rank":1,"keyword":"커피잔","prompt":f"A single coffee cup with latte art, no face, filling 90% of frame. 2D flat illustration, {_BG}.","hashtags":"커피, 카페, 컵, 음료, 사물, 일러스트, coffee cup, cafe, drink","type":"miri"},
        {"rank":2,"keyword":"태양","prompt":f"A single stylized smiling sun with rays, filling 90% of frame. 2D flat illustration, {_BG}.","hashtags":"태양, 해, 날씨, 자연, 밝은, 일러스트, sun, weather, nature","type":"miri"},
        {"rank":3,"keyword":"퍼즐조각","prompt":f"A single colorful puzzle piece, no face, filling frame. 2D flat illustration, {_BG}.","hashtags":"퍼즐, 조각, 게임, 협업, 사물, 일러스트, puzzle piece, game, object","type":"miri"},
    ]


# ═══════════════════════════════════════════════════
# MAIN (유지)
# ═══════════════════════════════════════════════════
def run():
    log.info("=" * 50)
    log.info("🚀 Miri Creator 키워드 수집 시작 (단일요소 v4)")
    log.info(f"   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    season_ctx = get_season_context()
    log.info(f"🌍 현재 시즌: {season_ctx['season']} ({season_ctx['month']}월) {season_ctx['emoji']}")

    # Google Trends 수집 + 코드 레벨 필터링
    trends = fetch_google_trends(limit=20)
    trends = filter_trends(trends)

    all_items = []

    # ① 스테디셀러 (단일요소 카테고리 기반)
    steady = get_steady_keywords(season_ctx)
    all_items.extend(steady)
    time.sleep(2)

    # ② 핫 키워드 (트렌드 → 단일요소 변환)
    hot = get_hot_keywords(trends)
    all_items.extend(hot)
    time.sleep(2)

    # ③ 트렌드 TOP (중복 제외, 단일요소 변환)
    miri = get_miri_top_keywords(trends, hot)
    all_items.extend(miri)

    log.info(f"\n📊 수집 결과: 스테디 {len(steady)}개 / 핫 {len(hot)}개 / 트렌드TOP {len(miri)}개")
    log.info(f"   총 {len(all_items)}개 항목")

    save_json(all_items)
    git_push()

    log.info("🎉 모든 작업 완료!\n")


if __name__ == "__main__":
    run()
