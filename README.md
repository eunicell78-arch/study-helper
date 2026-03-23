# 🎓 수행평가 도우미

고등학교 수행평가를 준비하는 학생들을 위한 **AI 기반 리서치 도우미** 웹앱입니다.  
**Streamlit** 앱으로 구현되어 있으며, Streamlit Community Cloud에 무료로 배포할 수 있습니다.  
Anthropic API 키는 Streamlit Secrets로 안전하게 관리되므로 사용자에게 노출되지 않습니다.

---

## ✨ 주요 기능

| 기능 | 설명 |
|------|------|
| 🔒 비밀번호 보호 | 단일 공용 비밀번호로 접근 제어 (Secrets로 관리) |
| 🤖 Anthropic Claude 연동 | 관리자 API 키로 Claude 모델 사용 (사용자에게 미노출) |
| 🏫 학교 유형별 맞춤 | 일반고/자사고/국제고/외고/영재고/과학고 차별화 |
| 📌 주제 방향 5개+ | 학교 유형·과목·조건에 맞는 방향 제시 |
| 📚 자료 20개+ 추천 | 논문·기사·공공자료·유튜브·기타 (URL 포함) |
| 📎 파일 첨부 | PDF, TXT, DOCX, HWP, PNG/JPG 첨부 후 AI에 전달 |
| ⚡ 스트리밍 응답 | 실시간 AI 응답 표시 |
| 🚀 방향 심화 | "이 방향 더 발전시키기" 클릭으로 심화 분석 |
| 💬 채팅 히스토리 | 이전 대화 맥락 유지, 후속 질문 가능 |
| 📋 결과 복사 | 클립보드 복사 버튼 |
| 📄 PDF 저장 | 브라우저 인쇄 기능으로 PDF 저장 |
| 🌙 다크/라이트 모드 | 토글 지원 |
| 📱 모바일 반응형 | 모든 기기에서 사용 가능 |
| 🇺🇸 영어 수행평가 모드 | 영어 자료·표현 추가 제공 |

---

## 🚀 Streamlit Community Cloud 배포 방법

