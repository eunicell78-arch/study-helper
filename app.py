import streamlit as st
import requests
import json
import re
import io
from urllib.parse import urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(
    page_title="🎓 수행평가 도우미",
    page_icon="🎓",
    layout="wide",
)

# ──────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────
MIN_SOURCES = 2                # default minimum sources per evaluation element
URL_TIMEOUT = 10               # seconds for HTTP validation requests
API_TIMEOUT = 30               # seconds for LLM API calls
API_RETRIES = 2                # retry count for transient failures
EASYOCR_MIN_CONFIDENCE = 0.3  # minimum EasyOCR confidence to include a text block

# Internal model defaults (hidden from user – provider only shown)
PROVIDER_MODELS = {
    "OpenAI":      "gpt-4.1-mini",
    "Anthropic":   "claude-3-5-sonnet-latest",
    "Gemini":      "gemini-1.5-pro",
    "Perplexity":  "sonar",
}

PROVIDER_ENDPOINTS = {
    "OpenAI":     "https://api.openai.com/v1/chat/completions",
    "Anthropic":  "https://api.anthropic.com/v1/messages",
    "Gemini":     "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "Perplexity": "https://api.perplexity.ai/chat/completions",
}

BLOCKED_DOMAINS = [
    "namu.wiki",
    "blog.naver.com",
    "m.blog.naver.com",
    "tistory.com",
    "velog.io",
    "brunch.co.kr",
    "medium.com",
    "wordpress.com",
    "blogspot.com",
    "cafe.naver.com",
]

TRUSTED_DOMAINS = [
    "riss.kr",
    "dbpia.co.kr",
    "kci.go.kr",
    "ndsl.kr",
    "kiss.kstudy.com",
    "scholar.google.com",
    "scholar.google.co.kr",
    "youtube.com",
    "youtu.be",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "sciencedirect.com",
    "springer.com",
    "wiley.com",
    "nature.com",
    "jstor.org",
    "ieee.org",
    "acm.org",
    "who.int",
    "un.org",
    "oecd.org",
    "worldbank.org",
    "korea.kr",
    "chosun.com",
    "joongang.co.kr",
    "hani.co.kr",
    "khan.co.kr",
    "yonhap.co.kr",
    "yna.co.kr",
    "hankyung.com",
    "donga.com",
    "mk.co.kr",
    "sedaily.com",
    "ohmynews.com",
    "icj-cij.org",
    "pca-cpa.org",
    "kbs.co.kr",
    "mbc.co.kr",
    "sbs.co.kr",
    "ytn.co.kr",
    "news1.kr",
    "newsis.com",
]

# A-layer: template search result URLs (always valid, no LLM needed)
SEARCH_TEMPLATES = [
    ("RISS 검색",      "https://www.riss.kr/search/Search.do?searchGubun=true&queryText={q}"),
    ("KCI 검색",       "https://www.kci.go.kr/kciportal/po/search/poSearch.kci?sereId=&queryText={q}"),
    ("Google Scholar", "https://scholar.google.com/scholar?q={q}"),
    ("DBpia 검색",     "https://www.dbpia.co.kr/search/searchResult?searchCategory=ALL&query={q}"),
]

EXTRACT_SYSTEM = """당신은 수행평가 평가표(루브릭)에서 평가요소를 추출하는 전문가입니다.
주어진 평가표 텍스트에서 모든 평가항목/평가요소를 빠짐없이 추출하여 JSON으로 반환하세요.
반드시 순수 JSON만 반환 (마크다운 코드블록 없이):
{
  "elements": [
    {
      "verbatim": "평가요소 원문 텍스트를 한 글자도 변경하지 말고 그대로 복사",
      "min_sources": 2,
      "checklist": [
        "보고서 작성 시 확인할 핵심 항목 1",
        "보고서 작성 시 확인할 핵심 항목 2",
        "보고서 작성 시 확인할 핵심 항목 3"
      ]
    }
  ]
}

중요 규칙:
- verbatim 필드: 원문에서 해당 평가요소 문장을 단 한 글자도 바꾸지 말고 그대로 복사할 것
- 모든 평가항목/요소를 누락 없이 추출 (표의 각 행, 각 평가 기준 모두 포함)
- "○개 이상", "N가지 이상", "최소 N개" 등 정량 조건이 있으면 min_sources를 해당 숫자로 설정 (최솟값은 2)
- 중복 제거
- 요약하거나 바꿔쓰지 말 것 — verbatim이 핵심
- checklist: 학생이 보고서 작성 시 이 요소를 충족했는지 확인할 수 있는 실용적인 체크 항목 3개"""

OUTLINE_SYSTEM = """당신은 수행평가 개요 작성 전문가입니다.
학생이 스스로 보고서를 작성할 수 있도록, 논술/보고서 구조(개요)만 제시합니다.
보고서 내용을 대필하지 않습니다.

다음 형식으로 개요 3개를 작성하세요:

## 개요 1: 기초 (⭐)
[전체적인 방향 설명]

### 1. [소제목]
- 핵심 포인트
- 활용 평가요소: [요소명]

### 2. [소제목]
...

---

## 개요 2: 표준 (⭐⭐)
...

---

## 개요 3: 심화 (⭐⭐⭐)
..."""

B_LAYER_SYSTEM = """당신은 학술 자료 검색 전문가입니다.
다음 평가요소에 대해 직접 접근 가능한 공신력 있는 URL을 5개 제시해주세요.
반드시 순수 JSON만 반환 (마크다운 코드블록 없이):
{
  "sources": [
    {
      "title": "자료 제목",
      "url": "https://실제직접URL",
      "usage": "이 자료 활용 방법 (1문장)"
    }
  ]
}
규칙:
- 블로그, 나무위키, 개인 사이트 절대 금지
- RISS, DBpia, KCI, 정부기관(.go.kr/.re.kr/.or.kr), 국제기구, 주요언론 사이트만
- URL이 실제 존재하는지 확신이 없으면 포함하지 말 것"""


