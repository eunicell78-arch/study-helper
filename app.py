import streamlit as st
import anthropic
import requests
import json
import re
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
MODEL = "claude-sonnet-4-20250514"
MIN_SOURCES = 2          # default minimum sources per evaluation element
URL_TIMEOUT = 3          # seconds for HTTP validation requests

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

FALLBACK_TEMPLATES = [
    ("RISS 검색", "https://www.riss.kr/search/Search.do?searchGubun=true&queryText={q}"),
    ("YouTube 검색", "https://www.youtube.com/results?search_query={q}"),
    ("Google Scholar", "https://scholar.google.com/scholar?q={q}"),
    ("DBpia 검색", "https://www.dbpia.co.kr/search/searchResult?searchCategory=ALL&query={q}"),
]

EXTRACT_SYSTEM = """당신은 수행평가 평가표(루브릭)에서 평가요소를 추출하는 전문가입니다.
주어진 평가표 텍스트에서 모든 평가항목/평가요소를 빠짐없이 추출하여 JSON으로 반환하세요.
반드시 순수 JSON만 반환 (마크다운 코드블록 없이):
{
  "elements": [
    {
      "name": "평가요소 이름 (간결하게)",
      "description": "이 요소가 평가하는 내용 (1~2문장)",
      "min_sources": 2
    }
  ]
}

주의사항:
- 모든 평가항목/요소를 누락 없이 추출
- "○개 이상", "N가지 이상" 등 정량 조건이 있으면 min_sources를 해당 숫자로 설정 (최솟값은 2)
- 중복 제거
- 평가요소 이름은 30자 이내"""

MATERIAL_SYSTEM = """당신은 수행평가 자료 추천 전문가입니다.
각 평가요소에 대해 공신력 있는 자료를 추천합니다.
반드시 순수 JSON만 반환 (마크다운 코드블록 없이):
{
  "results": [
    {
      "element_name": "평가요소 이름",
      "sources": [
        {
          "title": "자료 제목",
          "url": "https://실제URL",
          "usage": "이 자료를 보고서에서 어떻게 활용할지 (1문장)",
          "type": "논문/기사/공공기관/유튜브/국제기구/기타"
        }
      ],
      "checklist": [
        "체크리스트 항목 1",
        "체크리스트 항목 2",
        "체크리스트 항목 3"
      ]
    }
  ]
}

규칙:
- 블로그, 나무위키, 개인 사이트 URL 절대 금지
- 사용 가능한 도메인: RISS(riss.kr), DBpia(dbpia.co.kr), KCI(kci.go.kr), 정부기관(.go.kr/.re.kr/.or.kr), 주요언론사, 유튜브, 국제기구
- 검색 결과 페이지 URL도 허용 (예: riss.kr/search/..., youtube.com/results?...)
- 각 요소마다 자료 유형을 다양하게 혼합 (논문+기사+공공기관+유튜브 등)
- 요소당 최소 요청된 개수 이상 제시
- 체크리스트는 해당 요소를 보고서에 반영할 때 확인해야 할 핵심 포인트 3개"""

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


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def get_secret(key: str, default: str = "") -> str:
    """Read from st.secrets, fall back to default if key is missing."""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default