1. 이 저장소를 본인 계정으로 Fork합니다.
2. [share.streamlit.io](https://share.streamlit.io)에 접속하여 GitHub 계정으로 로그인합니다.
3. **New app** 버튼 클릭 후 저장소와 `app.py`를 선택합니다.
4. **Advanced settings → Secrets** 에 아래 내용을 붙여넣습니다:

```toml
ANTHROPIC_API_KEY = "sk-ant-your-actual-api-key"
APP_PASSWORD = "study2026"
```

5. **Deploy** 버튼을 클릭합니다.
6. 배포 완료 후 제공된 URL로 접속하면 됩니다.

> ⚠️ `secrets.toml` 파일은 절대 저장소에 커밋하지 마세요. `.gitignore`에 이미 추가되어 있습니다.

> Anthropic API 키는 [console.anthropic.com](https://console.anthropic.com)에서 발급받을 수 있습니다.

---

## 💻 로컬 실행 방법

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. Secrets 파일 생성 (macOS/Linux)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Windows: copy .streamlit\secrets.toml.example .streamlit\secrets.toml

# secrets.toml 을 편집하여 실제 API 키와 비밀번호 입력

# 3. 앱 실행
streamlit run app.py
```

---

## 🔑 Secrets 설정 항목

| 항목 | 설명 | 기본값 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 ([발급](https://console.anthropic.com)) | 없음 (필수) |
| `APP_PASSWORD` | 앱 접속 비밀번호 | `study2026` |

---

## 🚀 사용 방법

### 1단계: 비밀번호 입력
- 웹앱 접속 시 비밀번호 입력 화면이 표시됩니다.
- 비밀번호는 Streamlit Secrets의 `APP_PASSWORD`에서 관리합니다 (기본값: `study2026`).

### 2단계: 수행평가 정보 입력
1. **학교 유형** 선택 (일반고/자사고/국제고/외고/영재고/과학고/기타)
2. **과목**과 **주제/범위** 입력 (필수)
3. **조건/제한사항**, **평가 기준** 입력 (선택)
4. **학교 제공 자료**, **필수 참고자료**, **관심 키워드** 입력 (선택)
5. **파일 첨부** (선택): PDF, TXT, DOCX, HWP, PNG, JPG 파일을 첨부하면 AI가 내용을 참고합니다.
6. 수행평가 모드 선택: 🇰🇷 국문 / 🇺🇸 영어

### 3단계: 분석 시작
- **🔍 수행평가 분석 시작** 버튼 클릭
- AI가 주제 방향 5개 이상과 자료 20개 이상을 추천합니다.

### 4단계: 심화 탐구
- 원하는 방향 번호를 선택하고 **🚀 이 방향 더 발전시키기** 클릭
- 하단 입력창에서 후속 질문도 가능합니다.

---

## 📎 파일 첨부 지원 형식

| 형식 | 처리 방식 |
|------|----------|
| **TXT** | 텍스트 직접 읽기 |
| **PDF** | PyPDF2로 텍스트 추출 |
| **DOCX** | python-docx로 텍스트 추출 |
| **HWP** | 파일명만 전달 (직접 파싱 제한) |
| **PNG / JPG / JPEG** | 파일명만 전달 (이미지 텍스트 추출 불가) |

---

## 📦 GitHub Pages (index.html 백업 배포)

기존 `index.html`은 백업용으로 유지됩니다. GitHub Pages로도 배포 가능하지만  
API 키를 사용자가 직접 입력해야 하는 방식입니다.

1. 저장소 **Settings → Pages** 메뉴에서:
   - Source: **Deploy from a branch**
   - Branch: `main`, Folder: `/ (root)`
2. `https://[사용자명].github.io/[저장소명]/` 으로 접속

---

## 📄 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다.

## 📋 추천 자료 구성

| 카테고리 | 최소 수량 | 주요 출처 |
|---------|---------|---------|
| 📄 학술논문 | 5개 이상 | KCI, RISS, DBpia |
| 📰 신문기사 | 5개 이상 | 조선, 중앙, 한겨레, 경향 |
| 🏛️ 공공기관 자료 | 5개 이상 | 통계청, 정부부처, 연구원 |
| 🎥 유튜브 영상 | 3개 이상 | EBS, KBS, 세바시, TED |
| 🌐 기타 신뢰 출처 | 2개 이상 | 국제기구, 학회, 백서 |

> 💡 모든 자료에 출처 URL이 포함됩니다.  
> 최근 5년 이내(2021~2026년) 자료를 우선 추천합니다.

---

## ⚠️ 주의사항

- **대필 방지**: 이 도우미는 방향 제시와 자료 수집만을 목적으로 합니다. 보고서는 학생이 직접 작성해야 합니다.
- **API 키 보안**: API 키는 Streamlit Secrets에만 저장됩니다. 소스코드에 노출되지 않습니다.
- **비밀번호 관리**: 비밀번호는 Streamlit Secrets의 `APP_PASSWORD`로 설정하고 변경합니다.
- **표절 금지**: 추천된 자료를 그대로 복사하지 말고, 자신의 말로 재구성하여 인용하세요.

---

## 🛠️ 기술 스택

- [Streamlit](https://streamlit.io/) — Python 웹앱 프레임워크
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) — Claude Messages API (스트리밍)
- [PyPDF2](https://pypdf2.readthedocs.io/) — PDF 텍스트 추출
- [python-docx](https://python-docx.readthedocs.io/) — DOCX 텍스트 추출
- Streamlit Community Cloud — 무료 배포 및 Secrets 관리

---

## 📄 파일 구조

```
study-helper/
├── app.py                          # Streamlit 메인 앱
├── requirements.txt                # Python 의존성
├── index.html                      # 기존 HTML 앱 (백업용)
├── .streamlit/
│   ├── config.toml                 # Streamlit 테마/서버 설정
│   └── secrets.toml.example        # Secrets 설정 예시
├── .gitignore                      # secrets.toml 제외
└── README.md
```

---

## 📄 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다.

