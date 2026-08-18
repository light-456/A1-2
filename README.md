# 🗺️ 여행 추천 리포트 생성기

--date "yyyy-mm-dd"를 입력하면 LLM(Gemini)이 국내 여행지를 추천하고,
Kakao API로 해당 지역 맛집을 검색하여 여행 리포트를 자동 생성하는 CLI 프로그램입니다.

## 📋 프로젝트 개요

여러 API를 조합하여 인사이트를 만드는 프로그램입니다.
사용자가 여행 날짜를 입력하면 아래 3단계로 동작합니다.

1. **추천 지역 생성** — Gemini AI가 입력 날짜에 맞는 국내 여행지 추천 (도시, 날씨, 행사, 이유)
2. **맛집 검색** — Kakao Local API로 추천 도시의 맛집 정보(최대 5곳) 수집
3. **리포트 생성** — 결과를 JSON 데이터 + Markdown 리포트로 저장

## 🛠️ 사용 기술

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.10+ |
| LLM API | Google Gemini API (`gemini-flash-latest`) |
| 지도 API | Kakao Local API (키워드 장소 검색) |
| 주요 라이브러리 | `requests`, `python-dotenv`, `google-genai` |

## ⚙️ 설치 및 설정

### 1. 라이브러리 설치
```bash
pip install requests python-dotenv google-genai
```

> ℹ️ 예전 `google-generativeai` 패키지는 Google이 공식적으로 지원을 종료(deprecated)했으므로, 반드시 최신 `google-genai` 패키지를 사용합니다.

### 2. API 키 설정 (.env 파일)
프로젝트 폴더에 `.env` 파일을 만들고 아래처럼 API 키를 입력하세요:

```
KAKAO_API_KEY=여기에_카카오_REST_API_키_입력
GEMINI_API_KEY=여기에_제미나이_API_키_입력
```

> ⚠️ **주의사항**
> - 파일 이름은 반드시 `.env` 여야 합니다. (`.env.txt` ❌)
> - API 키를 **따옴표 없이** 입력하세요. 따옴표를 넣으면 값에 따옴표가 포함되어 인증(401)에 실패할 수 있습니다.
> - Kakao 키는 **REST API 키**를 사용해야 합니다.

## 🚀 실행 방법

```bash
python main.py -date "2025-03-15"
```

| 인자 | 설명 | 필수 | 형식 |
|------|------|------|------|
| `-date` / `--date` | 조회할 날짜 | ✅ | YYYY-MM-DD |

### 실행 예시 (진행 로그)
```
[1/3] 2025-03-15 추천 지역 생성 중(LLM)...
    - recommended_city: "제주"
[2/3] '제주' 맛집 검색 중(지도 API)...
    - 맛집 5곳 검색 완료
[3/3] 최종 리포트 생성 및 저장 중...

✅ 완료! results/2025-03-15_report.md 를 확인하세요.
```

## 📂 파일 구조

```
.
├── main.py                      # 메인 프로그램
├── README.md                    # 프로젝트 설명서
├── .env                         # API 키 (git에 올리지 않음)
├── .gitignore
└── results/                     # 실행 결과 저장 폴더
    ├── {날짜}_data.json         # 원본 데이터(추천/맛집/오류)
    └── {날짜}_report.md         # 최종 여행 리포트
```

### 결과물 설명
- **`{날짜}_data.json`** : 1차 추천 JSON + 맛집 검색 결과 + 오류 요약(errors)을 담은 원본 데이터
- **`{날짜}_report.md`** : 추천 지역·이유, 날씨, 행사, 맛집, 1일 일정, 오류 요약을 정리한 리포트

## 🔄 프로그램 동작 흐름

```
[날짜 입력] → [입력값 검증] → [LLM 추천(JSON)] → [Kakao 맛집 검색]
                                                        ↓
                              [JSON 저장] ← [Markdown 리포트 생성]
```

- LLM 출력을 **JSON으로 구조화**하여 다음 단계(맛집 검색)의 입력(`recommended_city`)으로 연결합니다.

## 🧩 오류 처리 정책

미션 요구사항에 따라 단계별로 오류를 처리하며, 모든 오류는 내부 `errors` 목록에 기록되어 리포트와 JSON에 남습니다.

| 상황 | 처리 방식 |
|------|-----------|
| **API 키 미설정** (Gemini) | 즉시 종료 + 설정 방법 안내 |
| **LLM JSON 파싱 실패** | 강화 프롬프트로 **최대 1회 재시도** |
| **지도 API 인증 실패(401/403)** | `AUTH_ERROR` 기록 후 맛집 "데이터 없음"으로 진행 |
| **검색 결과 0건** | `EMPTY_RESULT` 기록 후 "데이터 없음"으로 진행 |
| **네트워크 오류** | `NETWORK_ERROR` 기록 후 계속 진행 |

> 💡 **부분 실패 대응**: 일부 단계가 실패해도 프로그램은 중단되지 않고, 가능한 결과까지 리포트를 생성합니다.

## ✅ 미션 요구사항 충족 체크리스트

- [x] argparse 기반 CLI + 날짜 형식 검증
- [x] LLM(Gemini) 연동 및 JSON 구조화 출력 (`recommended_city`, `weather`, `events`, `reason`)
- [x] Kakao Local API로 맛집 검색 (name, address, category, url, x/y)
- [x] Markdown 리포트 생성 (추천/이유/날씨/행사/맛집/1일 일정/오류 요약)
- [x] try-except 기반 에러 처리 + 재시도 1회 제한
- [x] `.env`로 API 키 관리 (코드에 키 미포함)
- [x] `results/` 폴더에 JSON + Markdown 저장

## 🔒 보안 주의사항

- `.env` 파일에는 개인 API 키가 들어있으므로 **절대 외부에 공유하지 마세요.**
- GitHub 등에 올릴 때는 `.gitignore`에 `.env`를 반드시 추가하세요.

```
# .gitignore 예시
.env
results/
__pycache__/
```

**`.env`를 사용하는 이유**
- 협업/공유 시 실수로 키가 공개되는 것을 막습니다.
- 키를 교체해도 코드를 수정할 필요가 없습니다.
- 과금/쿼터가 걸린 서비스에서 사고를 예방합니다.