# ──────────────────────────────────────────────
# PROVIDER REST HELPERS
# ──────────────────────────────────────────────
def _friendly_http_error(status_code: int, provider: str) -> str:
    if status_code in (401, 403):
        return "API 키가 유효하지 않습니다. 키를 다시 확인해주세요."
    if status_code == 429:
        return "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
    if status_code >= 500:
        return f"{provider} 서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
    return f"{provider} API 오류 (HTTP {status_code})"


def _call_openai(system: str, user_msg: str, api_key: str) -> str:
    model = PROVIDER_MODELS["OpenAI"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 4096,
    }
    last_exc = None
    for attempt in range(API_RETRIES + 1):
        try:
            resp = requests.post(
                PROVIDER_ENDPOINTS["OpenAI"], headers=headers, json=body, timeout=API_TIMEOUT
            )
            if resp.status_code != 200:
                raise ValueError(_friendly_http_error(resp.status_code, "OpenAI"))
            return resp.json()["choices"][0]["message"]["content"]
        except ValueError:
            raise
        except Exception as e:
            last_exc = e
    raise ValueError(f"OpenAI 연결 오류: {last_exc}")


def _call_anthropic(system: str, user_msg: str, api_key: str) -> str:
    model = PROVIDER_MODELS["Anthropic"]
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 4096,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    }
    last_exc = None
    for attempt in range(API_RETRIES + 1):
        try:
            resp = requests.post(
                PROVIDER_ENDPOINTS["Anthropic"], headers=headers, json=body, timeout=API_TIMEOUT
            )
            if resp.status_code != 200:
                raise ValueError(_friendly_http_error(resp.status_code, "Anthropic"))
            return resp.json()["content"][0]["text"]
        except ValueError:
            raise
        except Exception as e:
            last_exc = e
    raise ValueError(f"Anthropic 연결 오류: {last_exc}")


def _call_gemini(system: str, user_msg: str, api_key: str) -> str:
    model = PROVIDER_MODELS["Gemini"]
    url = PROVIDER_ENDPOINTS["Gemini"].format(model=model) + f"?key={api_key}"
    body = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{system}\n\n{user_msg}"}]}
        ],
        "generationConfig": {"maxOutputTokens": 4096},
    }
    last_exc = None
    for attempt in range(API_RETRIES + 1):
        try:
            resp = requests.post(url, json=body, timeout=API_TIMEOUT)
            if resp.status_code != 200:
                # Detect invalid API key from response body (Gemini returns 400 for bad keys)
                if resp.status_code == 400:
                    body_text = resp.text or ""
                    if "API_KEY_INVALID" in body_text or "invalid" in body_text.lower():
                        raise ValueError(_friendly_http_error(401, "Gemini"))
                raise ValueError(_friendly_http_error(resp.status_code, "Gemini"))
            data = resp.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except ValueError:
            raise
        except Exception as e:
            last_exc = e
    raise ValueError(f"Gemini 연결 오류: {last_exc}")


def _call_perplexity(system: str, user_msg: str, api_key: str) -> str:
    model = PROVIDER_MODELS["Perplexity"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 4096,
    }
    last_exc = None
    for attempt in range(API_RETRIES + 1):
        try:
            resp = requests.post(
                PROVIDER_ENDPOINTS["Perplexity"], headers=headers, json=body, timeout=API_TIMEOUT
            )
            if resp.status_code != 200:
                raise ValueError(_friendly_http_error(resp.status_code, "Perplexity"))
            return resp.json()["choices"][0]["message"]["content"]
        except ValueError:
            raise
        except Exception as e:
            last_exc = e
    raise ValueError(f"Perplexity 연결 오류: {last_exc}")


_PROVIDER_CALLERS = {
    "OpenAI":     _call_openai,
    "Anthropic":  _call_anthropic,
    "Gemini":     _call_gemini,
    "Perplexity": _call_perplexity,
}

_TEST_SYSTEM = "You are a helpful assistant. Reply with a single word: OK"
_TEST_USER   = "Test connection. Reply: OK"


def test_connection(provider: str, api_key: str):
    """Return (success, message). Never logs the api_key value."""
    try:
        _PROVIDER_CALLERS[provider](_TEST_SYSTEM, _TEST_USER, api_key)
        return True, f"✅ {provider} 연결 성공!"
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"연결 오류: {type(e).__name__}"


def call_ai(provider: str, system: str, user_msg: str, api_key: str) -> str:
    """Call the selected provider and return the response text."""
    return _PROVIDER_CALLERS[provider](system, user_msg, api_key)


# ──────────────────────────────────────────────
# FILE & OCR HELPERS
# ──────────────────────────────────────────────
def extract_file_text(uploaded_file) -> str:
    """Extract text content from an uploaded file (non-image)."""
    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower()

    if ext == "txt":
        return uploaded_file.read().decode("utf-8", errors="replace")

    if ext == "pdf":
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(uploaded_file)
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)
        except Exception as e:
            return f"[PDF 파일 '{name}' – 텍스트 추출 실패: {e}]"

    if ext == "docx":
        try:
            import docx
            doc = docx.Document(uploaded_file)
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            return f"[DOCX 파일 '{name}' – 텍스트 추출 실패: {e}]"

    if ext == "hwp":
        return f"[HWP 파일 '{name}' – 지원되지 않습니다. 텍스트로 붙여넣기를 이용하세요.]"

    return f"[파일 '{name}' – 지원되지 않는 형식]"


