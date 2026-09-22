"""
miri_keywords.py v7 — 판매 데이터 기반 "승자 공식" 버전
────────────────────────────────────────────────
배경 (2025-10-31~2026-09-19, 217건 거래 실사용 데이터 분석):
  - 867개 등록 요소 중 42개(4.8%)만 판매, 매출 TOP10이 전체의 79.7% 차지
  - 2024년 초기 배치가 지금도 매출을 견인, 이후 자동화가 매일 찍어낸 신규
    아이템(스테디셀러/핫키워드/키즈venue/스티커/실용아이콘 5테마 로테이션)은
    매출 기여 사실상 0에 수렴
  - 승자(개와고양이, 대나무숲, 돋보기아이) 공통점: 굵은 아웃라인, 그라데이션/음영이
    있는 고채도 색감, 축소해도 읽히는 단순 구도, 구체적인 물리적 상호작용 디테일,
    시즌/트렌드가 아닌 범용 개념(반려동물·우정 / 자연·성장·힐링 / 조사·분석·탐구)

v6 → v7 변경사항 (핵심):
  - ⚠️ 5개 테마 로테이션(스테디셀러/핫키워드/키즈venue/칭찬스티커/실용아이콘) 전면 폐기
  - Google Trends 기반 "핫키워드"도 함께 제거 (트렌드 랜덤 소재가 저성과 원인 중 하나였음)
  - UNIVERSAL_CONCEPTS(범용 개념 5축: 조사분석/성장힐링/우정협업/고민생각/발견아이디어)로 교체
    → 매일 축당 정확히 1개씩, 총 5개 이미지만 생성
  - PROMPT_RULES에 승자 공식 명시적으로 삽입:
    굵고 일관된 검정 아웃라인 / 단색이 아닌 그라데이션·음영 색감 /
    구체적인 물리적 상호작용 디테일 최소 1개 강제 / 썸네일 가독성 / 범용성
  - 단일 피사체 원칙은 유지하되, "서로 상호작용하는 두 피사체"(예: 강아지+고양이,
    손을 맞잡은 두 아이)는 승자 사례 기반으로 명시적 예외 허용

기존 유지사항:
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
  pip3 install google-genai python-dotenv
"""

import os, json, re, datetime, logging, pathlib, random
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
# ★ v7: 승자 공식(굵은 아웃라인, 그라데이션 음영, 물리적 상호작용 디테일) 반영.
#   배경은 여전히 순수 단색 크로마키 그린 유지 — 그라데이션은 "피사체" 색감에만 적용.
BG_COLOR = (
    "chroma key green background hex color #00B140, pure flat solid color with NO gradient on the background itself, "
    "1:1 square aspect ratio, "
    "subject fills 90% of the frame with minimal empty space, close-up composition, "
    "SINGLE SUBJECT, OR TWO SUBJECTS ACTIVELY INTERACTING WITH EACH OTHER (e.g. a dog and cat leaning "
    "against each other, two kids holding hands) — no wider scene, no extra background elements, "
    "no environment/setting beyond the subject(s) themselves, "
    "clean modern flat vector illustration style, semi-simplified but natural/balanced proportions "
    "(NOT exaggerated chibi or super-deformed anime style), smooth clean shapes, "
    "friendly and approachable but not overly cutesy, "
    "simple minimal facial expression allowed on characters and animals only (subtle, not big anime eyes), "
    "NO face only on inanimate objects like food/plants/objects, "
    "THICK, CONFIDENT, CONSISTENT-WEIGHT BLACK OUTLINE on every subject — no thin, sketchy, or wavering lines, "
    "saturated but tasteful colors rendered WITH SUBTLE GRADIENT/SHADING for a sense of volume and depth "
    "(NOT flat single-tone fill on the subject), "
    "professional stock-illustration / icon-marketplace style suitable for universal design use "
    "(business documents, blogs, presentations, posters — not tied to a single cutesy sticker aesthetic), "
    "ABSOLUTELY NO TEXT, NO LETTERS, NO NUMBERS, NO TYPOGRAPHY OF ANY KIND anywhere in the image"
)

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

