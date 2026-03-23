import streamlit as st
import anthropic

st.set_page_config(
    page_title="🎓 수행평가 도우미",
    page_icon="🎓",
    layout="wide",
)

# ──────────────────────────────────────────────
# SYSTEM PROMPT (identical to index.html)
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """당신은 고등학교 수행평가 전문 리서치 어시스턴트입니다.
학생이 수행평가 보고서를 스스로 작성할 수 있도록, 방향 제시와 신뢰할 수 있는 자료 수집만을 목적으로 합니다.
절대로 보고서 전체를 대필하지 않습니다.

학교 유형별 차별화:
- 일반고: 교과 연계 + 실생활 적용, 기본~중급 자료
- 자사고: 심화 분석 + 비판적 사고, 중급~고급 자료
- 국제고: 글로벌 이슈 + 다문화 관점, 국제기구 자료 활용
- 외국어고: 언어·문화 융합 + 원문 자료, 외국 원문 비교
- 영재고: 학문적 깊이 + 연구 방법론, 논문 기반 접근
- 과학고: 과학적 탐구 + 데이터 기반, 실험 설계 + 통계 분석

응답 시 반드시 포함할 내용:
1. 주제 방향 5개 이상 (각각 핵심 아이디어, 탐구 질문, 추천 보고서 구조, 난이도, 장점, 주의점 포함)
2. 자료 추천 20개 이상 (모든 자료에 출처 URL 표시):
   - 📄 학술논문 (KCI, RISS, DBpia 등): 5개 이상
   - 📰 신문기사 (조선, 중앙, 한겨레, 경향 등): 5개 이상
   - 🏛️ 공공기관 자료 (정부부처, 연구원, 통계청 등): 5개 이상
   - 🎥 유튜브 영상 (강의, 다큐, 전문가 인터뷰): 3개 이상
   - 🌐 기타 신뢰 가능한 출처: 2개 이상
3. 최신 자료 우선 (최근 5년 이내, 2021~2026년)
4. 표절 주의 안내

영어 수행평가 모드인 경우:
- 영어 키워드와 영문 표현 예시 포함
- 영어 학술논문 3개 이상, 영어 신문기사 3개 이상, 영어 유튜브/TED 영상 2개 이상 추가
- 유용한 영어 표현/문장 패턴 제공"""


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
        return f"[HWP 파일 '{name}' – 직접 파싱이 어려워 파일명만 전달됩니다]"

    if ext in ("png", "jpg", "jpeg"):
        return f"[이미지 파일 '{name}' – 텍스트 추출 불가, 파일명만 전달됩니다]"

    return f"[파일 '{name}' – 지원되지 않는 형식]"


def build_user_message(school, subject, topic, conditions, rubric,
                        school_material, required_ref, keywords, mode,
                        attached_texts: list | None = None) -> str:
    """Compose the user message for the first research request."""
    msg = "📋 **수행평가 분석 요청**\n\n"
    msg += f"- **학교 유형**: {school}\n"
    msg += f"- **과목**: {subject}\n"
    msg += f"- **주제/범위**: {topic}\n"
    if conditions:
        msg += f"- **조건/제한사항**: {conditions}\n"
    if rubric:
        msg += f"- **평가 기준(루브릭)**: {rubric}\n"
    if school_material:
        msg += f"- **학교 제공 자료**: {school_material}\n"
    if required_ref:
        msg += f"- **필수 참고자료**: {required_ref}\n"
    if keywords:
        msg += f"- **관심 키워드**: {keywords}\n"
    msg += f"- **모드**: {'🇺🇸 영어 수행평가 모드' if mode == 'english' else '🇰🇷 국문 수행평가 모드'}\n\n"
    msg += (
        "위 정보를 바탕으로 수행평가 주제 방향 5개 이상과 공신력 있는 자료 20개 이상"
        "(논문 5개+, 신문기사 5개+, 공공기관 5개+, 유튜브 3개+, 기타 2개+, 모든 URL 포함)을 추천해주세요."
    )
    if mode == "english":
        msg += "\n영어 수행평가 모드이므로 영어 자료와 표현도 포함해주세요."
    if attached_texts:
        msg += "\n\n---\n**첨부 자료 내용:**\n"
        for item in attached_texts:
            msg += f"\n{item}\n"
    return msg


def stream_response(client: anthropic.Anthropic, model: str, messages: list) -> str:
    """Stream the AI response and return the full text."""
    full_text = ""
    # Separate system message from conversation messages (Anthropic API format)
    system_content = ""
    conv_messages = []
    for m in messages:
        if m["role"] == "system":
            system_content = m["content"]
        else:
            conv_messages.append({"role": m["role"], "content": m["content"]})

    with st.chat_message("assistant"):
        placeholder = st.empty()
        with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=system_content,
            messages=conv_messages,
        ) as stream:
            for text in stream.text_stream:
                full_text += text
                placeholder.markdown(full_text + "▌")
        placeholder.markdown(full_text)
    return full_text


# ──────────────────────────────────────────────
# SESSION STATE INIT
# ──────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state["messages"] = []


# ──────────────────────────────────────────────
# PASSWORD GATE
# ──────────────────────────────────────────────
if not check_password():
    st.stop()