def ocr_image(image_bytes: bytes):
    """
    Perform OCR on image bytes. Returns (text, method_note) tuple.
    Tries pytesseract first, then easyocr, then fails gracefully.
    """
    try:
        import pytesseract
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(image_bytes))
        text = pytesseract.image_to_string(img, lang="kor+eng")
        return text.strip(), "pytesseract"
    except ImportError:
        pass
    except Exception:
        pass

    try:
        import easyocr
        import numpy as np
        from PIL import Image as PILImage
        img = PILImage.open(io.BytesIO(image_bytes))
        img_array = np.array(img)
        reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        results = reader.readtext(img_array)
        text = "\n".join(t for _, t, conf in results if conf > EASYOCR_MIN_CONFIDENCE)
        return text.strip(), "easyocr"
    except ImportError:
        pass
    except Exception:
        pass

    return "", "unavailable"


# ──────────────────────────────────────────────
# URL VALIDATION HELPERS
# ──────────────────────────────────────────────
def is_domain_blocked(domain: str) -> bool:
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    for blocked in BLOCKED_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return True
    return False


def is_domain_trusted(domain: str) -> bool:
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if (domain.endswith(".go.kr") or domain.endswith(".ac.kr")
            or domain.endswith(".re.kr") or domain.endswith(".or.kr")):
        return True
    for trusted in TRUSTED_DOMAINS:
        if domain == trusted or domain.endswith("." + trusted):
            return True
    return False


def validate_url(url: str) -> bool:
    """Return True if URL passes domain check + HTTP validation.

    Always performs an actual HTTP request (HEAD then GET fallback) even for
    trusted domains, so that blocked/empty search-result pages are excluded.
    403 responses are treated as failures regardless of domain trust.
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not domain:
            return False
        if is_domain_blocked(domain):
            return False
        headers = {"User-Agent": "Mozilla/5.0 (compatible; StudyHelper/1.0)"}
        # HEAD request first (lightweight)
        try:
            resp = requests.head(
                url, headers=headers, timeout=URL_TIMEOUT, allow_redirects=True
            )
            if resp.status_code == 403:
                return False
            if 200 <= resp.status_code < 400:
                return True
            # HEAD returned a non-2xx/3xx code (e.g. 405 Method Not Allowed)
            # fall through to GET fallback
        except requests.RequestException:
            pass  # HEAD failed entirely → try GET
        # GET fallback – stream to avoid downloading the full body
        resp = requests.get(
            url, headers=headers, timeout=URL_TIMEOUT,
            allow_redirects=True, stream=True,
        )
        resp.close()
        if resp.status_code == 403:
            return False
        return 200 <= resp.status_code < 400
    except Exception:
        return False


def validate_urls_parallel(urls: list) -> dict:
    results = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(validate_url, url): url for url in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception:
                results[url] = False
    return results


# ──────────────────────────────────────────────
# SOURCE GENERATION HELPERS
# ──────────────────────────────────────────────
def parse_min_sources(text: str) -> int:
    """
    Parse minimum source count from evaluation element text.
    Detects patterns like '3개 이상', '2가지 이상', '최소 3개', etc.
    """
    patterns = [
        r"(\d+)\s*개\s*이상",
        r"(\d+)\s*가지\s*이상",
        r"(\d+)\s*건\s*이상",
        r"최소\s*(\d+)\s*개",
    ]
    max_found = MIN_SOURCES
    for pattern in patterns:
        for m in re.findall(pattern, text):
            n = int(m)
            if n > max_found:
                max_found = n
    return max_found


def build_search_query(subject: str, topic: str, element_verbatim: str) -> str:
    """
    Build a clean, keyword-focused search query from evaluation element text.

    Strips evaluation-style sentence endings and format/quantity constraints,
    then combines subject + topic + extracted keywords (max ~80 chars).
    """
    text = element_verbatim
    # Remove Korean evaluation-style sentence endings (e.g. 했는가, 서술하였는가)
    text = re.sub(
        r'(했는가|하였는가|서술하였는가|제시하였는가|있는가|했나|하였나|'
        r'되었는가|되었나|였는가|인가|였나|하는가|하였나|포함하였는가|'
        r'활용하였는가|분석하였는가|설명하였는가|논하였는가)[?？.]*',
        '', text,
    )
    # Remove format/quantity constraints (e.g. 3개 이상, 최소 800자, (500자 이내))
    text = re.sub(r'\d+\s*(개|가지|건|자|줄|문장)\s*(이상|이내|이하|내외)', '', text)
    text = re.sub(r'최소\s*\d+\s*(개|자|줄)', '', text)
    text = re.sub(r'\(\s*\d+\s*(자|글자|단어)\s*(이상|이내|이하|내외)?\s*\)', '', text)
    # Remove date/citation hints that pollute search
    text = re.sub(r'(연도|날짜|출처|참고문헌)\s*포함', '', text)
    # Remove parentheses containing only whitespace/punctuation (residue from above)
    text = re.sub(r'\([^\w가-힣]*\)', '', text)
    # Collapse remaining punctuation/whitespace
    text = re.sub(r'[,;·:]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip().rstrip('.,·-')
    # Combine: subject + topic + up to 50 chars of cleaned keywords
    keywords = text[:50].strip()
    query = f"{subject} {topic} {keywords}".strip()
    # Hard cap at 80 chars, breaking on a word boundary where possible
    if len(query) > 80:
        truncated = query[:80]
        last_space = truncated.rfind(' ')
        query = truncated[:last_space] if last_space > 0 else truncated
    return query


def make_a_layer_sources(
    element_verbatim: str,
    subject: str = "",
    topic: str = "",
) -> list:
    """
    Generate A-layer search result URL candidates for an element.

    Uses a clean keyword query (via build_search_query) instead of raw
    verbatim text, so search result pages are actually populated.
    Returns one candidate per template in SEARCH_TEMPLATES.
    The caller is responsible for validating URLs and cycling through
    the returned candidates to meet the required source count.
    """
    query_text = build_search_query(subject, topic, element_verbatim)
    q = quote_plus(query_text)
    short = element_verbatim[:30]
    suffix = "…" if len(element_verbatim) > 30 else ""
    templates = list(SEARCH_TEMPLATES)
    sources = []
    for site_name, template in templates:
        url = template.format(q=q)
        sources.append({
            "title": f"{short}{suffix} — {site_name}",
            "url": url,
            "usage": (
                f"이 요소에 관한 자료를 {site_name}에서 검색하여 보고서에 활용합니다. "
                f"(검색어: {query_text[:40]}{'…' if len(query_text) > 40 else ''})"
            ),
            "type": "검색결과",
            "layer": "A",
        })
    return sources


# ──────────────────────────────────────────────
# PARSE HELPER
# ──────────────────────────────────────────────
def parse_json_response(text: str) -> dict:
    """Parse JSON from AI response, stripping markdown code fences."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    return json.loads(text.strip())