# ── 이미지 프롬프트 공통 규칙 (★ v7: 승자 공식 명시 삽입) ──
PROMPT_RULES = f"""
이미지 프롬프트 규칙 (아래 항목별 구조를 참고해서 자연스러운 영어 프롬프트 한 문단으로 작성할 것):

- 스타일: 미니멀 플랫 디자인, 깔끔한 벡터 아트 스타일, 누구나 직관적으로 이해할 수 있는 아이콘 같은 그림체
- 배경: 완전한 단색 초록색(#00B140) 크로마키 배경, 그림자·텍스처·그라데이션 없이 순수 단색만
  (그라데이션/음영은 배경이 아니라 피사체 자체의 색감에만 적용할 것)
- 구도: 정중앙 배치, 1:1 정사각형 비율, 피사체가 프레임의 90% 이상을 채워 여백 최소화
- 용도: 비즈니스 프레젠테이션(PPT) 삽화로 바로 쓸 수 있는 범용 스타일
- 크기: 최소 700x700px 이상 퀄리티
- 추가 요구사항: 텍스트/글자/숫자/워터마크 절대 없음, 사실적 사진 스타일 아님

⭐⭐ 판매 데이터로 검증된 "승자 공식" — 반드시 전부 반영할 것 ⭐⭐
1. 굵고 확신 있는 검정 아웃라인. 얇거나 흐릿하거나 두께가 들쭉날쭉한 선 절대 금지
2. 고채도이지만 촌스럽지 않은 색감. 피사체를 단색으로 납작하게 채우지 말고
   그라데이션/음영을 넣어 입체감과 볼륨감을 살릴 것
3. 축소된 썸네일 크기에서도 한눈에 무엇인지 인지되는 단순명료한 구도.
   디테일 과잉으로 실루엣이 뭉개지지 않게 할 것
4. ⭐ 가장 중요 — 구체적인 물리적 상호작용 디테일을 최소 1개 이상 그림 안에 실제로 그려넣을 것.
   단순히 두 대상을 나란히 배치하는 것이 아니라, 예를 들어 "돋보기를 든 아이"라면 돋보기
   렌즈 안에 확대되어 비치는 눈을 실제로 그리는 식. 대상 사이의 진짜 접촉/반응/작용을 구체화할 것
5. 범용성 — 특정 시즌/이벤트/유행어가 아니라 프레젠테이션에서 상시로 통하는 범용 개념
   (반려동물·우정, 자연·성장·힐링, 조사·분석·탐구 등)

⭐ 그 외 필수 규칙:
- {BG_COLOR}
- 반드시 "단일 피사체" 하나만 그리거나, 위 예외에 해당하는 "서로 상호작용하는 두 피사체"만
  그릴 것. 그 이상의 다중 요소나 배경 장면 조합은 절대 금지
- no floor, no shadow, no ground element
- 동물/사람 캐릭터: 은은하고 단순한 표정 정도만 허용 (과장된 큰 눈/귀여움 강조 X)
- 사물/식물/음식: NO face, NO eyes, NO mouth
- 저작권 있는 특정 인물/캐릭터/브랜드 절대 사용 금지
"""