def check_password() -> bool:
    """Show password screen and return True once authenticated."""
    if st.session_state.get("authenticated"):
        return True

    st.markdown(
        """
        <div style="text-align:center; padding: 60px 20px;">
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
            app_password = get_secret("APP_PASSWORD", "study2026")
            if pw == app_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ 비밀번호가 올바르지 않습니다.")
    return False


def extract_file_text(uploaded_file) -> str:
    """Extract text content from an uploaded file."""
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

    if ext in ("png", "jpg", "jpeg"):
        return f"[이미지 파일 '{name}' – 텍스트 추출 불가. 평가표 내용을 직접 텍스트로 붙여넣기 해주세요.]"

    return f"[파일 '{name}' – 지원되지 않는 형식]"


def is_domain_blocked(domain: str) -> bool:
    """Return True if the domain is on the blocked list."""
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    for blocked in BLOCKED_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return True
    return False


def is_domain_trusted(domain: str) -> bool:
    """Return True if the domain is trusted (skip HTTP check)."""
    domain = domain.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    # Korean government, academic, public institutions
    if (domain.endswith(".go.kr") or domain.endswith(".ac.kr")
            or domain.endswith(".re.kr") or domain.endswith(".or.kr")):
        return True
    for trusted in TRUSTED_DOMAINS:
        if domain == trusted or domain.endswith("." + trusted):
            return True
    return False


def validate_url(url: str) -> bool:
    """Return True if the URL is acceptable to display."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if not domain:
            return False
        if is_domain_blocked(domain):
            return False
        if is_domain_trusted(domain):
            return True
        headers = {"User-Agent": "Mozilla/5.0 (compatible; StudyHelper/1.0)"}
        resp = requests.head(url, headers=headers, timeout=URL_TIMEOUT, allow_redirects=True)
        return 200 <= resp.status_code < 400
    except Exception:
        return False


def validate_urls_parallel(urls: list) -> dict:
    """Validate multiple URLs in parallel, return {url: is_valid}."""
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


def make_fallback_sources(element_name: str, count: int) -> list:
    """Generate fallback search result sources for an element."""
    q = quote_plus(element_name)
    sources = []
    for i, (site_name, template) in enumerate(FALLBACK_TEMPLATES):
        if i >= count:
            break
        url = template.format(q=q)
        sources.append({
            "title": f"{element_name} — {site_name}",
            "url": url,
            "usage": f"{element_name}에 관한 자료를 {site_name}에서 검색하여 활용합니다.",
            "type": "검색결과",
        })
    return sources


def call_ai(client: anthropic.Anthropic, system: str, user_msg: str) -> str:
    """Call AI and return full response text (non-streaming)."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    return response.content[0].text


def stream_ai(client: anthropic.Anthropic, system: str, user_msg: str,
              container=None) -> str:
    """Stream AI response, display progressively, and return full text."""
    full_text = ""
    placeholder = (container or st).empty()
    with client.messages.stream(
        model=MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
            placeholder.markdown(full_text + "▌")
    placeholder.markdown(full_text)
    return full_text


def parse_json_response(text: str) -> dict:
    """Parse JSON from AI response, stripping any markdown code fences."""
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    return json.loads(text.strip())


# ──────────────────────────────────────────────
# SESSION STATE INIT
# ──────────────────────────────────────────────
_defaults = {
    "authenticated": False,
    "app_step": "input",   # "input" | "confirm_elements" | "generating" | "results"
    "elements": [],
    "saved_inputs": {},
    "final_results": [],
    "outline_text": "",
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ──────────────────────────────────────────────
# PASSWORD GATE
# ──────────────────────────────────────────────
if not check_password():
    st.stop()


# ──────────────────────────────────────────────
# LOAD ANTHROPIC CLIENT
# ──────────────────────────────────────────────
api_key = get_secret("ANTHROPIC_API_KEY")
if not api_key:
    st.error(
        "⚠️ Anthropic API 키가 설정되지 않았습니다. "
        "Streamlit Secrets에서 `ANTHROPIC_API_KEY`를 설정해주세요."
    )
    st.stop()

client = anthropic.Anthropic(api_key=api_key)


# ──────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────
with st.sidebar:
    st.title("🎓 수행평가 도우미")
    st.caption("AI 기반 리서치 어시스턴트")
    st.divider()

    # School type
    st.subheader("🏫 학교 유형")
    school = st.selectbox(
        "학교 유형 선택",
        ["일반고", "자사고", "국제고", "외국어고", "영재고", "과학고", "기타"],
        label_visibility="collapsed",
    )
    st.divider()

    # Assignment info
    st.subheader("📋 수행평가 정보")
    subject = st.text_input("과목 *", placeholder="예: 사회, 과학, 국어")
    topic = st.text_input("수행평가 주제 *", placeholder="예: 독도와 국제법")
    conditions = st.text_area(
        "조건/제한사항 (선택)",
        placeholder="예: A4 3장, 참고문헌 5개 이상, 2주 후 제출",
        height=80,
    )
    st.divider()

    # Rubric / evaluation chart
    st.subheader("📊 평가표 (루브릭)")
    rubric_text = st.text_area(
        "평가표 텍스트 입력 (권장)",
        placeholder="평가항목, 평가요소, 배점 기준을 붙여넣으세요",
        height=120,
    )
    rubric_file = st.file_uploader(
        "또는 파일 업로드 (PDF/TXT/DOCX)",
        type=["pdf", "txt", "docx"],
        key="rubric_file",
        help="HWP, 이미지(PNG/JPG)는 텍스트 추출이 어렵습니다. 텍스트로 붙여넣기를 권장합니다.",
    )
    if rubric_file:
        st.caption(f"📎 {rubric_file.name}")
    st.divider()

    # Reference materials – file upload only
    st.subheader("📎 참고자료 (선택)")
    ref_files = st.file_uploader(
        "파일 첨부",
        type=["pdf", "txt", "docx", "hwp", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="ref_files",
        help="PDF, TXT, DOCX 파일을 첨부할 수 있습니다. HWP, PNG, JPG는 파일명만 전달됩니다.",
    )
    if ref_files:
        st.caption(f"📎 첨부된 파일 ({len(ref_files)}개):")
        for _f in ref_files:
            st.caption(f"  • {_f.name}")
    st.divider()

    # Buttons depend on current step
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
            for _k in ("app_step", "elements", "saved_inputs", "final_results", "outline_text"):
                st.session_state[_k] = _defaults[_k]
            st.rerun()


# ──────────────────────────────────────────────
# MAIN AREA – HEADER
# ──────────────────────────────────────────────
st.title("🎓 수행평가 도우미")
st.caption(
    "AI가 평가요소별 공신력 있는 자료를 추천해드립니다. "
    "보고서는 학생 여러분이 직접 작성합니다. ✍️"
)


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
        # Merge rubric text and file
        final_rubric = rubric_text.strip()
        if rubric_file:
            extracted = extract_file_text(rubric_file)
            final_rubric = (final_rubric + "\n\n" + extracted).strip() if final_rubric else extracted

        if not final_rubric:
            st.warning("⚠️ 평가표(루브릭)를 텍스트로 입력하거나 파일로 업로드해주세요.")
        else:
            # Collect reference file texts
            ref_texts = []
            if ref_files:
                for _f in ref_files:
                    ref_texts.append(f"[{_f.name}]\n{extract_file_text(_f)}")

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
                    raw = call_ai(client, EXTRACT_SYSTEM, extract_msg)
                    parsed = parse_json_response(raw)
                    elements = parsed.get("elements", [])
                    if not elements:
                        st.error("평가요소를 추출하지 못했습니다. 평가표 내용을 확인해주세요.")
                    else:
                        st.session_state["elements"] = elements
                        st.session_state["app_step"] = "confirm_elements"
                        st.rerun()
                except Exception as e:
                    st.error(f"❌ 평가요소 추출 실패: {e}")


# ──────────────────────────────────────────────
# STEP 2 — CONFIRM ELEMENTS
# ──────────────────────────────────────────────
elif st.session_state["app_step"] == "confirm_elements":
    elements = st.session_state["elements"]
    st.subheader(f"📋 추출된 평가요소 ({len(elements)}개)")
    st.caption("아래 평가요소 리스트를 확인하고, 맞으면 '자료 추천 시작' 버튼을 눌러주세요.")

    for i, el in enumerate(elements, 1):
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**{i}. {el['name']}**")
            if el.get("description"):
                st.caption(el["description"])
        with col2:
            st.caption(f"자료 최소 {el.get('min_sources', MIN_SOURCES)}개")

    st.divider()

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("✅ 이 요소 리스트로 자료 추천 시작", type="primary", use_container_width=True):
            st.session_state["app_step"] = "generating"
            st.rerun()
    with col_b:
        if st.button("↩ 평가표 다시 입력", use_container_width=True):
            st.session_state["app_step"] = "input"
            st.session_state["elements"] = []
            st.rerun()


# ──────────────────────────────────────────────
# STEP 3 — GENERATING (blocking, then rerun)
# ──────────────────────────────────────────────
elif st.session_state["app_step"] == "generating":
    inputs = st.session_state["saved_inputs"]
    elements = st.session_state["elements"]

    elements_text = "\n".join(
        f"{i}. {el['name']} (최소 자료 {el.get('min_sources', MIN_SOURCES)}개)"
        for i, el in enumerate(elements, 1)
    )
    ref_block = ""
    if inputs.get("ref_texts"):
        ref_block = "\n\n참고자료:\n" + "\n".join(inputs["ref_texts"])

    material_msg = (
        f"다음 수행평가의 각 평가요소에 대해 자료를 추천해주세요.\n\n"
        f"학교 유형: {inputs['school']}\n"
        f"과목: {inputs['subject']}\n"
        f"주제: {inputs['topic']}\n"
        + (f"조건: {inputs['conditions']}\n" if inputs.get("conditions") else "")
        + f"\n평가요소 목록:\n{elements_text}\n\n"
        "각 평가요소마다 최소 6개씩 자료를 추천해주세요 (URL 검증 후 필터링 예정).\n"
        "블로그, 나무위키 금지. RISS, DBpia, 정부기관, 주요언론사, 유튜브, 국제기구 사용."
        + ref_block
    )

    with st.spinner("📚 자료를 검색하고 링크를 검증하는 중... (잠시 기다려주세요)"):
        try:
            raw = call_ai(client, MATERIAL_SYSTEM, material_msg)
            data = parse_json_response(raw)
            results_raw = data.get("results", [])

            # Collect all URLs for parallel validation
            all_urls = [
                src.get("url", "")
                for item in results_raw
                for src in item.get("sources", [])
                if src.get("url", "")
            ]
            url_validity = validate_urls_parallel(all_urls) if all_urls else {}

            # Build final results, filling gaps with fallbacks
            final_results = []
            for item in results_raw:
                el_name = item.get("element_name", "")
                matching_el = next(
                    (el for el in elements if el["name"] == el_name),
                    {"min_sources": MIN_SOURCES},
                )
                min_sources = matching_el.get("min_sources", MIN_SOURCES)

                valid_sources = [
                    src for src in item.get("sources", [])
                    if url_validity.get(src.get("url", ""), False)
                ]

                if len(valid_sources) < min_sources:
                    needed = min_sources - len(valid_sources)
                    valid_sources.extend(make_fallback_sources(el_name, needed))

                final_results.append({
                    "element_name": el_name,
                    "sources": valid_sources,
                    "checklist": item.get("checklist", []),
                })

            # Generate outlines (non-streaming, stored then displayed in results step)
            outline_elements = "\n".join(f"- {el['name']}" for el in elements)
            outline_msg = (
                f"다음 수행평가의 개요 3개를 작성해주세요.\n\n"
                f"학교 유형: {inputs['school']}\n"
                f"과목: {inputs['subject']}\n"
                f"주제: {inputs['topic']}\n"
                + (f"조건: {inputs['conditions']}\n" if inputs.get("conditions") else "")
                + f"\n평가요소:\n{outline_elements}\n\n"
                "개요 3개(기초/표준/심화)를 작성해주세요. "
                "각 개요는 평가요소를 어떻게 다루는지 명시합니다."
            )
            outline_text = call_ai(client, OUTLINE_SYSTEM, outline_msg)

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

    # ── Section 1: material recommendations ──
    st.subheader("📚 1. 평가요소별 자료 추천")
    st.caption(f"총 {len(final_results)}개 평가요소 | 검증된 링크만 표시")

    result_output = (
        f"# 수행평가 자료 추천 결과\n\n"
        f"과목: {inputs['subject']} | 주제: {inputs['topic']}\n\n"
        "## 1. 평가요소별 자료 추천\n\n"
    )

    for item in final_results:
        el_name = item["element_name"]
        sources = item["sources"]
        checklist = item.get("checklist", [])

        st.markdown(f"### 📌 {el_name}")
        result_output += f"[{el_name}]\n"

        for i, src in enumerate(sources, 1):
            title = src.get("title", "자료")
            url = src.get("url", "#")
            usage = src.get("usage", "")
            st.markdown(f"- **자료 {i}**: [{title}]({url})")
            if usage:
                st.markdown(f"  → 활용 방식: {usage}")
            result_output += f"- 자료 {i}: {title} ({url})\n"
            if usage:
                result_output += f"  → 활용 방식: {usage}\n"

        if checklist:
            st.markdown("✔ **체크리스트:**")
            for c in checklist:
                st.markdown(f"  - {c}")
            result_output += "✔ 체크리스트:\n"
            for c in checklist:
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

    # Download
    st.download_button(
        label="📥 결과 다운로드 (.txt)",
        data=result_output,
        file_name=f"수행평가_분석결과_{inputs.get('subject', '')}.txt",
        mime="text/plain",
    )