# ──────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────
with st.sidebar:
    st.title("🎓 수행평가 도우미")
    st.caption("AI 기반 리서치 어시스턴트")
    st.divider()

    # Model selection
    st.subheader("⚙️ AI 모델 설정")
    model = st.selectbox(
        "모델 선택",
        ["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"],
        index=0,
    )
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
    topic = st.text_input("주제 또는 범위 *", placeholder="예: 기후 변화와 탄소 중립")
    conditions = st.text_area(
        "조건/제한사항",
        placeholder="예: A4 3장, 참고문헌 5개 이상, 2주 후 제출",
        height=80,
    )
    rubric = st.text_area(
        "평가 기준/루브릭 (선택)",
        placeholder="평가 기준이 있다면 입력하세요",
        height=80,
    )
    st.divider()

    # Reference materials
    st.subheader("📚 참고자료")
    school_material = st.text_area(
        "학교 제공 자료 (선택)",
        placeholder="학교에서 받은 자료 내용 또는 제목",
        height=70,
    )
    required_ref = st.text_area(
        "필수 참고자료 (선택)",
        placeholder="반드시 참고해야 할 자료",
        height=70,
    )
    keywords = st.text_input(
        "관심 키워드 (선택)",
        placeholder="예: 청소년, 환경, 정책",
    )
    uploaded_files = st.file_uploader(
        "파일 첨부 (선택)",
        type=["pdf", "txt", "docx", "hwp", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        help="PDF, TXT, DOCX, HWP, PNG, JPG 파일을 첨부할 수 있습니다.",
    )
    if uploaded_files:
        st.caption(f"📎 첨부된 파일 ({len(uploaded_files)}개):")
        for f in uploaded_files:
            st.caption(f"  • {f.name}")
    st.divider()

    # Mode
    st.subheader("🌐 수행평가 모드")
    mode = st.radio(
        "모드 선택",
        options=["korean", "english"],
        format_func=lambda x: "🇰🇷 국문 모드" if x == "korean" else "🇺🇸 영어 모드",
        label_visibility="collapsed",
    )
    st.divider()

    # Action buttons
    start_btn = st.button(
        "🔍 수행평가 분석 시작",
        use_container_width=True,
        type="primary",
        disabled=not subject or not topic,
    )
    if st.button("🗑️ 대화 초기화", use_container_width=True):
        st.session_state["messages"] = []
        st.rerun()


# ──────────────────────────────────────────────
# MAIN AREA – HEADER
# ──────────────────────────────────────────────
st.title("🎓 수행평가 도우미")
st.caption(
    "AI가 수행평가 주제 방향과 공신력 있는 자료를 추천해드립니다. "
    "보고서는 학생 여러분이 직접 작성합니다. ✍️"
)

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
# DISPLAY CHAT HISTORY
# ──────────────────────────────────────────────
if not st.session_state["messages"]:
    st.info(
        "👈 왼쪽 사이드바에서 학교 유형, 과목, 주제를 입력한 후 "
        "**🔍 수행평가 분석 시작** 버튼을 눌러주세요."
    )

for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ──────────────────────────────────────────────
# TRIGGER: START RESEARCH BUTTON
# ──────────────────────────────────────────────
if start_btn:
    if not subject or not topic:
        st.warning("⚠️ 과목과 주제는 필수 입력입니다.")
    else:
        # Extract text from uploaded files
        attached_texts = []
        if uploaded_files:
            for f in uploaded_files:
                text = extract_file_text(f)
                attached_texts.append(f"[{f.name}]\n{text}")

        user_msg = build_user_message(
            school, subject, topic, conditions, rubric,
            school_material, required_ref, keywords, mode,
            attached_texts=attached_texts if attached_texts else None,
        )
        # Reset history for a fresh research session
        st.session_state["messages"] = []
        st.session_state["messages"].append({"role": "user", "content": user_msg})

        with st.chat_message("user"):
            st.markdown(user_msg)

        api_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        try:
            response_text = stream_response(client, model, api_messages)
            st.session_state["messages"].append(
                {"role": "assistant", "content": response_text}
            )
            # Download button
            st.download_button(
                label="📥 결과 다운로드 (.txt)",
                data=response_text,
                file_name="수행평가_분석결과.txt",
                mime="text/plain",
                key="dl_start",
            )
        except Exception as e:
            st.error(f"❌ 오류가 발생했습니다: {e}")

# ──────────────────────────────────────────────
# CHAT INPUT – follow-up questions
# ──────────────────────────────────────────────
if st.session_state["messages"]:
    followup = st.chat_input(
        "후속 질문을 입력하세요 (예: 방향 3 더 발전시켜줘, 논문 자료 더 찾아줘)"
    )
    if followup:
        st.session_state["messages"].append({"role": "user", "content": followup})
        with st.chat_message("user"):
            st.markdown(followup)

        api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state["messages"]
        ]
        try:
            response_text = stream_response(client, model, api_messages)
            st.session_state["messages"].append(
                {"role": "assistant", "content": response_text}
            )
            st.download_button(
                label="📥 결과 다운로드 (.txt)",
                data=response_text,
                file_name="수행평가_분석결과.txt",
                mime="text/plain",
                key=f"dl_followup_{len(st.session_state['messages'])}",
            )
        except Exception as e:
            st.error(f"❌ 오류가 발생했습니다: {e}")