# ═══════════════════════════════════════════════════
# ★ 범용 개념 5축 (브리핑 기반 재편, 테마 로테이션 대신 사용)
#   승자 3개(개와고양이/대나무숲/돋보기아이)가 각각 우정·성장·탐구 축에 해당함을
#   근거로, 프레젠테이션에서 상시로 필요한 범용 개념 5개를 고정 축으로 삼음.
#   대분류(축) 5개는 고정, 하위 구체 키워드는 Gemini가 매번 새로 제안(예시는 seed 역할만).
# ═══════════════════════════════════════════════════
UNIVERSAL_CONCEPTS = {
    "investigate": {
        "label": "조사·분석·탐구",
        "examples": [
            "돋보기아이", "현미경보는과학자", "지도보는탐험가", "별자리관측",
            "탐정", "책파헤치는아이", "퍼즐분석",
        ],
    },
    "growth": {
        "label": "성장·발전·힐링",
        "examples": [
            "대나무숲", "새싹키우는손", "나무심기", "씨앗에물주기",
            "해바라기", "나이테", "숲속산책",
        ],
    },
    "friendship": {
        "label": "우정·협업·관계",
        "examples": [
            "강아지와고양이", "손을맞잡은두아이", "어깨동무친구", "하이파이브",
            "나란히앉은토끼와거북이", "우산함께쓰는친구",
        ],
    },
    "thinking": {
        "label": "고민·생각·사고",
        "examples": [
            "턱괴고생각하는아이", "물음표보는사람", "골똘히생각하는고양이",
            "미로앞에서고민하는아이", "저울질하는사람", "갈림길에선사람",
        ],
    },
    "discovery": {
        "label": "발견·아이디어·영감",
        "examples": [
            "전구켜지는순간", "퍼즐마지막조각", "보물찾은아이",
            "유레카포즈", "열쇠를찾은손", "돋보기로발견",
        ],
    },
}


def gemini_ask(prompt: str) -> str:
    """Gemini API 호출 공통 함수"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return resp.text.strip()


def parse_json_response(text: str) -> list:
    """Gemini 응답에서 JSON 파싱 (마크다운 펜스 제거)"""
    text = re.sub(r"^```json\s*|^```\s*|```$", "", text, flags=re.MULTILINE).strip()
    return json.loads(text)


BANNED_KEYWORD_PATTERNS = [
    r'에르메스|샤넬|루이비통|구찌|프라다|나이키|아디다스|스타벅스|맥도날드',  # 브랜드
    r'청장|장관|대통령|국회|정부|경찰|검찰|법원|의원|국무',                   # 정치/공직
    r'사망|사고|범죄|재판|수사|의혹|논란|충돌|폭행|피해|사건',               # 부정적 뉴스
    r'선수|배우|가수|아이돌|감독|코치',                                        # 특정 인물 직함
]


def _is_valid_single_keyword(kw: str) -> bool:
    """★ Gemini가 자유 제안한 키워드가 '단일 명사(구)'로 안전한지 코드 레벨 검증.
    카테고리 이탈한 랜덤 단어나 문장형 응답이 그대로 나가는 것을 막기 위한 안전장치.
    """
    if not kw:
        return False
    kw = kw.strip()
    if len(kw) < 2 or len(kw) > 12:
        return False
    if kw.count(" ") >= 2:
        return False
    if re.search(r'(다|요|음|는|하는|있는|그리고)$', kw):
        return False
    if any(re.search(p, kw) for p in BANNED_KEYWORD_PATTERNS):
        return False
    return True


def _validate_or_fallback(items: list, picked_axes: list, example_pool: dict, log_label: str = "") -> list:
    """★ Gemini가 자유 제안한 키워드를 그대로 살리되(다양성 유지),
    검증(_is_valid_single_keyword)에 실패한 항목만 해당 축의 예시 풀에서 랜덤으로 안전하게 대체.
    """
    if len(items) != len(picked_axes):
        log.warning(
            f"  ⚠️ {log_label}: Gemini 응답 개수({len(items)}) != 지정 축 개수({len(picked_axes)}) "
            f"— 앞에서부터 순서대로 매칭"
        )
    for i, it in enumerate(items):
        if i >= len(picked_axes):
            break
        axis = picked_axes[i]
        kw = (it.get("keyword") or "").strip()
        if _is_valid_single_keyword(kw):
            continue  # 유효한 신규 제안 → 그대로 살려서 다양성 확보
        fallback = random.choice(example_pool[axis]["examples"])
        log.warning(f"  ⚠️ {log_label}: '{kw}'가 검증 실패(축:{axis}) → 예시 '{fallback}'로 대체")
        it["keyword"] = fallback
    return items


# ═══════════════════════════════════════════════════
# 범용 개념 키워드 생성 (★ v7: 유일한 생성 함수, 5축 × 1개 = 5개)
# ═══════════════════════════════════════════════════
def get_universal_concept_keywords() -> list[dict]:
    """5개 범용 개념 축(조사분석/성장힐링/우정협업/고민생각/발견아이디어)에서
    매일 축당 정확히 1개씩, 총 5개 키워드+이미지 프롬프트를 생성.
    트렌드/테마 로테이션 대신 판매 데이터로 검증된 승자 공식을 모든 프롬프트에 강제.
    """
    log.info("🎯 범용 개념 키워드(승자 공식 반영) 생성 중...")

    axes = list(UNIVERSAL_CONCEPTS.keys())
    live_rnd = random.Random()  # 실행마다 예시가 달라져서 다양성 확보
    axis_block = "\n".join([
        f"{i+1}. [{UNIVERSAL_CONCEPTS[axis]['label']}] 참고 예시(그대로 써도 되고, "
        f"같은 축의 느낌으로 새로 제안해도 됨): "
        f"{', '.join(live_rnd.sample(UNIVERSAL_CONCEPTS[axis]['examples'], min(4, len(UNIVERSAL_CONCEPTS[axis]['examples']))))}"
        for i, axis in enumerate(axes)
    ])

    prompt = f"""