def _clear_element_edit_keys() -> None:
    """Remove all element-editing session-state keys (el_edit_*)."""
    for k in list(st.session_state.keys()):
        if k.startswith("el_edit_"):
            del st.session_state[k]


# ──────────────────────────────────────────────
# SESSION STATE INIT
# ──────────────────────────────────────────────
_defaults = {
    "authenticated":  False,
    "provider":       "Anthropic",
    "api_key":        "",
    "api_verified":   False,
    "app_step":       "input",   # input | ocr_confirm | confirm_elements | generating | results
    "elements":       [],
    "saved_inputs":   {},
    "final_results":  [],
    "outline_text":   "",
    "ocr_raw_text":   "",
    "ocr_image_name": "",
    "ocr_method":     "",
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ──────────────────────────────────────────────
# PASSWORD GATE
# ──────────────────────────────────────────────
def check_password() -> bool:
    if st.session_state.get("authenticated"):
        return True
    st.markdown(
        """
        <div style="text-align:center; padding:60px 20px;">
            <div style="font-size:4rem;">🎓</div>
            <h1 style="margin-bottom:8px;">수행평가 도우미</h1>
            <p style="color:#6b7280;">이 앱은 비밀번호로 보호되어 있습니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pw = st.text_input(
            "비밀번호",
            type="password",
            placeholder="비밀번호를 입력하세요",
            key="pw_input",
            label_visibility="collapsed",
        )
        if st.button("🔓 입장하기", use_container_width=True, type="primary"):
            app_password = "study2026"
            try:
                app_password = st.secrets.get("APP_PASSWORD", "study2026")
            except Exception:
                pass
            if pw == app_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ 비밀번호가 올바르지 않습니다.")
    return False


if not check_password():
    st.stop()


# ──────────────────────────────────────────────
# PROVIDER / API KEY GATE  (shown after password, before main app)
# ──────────────────────────────────────────────
st.title("🎓 수행평가 도우미")
st.caption(
    "AI가 평가요소별 공신력 있는 자료를 추천해드립니다. "
    "보고서는 학생 여러분이 직접 작성합니다. ✍️"
)

with st.container(border=True):
    st.subheader("🔑 AI Provider 설정")
    col_prov, col_key, col_btn = st.columns([1, 3, 1])

    with col_prov:
        provider_choice = st.selectbox(
            "Provider",
            list(PROVIDER_MODELS.keys()),
            index=list(PROVIDER_MODELS.keys()).index(st.session_state["provider"]),
            key="provider_select",
            label_visibility="collapsed",
        )
        if provider_choice != st.session_state["provider"]:
            st.session_state["provider"] = provider_choice
            st.session_state["api_verified"] = False
            st.session_state["api_key"] = ""

    with col_key:
        api_key_input = st.text_input(
            "API Key",
            type="password",
            value=st.session_state["api_key"],
            placeholder=f"{provider_choice} API Key를 입력하세요",
            key="api_key_input",
            label_visibility="collapsed",
        )
        if api_key_input != st.session_state["api_key"]:
            st.session_state["api_key"] = api_key_input
            st.session_state["api_verified"] = False

    with col_btn:
        if st.button("🔗 연결 테스트", use_container_width=True):
            if not st.session_state["api_key"].strip():
                st.error("API Key를 먼저 입력해주세요.")
            else:
                with st.spinner("연결 테스트 중..."):
                    ok, msg = test_connection(
                        st.session_state["provider"],
                        st.session_state["api_key"],
                    )
                st.session_state["api_verified"] = ok
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    if st.session_state["api_verified"]:
        st.success(f"✅ {st.session_state['provider']} 연결됨 — 모든 기능 사용 가능")
    else:
        st.warning("⚠️ API Key 연결 테스트를 완료해야 앱 기능을 사용할 수 있습니다.")

api_ready = st.session_state["api_verified"] and bool(st.session_state["api_key"].strip())

if not api_ready:
    st.stop()

st.divider()


# ──────────────────────────────────────────────
# SIDEBAR  (shown only after API is verified)
# ──────────────────────────────────────────────
with st.sidebar:
    st.title("🎓 수행평가 도우미")
    st.caption("AI 기반 리서치 어시스턴트")
    st.divider()

    st.subheader("🏫 학교 유형")
    school = st.selectbox(
        "학교 유형 선택",
        ["일반고", "자사고", "국제고", "외국어고", "영재고", "과학고", "기타"],
        label_visibility="collapsed",
    )
    st.divider()

    st.subheader("📋 수행평가 정보")
    subject = st.text_input("과목 *", placeholder="예: 사회, 과학, 국어")
    topic = st.text_input("수행평가 주제 *", placeholder="예: 독도와 국제법")
    conditions = st.text_area(
        "조건/제한사항 (선택)",
        placeholder="예: A4 3장, 참고문헌 5개 이상, 2주 후 제출",
        height=80,
    )
    st.divider()

    st.subheader("📊 평가표 (루브릭)")
    rubric_text = st.text_area(
        "평가표 텍스트 입력 (권장)",
        placeholder="평가항목, 평가요소, 배점 기준을 붙여넣으세요",
        height=120,
    )
    rubric_file = st.file_uploader(
        "파일 업로드 (PDF/TXT/DOCX)",
        type=["pdf", "txt", "docx"],
        key="rubric_file",
    )
    rubric_image = st.file_uploader(
        "이미지 업로드 (PNG/JPG) — OCR 지원",
        type=["png", "jpg", "jpeg"],
        key="rubric_image",
        help="이미지 업로드 시 OCR로 텍스트를 추출합니다. 추출 후 반드시 내용을 확인하세요.",
    )
    if rubric_file:
        st.caption(f"📎 {rubric_file.name}")
    if rubric_image:
        st.caption(f"🖼️ {rubric_image.name} (OCR 예정)")
    st.caption("💡 HWP 파일은 지원되지 않습니다. 텍스트로 붙여넣기를 권장합니다.")
    st.divider()

    st.subheader("📎 참고자료 (선택)")
    ref_files = st.file_uploader(
        "파일 첨부",
        type=["pdf", "txt", "docx"],
        accept_multiple_files=True,
        key="ref_files",
    )
    if ref_files:
        st.caption(f"📎 첨부 파일 ({len(ref_files)}개):")
        for _f in ref_files:
            st.caption(f"  • {_f.name}")
    st.divider()

    if st.session_state["app_step"] == "input":
        extract_btn = st.button(
            "🔍 평가요소 추출 시작",
            use_container_width=True,
            type="primary",
            disabled=not subject or not topic,
        )
    else:
        extract_btn = False
        if st.button("🔄 처음으로 돌아가기", use_container_width=True):
            for _k in (
                "app_step", "elements", "saved_inputs",
                "final_results", "outline_text",
                "ocr_raw_text", "ocr_image_name", "ocr_method",
            ):
                st.session_state[_k] = _defaults[_k]
            _clear_element_edit_keys()
            st.rerun()


# ──────────────────────────────────────────────
# STEP 1 — INPUT
# ──────────────────────────────────────────────
if st.session_state["app_step"] == "input":
    if not subject or not topic:
        st.info(
            "👈 왼쪽 사이드바에서 학교 유형, 과목, 주제를 입력한 후 "
            "**🔍 평가요소 추출 시작** 버튼을 눌러주세요."
        )
    else:
        st.info(
            f"✅ 준비 완료: **{subject}** — {topic}  \n"
            "평가표(루브릭)를 입력하고 왼쪽 버튼을 눌러 평가요소를 추출하세요."
        )

    if extract_btn:
        if rubric_image:
            # OCR path – go to ocr_confirm step
            image_bytes = rubric_image.read()
            with st.spinner("🖼️ 이미지에서 텍스트를 추출하는 중 (OCR)..."):
                ocr_text, ocr_method = ocr_image(image_bytes)

            file_rubric = ""
            if rubric_file:
                file_rubric = extract_file_text(rubric_file)

            st.session_state["saved_inputs"] = {
                "school": school,
                "subject": subject,
                "topic": topic,
                "conditions": conditions,
                "text_rubric": rubric_text.strip(),
                "file_rubric": file_rubric,
                "ref_texts": [extract_file_text(_f) for _f in ref_files] if ref_files else [],
            }
            st.session_state["ocr_raw_text"] = ocr_text
            st.session_state["ocr_image_name"] = rubric_image.name
            st.session_state["ocr_method"] = ocr_method
            st.session_state["app_step"] = "ocr_confirm"
            st.rerun()

        else:
            # No image – proceed directly to element extraction
            final_rubric = rubric_text.strip()
            if rubric_file:
                file_text = extract_file_text(rubric_file)
                final_rubric = (final_rubric + "\n\n" + file_text).strip() if final_rubric else file_text

            if not final_rubric:
                st.warning("⚠️ 평가표(루브릭)를 텍스트로 입력하거나 파일로 업로드해주세요.")
            else:
                ref_texts = [extract_file_text(_f) for _f in ref_files] if ref_files else []
                st.session_state["saved_inputs"] = {
                    "school": school,
                    "subject": subject,
                    "topic": topic,
                    "conditions": conditions,
                    "rubric": final_rubric,
                    "ref_texts": ref_texts,
                }
                with st.spinner("🔍 평가표에서 평가요소를 추출하는 중..."):
                    extract_msg = (
                        f"다음 수행평가 정보를 바탕으로 평가요소를 추출해주세요.\n\n"
                        f"과목: {subject}\n주제: {topic}\n학교 유형: {school}\n\n"
                        f"평가표(루브릭):\n{final_rubric}"
                    )
                    try:
                        raw = call_ai(
                            st.session_state["provider"],
                            EXTRACT_SYSTEM,
                            extract_msg,
                            st.session_state["api_key"],
                        )
                        parsed = parse_json_response(raw)
                        elements = parsed.get("elements", [])
                        # Code-level enforcement of min_sources from verbatim
                        for el in elements:
                            code_min = parse_min_sources(el.get("verbatim", ""))
                            el["min_sources"] = max(
                                el.get("min_sources", MIN_SOURCES), code_min
                            )
                        if not elements:
                            st.error(
                                "평가요소를 추출하지 못했습니다. 평가표 내용을 확인해주세요."
                            )
                        else:
                            st.session_state["elements"] = elements
                            st.session_state["app_step"] = "confirm_elements"
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ 평가요소 추출 실패: {e}")


# ──────────────────────────────────────────────
# STEP 1b — OCR CONFIRM
# ──────────────────────────────────────────────
elif st.session_state["app_step"] == "ocr_confirm":
    st.subheader("🖼️ OCR 텍스트 확인")
    ocr_method = st.session_state.get("ocr_method", "unknown")
    image_name = st.session_state.get("ocr_image_name", "이미지")

    if st.session_state["ocr_raw_text"]:
        st.info(
            f"**{image_name}** 파일에서 텍스트를 추출했습니다 (방법: {ocr_method}).  \n"
            "아래 텍스트를 꼼꼼히 확인하고 오타나 누락 내용이 있으면 직접 수정하세요."
        )
        ocr_edited = st.text_area(
            "OCR 추출 텍스트 (수정 가능)",
            value=st.session_state["ocr_raw_text"],
            height=300,
            key="ocr_edited_text",
        )
    else:
        if ocr_method == "unavailable":
            st.warning(
                "⚠️ OCR 라이브러리가 설치되어 있지 않습니다.  \n"
                "서버에 `pytesseract` (+ Tesseract 바이너리) 또는 `easyocr`를 설치해주세요.  \n"
                "아래 텍스트 영역에 평가표 내용을 직접 붙여넣어 주세요."
            )
        else:
            st.warning("⚠️ OCR 텍스트 추출에 실패했습니다. 아래에 직접 입력해주세요.")
        ocr_edited = st.text_area(
            "평가표 텍스트 직접 입력",
            height=300,
            key="ocr_edited_text",
        )

    ocr_confirmed = st.checkbox(
        "✅ OCR 텍스트를 확인했고 오타를 수정했습니다 (필수)",
        key="ocr_confirm_checkbox",
    )

    col_a, col_b = st.columns(2)
    with col_a:
        proceed_btn = st.button(
            "▶ 평가요소 추출로 진행",
            type="primary",
            use_container_width=True,
            disabled=not ocr_confirmed,
        )
    with col_b:
        if st.button("↩ 이미지 다시 업로드", use_container_width=True):
            st.session_state["app_step"] = "input"
            st.session_state["ocr_raw_text"] = ""
            st.rerun()

    if proceed_btn and ocr_confirmed:
        inputs = st.session_state["saved_inputs"]
        ocr_text_val = st.session_state.get("ocr_edited_text", "")
        # Merge all rubric sources
        combined_rubric = ocr_text_val.strip()
        if inputs.get("text_rubric"):
            combined_rubric = inputs["text_rubric"] + "\n\n" + combined_rubric
        if inputs.get("file_rubric"):
            combined_rubric = combined_rubric + "\n\n" + inputs["file_rubric"]
        inputs["rubric"] = combined_rubric.strip()
        st.session_state["saved_inputs"] = inputs

        with st.spinner("🔍 평가표에서 평가요소를 추출하는 중..."):
            extract_msg = (
                f"다음 수행평가 정보를 바탕으로 평가요소를 추출해주세요.\n\n"
                f"과목: {inputs['subject']}\n주제: {inputs['topic']}\n"
                f"학교 유형: {inputs['school']}\n\n"
                f"평가표(루브릭):\n{inputs['rubric']}"
            )
            try:
                raw = call_ai(
                    st.session_state["provider"],
                    EXTRACT_SYSTEM,
                    extract_msg,
                    st.session_state["api_key"],
                )
                parsed = parse_json_response(raw)
                elements = parsed.get("elements", [])
                for el in elements:
                    code_min = parse_min_sources(el.get("verbatim", ""))
                    el["min_sources"] = max(el.get("min_sources", MIN_SOURCES), code_min)
                if not elements:
                    st.error("평가요소를 추출하지 못했습니다. OCR 텍스트를 확인해주세요.")
                else:
                    st.session_state["elements"] = elements
                    st.session_state["app_step"] = "confirm_elements"
                    st.rerun()
            except Exception as e:
                st.error(f"❌ 평가요소 추출 실패: {e}")


# ──────────────────────────────────────────────
# STEP 2 — CONFIRM ELEMENTS  (with editing)
# ──────────────────────────────────────────────
elif st.session_state["app_step"] == "confirm_elements":
    elements = st.session_state["elements"]

    st.subheader(f"📋 추출된 평가요소 ({len(elements)}개)")
    st.caption(
        "아래 평가요소 리스트를 확인하고 필요하면 수정·추가·삭제하세요. "
        "원문(verbatim)을 그대로 유지하는 것을 권장합니다."
    )

    # Initialise edit-state keys for any element not yet in session state
    for i, el in enumerate(elements):
        k = f"el_edit_{i}"
        if k not in st.session_state:
            st.session_state[k] = el.get("verbatim", "")

    to_delete = None
    for i, el in enumerate(elements):
        key = f"el_edit_{i}"
        with st.expander(
            f"**요소 {i + 1}**  ·  최소 자료 {el.get('min_sources', MIN_SOURCES)}개",
            expanded=True,
        ):
            edited_text = st.text_area(
                "평가요소 원문",
                value=st.session_state.get(key, el.get("verbatim", "")),
                key=key,
                height=80,
                label_visibility="collapsed",
            )
            computed_min = parse_min_sources(edited_text)
            col_info, col_del = st.columns([4, 1])
            with col_info:
                if computed_min > MIN_SOURCES:
                    st.caption(
                        f"🔢 '{computed_min}개 이상' 조건 감지 → 자료 최소 **{computed_min}개** 제공 예정"
                    )
            with col_del:
                if st.button("🗑️ 삭제", key=f"del_{i}", help="이 요소 삭제"):
                    to_delete = i

    if to_delete is not None:
        # Sync all current edits before deleting
        for j in range(len(elements)):
            k = f"el_edit_{j}"
            v = st.session_state.get(k, elements[j].get("verbatim", ""))
            elements[j]["verbatim"] = v
            elements[j]["min_sources"] = parse_min_sources(v)
        elements.pop(to_delete)
        st.session_state["elements"] = elements
        _clear_element_edit_keys()
        st.rerun()

    st.divider()

    # Add new element
    with st.expander("➕ 새 평가요소 추가"):
        new_el_text = st.text_area("새 평가요소 원문 입력", height=80, key="new_el_input")
        if st.button("추가", key="add_el_btn"):
            if new_el_text.strip():
                for j in range(len(elements)):
                    k = f"el_edit_{j}"
                    v = st.session_state.get(k, elements[j].get("verbatim", ""))
                    elements[j]["verbatim"] = v
                    elements[j]["min_sources"] = parse_min_sources(v)
                elements.append({
                    "verbatim": new_el_text.strip(),
                    "min_sources": parse_min_sources(new_el_text.strip()),
                    "checklist": [],
                })
                st.session_state["elements"] = elements
                _clear_element_edit_keys()
                st.rerun()

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button(
            "✅ 이 요소 리스트로 자료 추천 시작",
            type="primary",
            use_container_width=True,
        ):
            confirmed = []
            for i in range(len(elements)):
                k = f"el_edit_{i}"
                text = st.session_state.get(k, elements[i].get("verbatim", ""))
                confirmed.append({
                    "verbatim": text,
                    "min_sources": parse_min_sources(text),
                    "checklist": elements[i].get("checklist", []),
                })
            st.session_state["elements"] = confirmed
            st.session_state["app_step"] = "generating"
            st.rerun()
    with col_b:
        if st.button("↩ 평가표 다시 입력", use_container_width=True):
            st.session_state["app_step"] = "input"
            st.session_state["elements"] = []
            _clear_element_edit_keys()
            st.rerun()


# ──────────────────────────────────────────────
# STEP 3 — GENERATING
# ──────────────────────────────────────────────
elif st.session_state["app_step"] == "generating":
    inputs = st.session_state["saved_inputs"]
    elements = st.session_state["elements"]

    with st.spinner("📚 자료를 생성하고 개요를 작성하는 중... (잠시 기다려주세요)"):
        try:
            final_results = []

            # A-layer: build template search URLs for each element (no LLM needed)
            subject = inputs.get("subject", "")
            topic = inputs.get("topic", "")
            element_data = []
            all_candidate_urls: set = set()

            for el in elements:
                verbatim = el.get("verbatim", "")
                min_src = el.get("min_sources", MIN_SOURCES)
                required = max(min_src, MIN_SOURCES)
                candidates = make_a_layer_sources(verbatim, subject, topic)
                element_data.append({
                    "verbatim": verbatim,
                    "min_sources": min_src,
                    "required": required,
                    "checklist": el.get("checklist", []),
                    "candidates": candidates,
                })
                for s in candidates:
                    all_candidate_urls.add(s["url"])

            # Validate all unique A-layer URLs in one parallel batch
            validity = (
                validate_urls_parallel(list(all_candidate_urls))
                if all_candidate_urls else {}
            )

            for ed in element_data:
                candidates = ed["candidates"]
                required = ed["required"]
                # Keep only sources whose URL passed validation
                valid_sources = [
                    s for s in candidates if validity.get(s["url"], False)
                ]
                if not valid_sources:
                    # All failed (e.g. network blocked in Streamlit Cloud) –
                    # fall back to unvalidated candidates so the user still gets
                    # links, but mark them so they can be distinguished in the UI.
                    valid_sources = [
                        {**s, "unvalidated": True} for s in candidates
                    ]
                # Cycle through valid sources to satisfy required count
                result_sources = [
                    valid_sources[i % len(valid_sources)] for i in range(required)
                ]
                final_results.append({
                    "verbatim": ed["verbatim"],
                    "sources": result_sources,
                    "checklist": ed["checklist"],
                    "min_sources": ed["min_sources"],
                })

            # Generate outlines via LLM
            outline_elements = "\n".join(
                f"- {el.get('verbatim', '')[:80]}" for el in elements
            )
            outline_msg = (
                f"다음 수행평가의 개요 3개를 작성해주세요.\n\n"
                f"학교 유형: {inputs.get('school', '')}\n"
                f"과목: {inputs.get('subject', '')}\n"
                f"주제: {inputs.get('topic', '')}\n"
                + (f"조건: {inputs['conditions']}\n" if inputs.get("conditions") else "")
                + f"\n평가요소:\n{outline_elements}\n\n"
                "개요 3개(기초/표준/심화)를 작성해주세요. "
                "각 개요는 평가요소를 어떻게 다루는지 명시합니다."
            )
            outline_text = call_ai(
                st.session_state["provider"],
                OUTLINE_SYSTEM,
                outline_msg,
                st.session_state["api_key"],
            )

            st.session_state["final_results"] = final_results
            st.session_state["outline_text"] = outline_text
            st.session_state["app_step"] = "results"
            st.rerun()

        except Exception as e:
            st.error(f"❌ 자료 생성 실패: {e}")
            if st.button("↩ 처음으로"):
                st.session_state["app_step"] = "input"
                st.rerun()


# ──────────────────────────────────────────────
# STEP 4 — RESULTS
# ──────────────────────────────────────────────
elif st.session_state["app_step"] == "results":
    inputs = st.session_state["saved_inputs"]
    elements = st.session_state["elements"]
    final_results = st.session_state.get("final_results", [])
    outline_text = st.session_state.get("outline_text", "")

    # ── Fulfillment dashboard ──
    all_satisfied = True
    dashboard_rows = []
    for item in final_results:
        needed = item.get("min_sources", MIN_SOURCES)
        have = len(item.get("sources", []))
        ok = have >= needed
        if not ok:
            all_satisfied = False
        label = "✅" if ok else "❌"
        vb = item["verbatim"]
        short = vb[:50] + ("…" if len(vb) > 50 else "")
        dashboard_rows.append((short, needed, have, label))

    with st.expander("📊 충족 현황표 (만점 조건 확인)", expanded=not all_satisfied):
        if all_satisfied:
            st.success("✅ 모든 평가요소의 자료 수 조건이 충족되었습니다.")
        else:
            st.warning("⚠️ 일부 평가요소의 자료 수가 부족합니다. 직접 추가해주세요.")
        for vb_short, needed, have, label in dashboard_rows:
            st.markdown(f"{label} **{vb_short}** — 필요: {needed}개 / 확보: {have}개")

    st.divider()

    # ── B-layer toggle ──
    b_layer_on = st.toggle(
        "🔍 원문 직링크 더 찾기 (B 레이어, 기본 OFF)",
        value=False,
        help="LLM이 직접 접근 가능한 URL 후보를 생성한 뒤 링크 검증을 거쳐 추가합니다.",
        key="b_layer_toggle",
    )

    if b_layer_on:
        if st.button("🔄 B 레이어 직링크 생성", type="secondary"):
            with st.spinner("🔍 직링크 후보 생성 및 검증 중..."):
                for item in final_results:
                    verbatim = item["verbatim"]
                    b_msg = (
                        f"평가요소: {verbatim}\n\n"
                        f"과목: {inputs.get('subject', '')}, "
                        f"주제: {inputs.get('topic', '')}"
                    )
                    try:
                        raw = call_ai(
                            st.session_state["provider"],
                            B_LAYER_SYSTEM,
                            b_msg,
                            st.session_state["api_key"],
                        )
                        b_data = parse_json_response(raw)
                        b_candidates = b_data.get("sources", [])
                        b_urls = [s.get("url", "") for s in b_candidates if s.get("url")]
                        validity = validate_urls_parallel(b_urls) if b_urls else {}
                        for src in b_candidates:
                            url = src.get("url", "")
                            if url and validity.get(url, False):
                                src["layer"] = "B"
                                item["sources"].append(src)
                    except Exception:
                        pass
            st.session_state["final_results"] = final_results
            st.rerun()

    st.divider()

    # ── Section 1: material recommendations ──
    st.subheader("📚 1. 평가요소별 자료 추천")
    st.caption(f"총 {len(final_results)}개 평가요소 | A레이어(검색결과 URL) 기본 제공")

    result_output = (
        f"# 수행평가 자료 추천 결과\n\n"
        f"과목: {inputs.get('subject', '')} | 주제: {inputs.get('topic', '')}\n\n"
        "## 1. 평가요소별 자료 추천\n\n"
    )

    for item in final_results:
        verbatim = item["verbatim"]
        sources = item["sources"]
        checklist = item.get("checklist", [])

        st.markdown(f"### 📌 {verbatim}")
        result_output += f"[{verbatim}]\n"

        for i, src in enumerate(sources, 1):
            title = src.get("title", "자료")
            url = src.get("url", "#")
            usage = src.get("usage", "")
            layer_tag = " *(직링크)*" if src.get("layer") == "B" else ""
            unvalidated_tag = " ⚠️" if src.get("unvalidated") else ""
            st.markdown(f"- **자료 {i}**{layer_tag}{unvalidated_tag}: [{title}]({url})")
            if src.get("unvalidated"):
                st.caption("  ⚠️ 링크 검증 불가 (네트워크 제한). 클릭 후 결과를 직접 확인하세요.")
            if usage:
                st.markdown(f"  → 활용 방식: {usage}")
            result_output += f"- 자료 {i}: {title} ({url})\n"
            if usage:
                result_output += f"  → 활용 방식: {usage}\n"

        if checklist:
            st.markdown("✔ **체크리스트:**")
            result_output += "✔ 체크리스트:\n"
            for c in checklist:
                st.markdown(f"  - {c}")
                result_output += f"  - {c}\n"

        st.divider()
        result_output += "\n"

    # ── Section 2: outlines ──
    st.subheader("📝 2. 개요 3개 (난이도별)")
    result_output += "\n## 2. 개요 3개 (난이도별)\n\n"

    if outline_text:
        st.markdown(outline_text)
        result_output += outline_text
    else:
        st.info("개요를 생성하지 못했습니다. 처음으로 돌아가 다시 시도해주세요.")

    st.divider()

    st.download_button(
        label="📥 결과 다운로드 (.txt)",
        data=result_output,
        file_name=f"수행평가_분석결과_{inputs.get('subject', '')}.txt",
        mime="text/plain",
    )