당신은 한국 디자인 플랫폼 '미리캔버스'에서 PNG 일러스트 요소(element)를 판매하는 전문가입니다.

⭐ 아래는 11개월치 실제 판매 데이터 분석(217건 거래)으로 확인된 "잘 팔리는 요소"의 공통 공식입니다:
1. 굵고 확신 있는 검정 아웃라인 (얇거나 흐릿한 선 없이 일관된 두께)
2. 고채도이지만 촌스럽지 않은 색감 — 단색이 아니라 그라데이션/음영으로 입체감을 살림
3. 축소된 썸네일에서도 즉시 인지되는 단순명료한 구도
4. ⭐ 가장 중요: 물리적 상호작용을 구체적으로 표현 — 예를 들어 "돋보기 + 아이"를 그냥 나란히
   배치하는 게 아니라, 돋보기 렌즈 안에 확대된 눈이 실제로 비치는 디테일까지 그려넣는 식.
   이런 구체적 디테일 하나가 퀄리티 체감을 크게 좌우함
5. 범용성 — 특정 시즌/이벤트가 아니라 프레젠테이션에서 상시로 필요한 개념
   (반려동물·우정, 자연·성장·힐링, 조사·분석·탐구 등)

⭐ 반대로 실제로 잘 안 팔린 것: 매일 바뀌는 트렌드 키워드, 복합 장면형 배경, 특정 시즌/이벤트
한정 소재. → 그래서 오늘부터는 아래 5개 "범용 개념" 축으로만 키워드를 만듭니다.

오늘 다룰 5개 축과 참고 예시 (반드시 순서대로 각 1개씩, 총 5개):
{axis_block}

각 축마다 참고 예시를 그대로 써도 되고, 그 축의 느낌에 맞는 "새로운" 아이디어를
자유롭게 제안해도 됩니다. 단, 반드시 그 축의 컨셉에서 벗어나지 않아야 합니다.

{COPYRIGHT_FILTER}

각 항목에 대해 아래 형식으로 JSON 배열만 반환하세요 (마크다운 없이 순수 JSON, 축 순서대로 5개):
[
  {{
    "rank": 1,
    "keyword": "키워드 (한국어, 2~10자 정도의 명사구)",
    "prompt": "이미지 생성 프롬프트 (영어 한 문단, 위 승자 공식 5가지를 모두 반영하고 구체적인 물리적 상호작용/디테일을 최소 1개 명시적으로 묘사할 것)",
    "hashtags": "미리캔버스 태그 10개 (한국어+영어 혼용, 쉼표 구분)"
  }}
]

{PROMPT_RULES}

해시태그 규칙:
- 10개 이하, 한국어 7개 + 영어 3개 조합
- 키워드 자체 + 해당 축 관련 검색어(예: 우정·협업 축이면 "우정, 협업, 반려동물" 등) +
  "일러스트/캐릭터/PNG/clipart" 조합 포함
"""

    try:
        text = gemini_ask(prompt)
        items = parse_json_response(text)
        items = _validate_or_fallback(items, axes, example_pool=UNIVERSAL_CONCEPTS, log_label="범용개념")
        for i, it in enumerate(items):
            it["type"] = axes[i] if i < len(axes) else axes[-1]
        log.info(f"  ✅ 범용 개념 키워드 {len(items)}개 생성 완료")
        return items
    except Exception as e:
        log.error(f"  ❌ 범용 개념 키워드 생성 실패: {e}")
        return _fallback_universal()


# ═══════════════════════════════════════════════════
# JSON 저장 (유지)
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
# Git Push (유지)
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
# ★ Fallback 데이터 (Gemini 실패 시 축당 1개씩 5개, 승자 공식 반영)
# ═══════════════════════════════════════════════════
_BG = (
    f"{BG_COLOR}, no floor, no shadow, no ground element"
)

def _fallback_universal() -> list[dict]:
    """Gemini 실패 시 기본값 — 범용 개념 5축 × 1개, 승자 공식(굵은 아웃라인/그라데이션 음영/
    물리적 상호작용 디테일) 반영."""
    return [
        {"rank": 1, "type": "investigate", "keyword": "돋보기아이",
         "prompt": f"A single child holding a large magnifying glass up to one eye, with the eye visibly enlarged and clearly visible through the lens glass — this magnified-eye detail is essential and must be drawn explicitly. {_BG}",
         "hashtags": "돋보기, 관찰, 탐구, 조사, 호기심많은아이, 일러스트, magnifying glass, curious kid, investigate"},
        {"rank": 2, "type": "growth", "keyword": "새싹키우는손",
         "prompt": f"A single cupped hand gently cradling a small green sprout with two fresh leaves, soil visibly clinging to the tiny roots where the sprout meets the palm — this hand-to-sprout contact detail is essential and must be drawn explicitly. {_BG}",
         "hashtags": "새싹, 성장, 힐링, 자연, 식물키우기, 일러스트, sprout, growth, healing plant"},
        {"rank": 3, "type": "friendship", "keyword": "강아지와고양이",
         "prompt": f"A single dog and cat leaning their bodies against each other, cheek to cheek, with visible fur overlap where they touch — this physical contact detail is essential and must be drawn explicitly. {_BG}",
         "hashtags": "강아지, 고양이, 우정, 반려동물, 친구, 일러스트, dog and cat, friendship, pets"},
        {"rank": 4, "type": "thinking", "keyword": "턱괴고생각하는아이",
         "prompt": f"A single child resting their chin on one hand in a thinking pose, with the fingers visibly pressing into the cheek and a faint furrowed brow showing deep thought — this hand-to-face pressure detail is essential and must be drawn explicitly. {_BG}",
         "hashtags": "생각, 고민, 사고, 골똘히생각하는아이, 아이디어, 일러스트, thinking pose, contemplation, kid"},
        {"rank": 5, "type": "discovery", "keyword": "전구켜지는순간",
         "prompt": f"A single glowing light bulb with a bright starburst of light rays radiating outward from the filament, the glass surface visibly reflecting the warm glow — this radiating-light detail is essential and must be drawn explicitly. {_BG}",
         "hashtags": "전구, 아이디어, 영감, 발견, 유레카, 일러스트, light bulb, idea, discovery moment"},
    ]


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════
def run():
    log.info("=" * 50)
    log.info("🚀 Miri Creator 키워드 수집 시작 (범용개념 승자공식 버전 v7)")
    log.info(f"   {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 50)

    items = get_universal_concept_keywords()

    log.info(f"\n📊 수집 결과: 총 {len(items)}개 항목 (범용개념 5축 × 1개)")

    save_json(items)
    git_push()

    log.info("🎉 모든 작업 완료!\n")


if __name__ == "__main__":
    run()
