# main.py
# 국내 여행 추천 리포트 생성기
# - LLM(Gemini)으로 추천 지역/이유/날씨/행사 생성
# - Kakao 지도 API로 맛집 검색
# - 결과를 JSON + Markdown 리포트로 저장

import os
import re
import sys
import json
import argparse
from datetime import datetime

import requests
from dotenv import load_dotenv

import google.generativeai as genai

# ─────────────────────────────────────────────
# 0. 환경설정 & 상수
# ─────────────────────────────────────────────
load_dotenv()  # .env 파일에서 키를 불러옴 (코드에 키를 직접 박지 않음 → 보안)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")

# ⭐ 404 방지: 최신 라이브러리에서 인식되는 모델명 사용
#    만약 여전히 404가 나면 "gemini-2.0-flash" 로 바꿔보세요.
GEMINI_MODEL = "gemini-3.5-flash"

KAKAO_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
RESULT_DIR = "results"


# ─────────────────────────────────────────────
# 1. 입력값(날짜) 검증
# ─────────────────────────────────────────────
def parse_args():
    """CLI 인자를 파싱한다. -date, --date 둘 다 허용."""
    parser = argparse.ArgumentParser(description="국내 여행 추천 리포트 생성기")
    # dest="date"로 통일 → -date, --date 모두 같은 변수에 저장
    parser.add_argument("-date", "--date", dest="date", required=True,
                        help='추천받을 날짜 (형식: "YYYY-MM-DD")')
    return parser.parse_args()


def validate_date(date_str):
    """날짜 형식(YYYY-MM-DD)이 올바른지 검증한다."""
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ─────────────────────────────────────────────
# 2. LLM 호출 (추천 지역/이유/날씨/행사)
# ─────────────────────────────────────────────
def build_prompt(date_str, retry=False):
    """LLM에게 보낼 프롬프트를 생성한다."""
    base = f"""당신은 국내 여행 추천 전문가입니다.
날짜 '{date_str}'에 가기 좋은 국내 여행지 한 곳을 추천해 주세요.

반드시 아래 JSON 형식으로만 답변하세요. 설명이나 마크다운(```)은 절대 붙이지 마세요.
{{
  "recommended_city": "도시명",
  "weather": "해당 시기 날씨 요약",
  "events": ["행사1", "행사2"],
  "reason": "추천 이유"
}}"""
    if retry:
        # ⭐ 재시도 강화: 파싱 실패 시 '순수 JSON만' 다시 강조
        base += "\n\n중요: 앞뒤 설명 없이 위 필수 키를 가진 순수 JSON 객체 하나만 출력하세요."
    return base


def extract_json(text):
    """LLM 응답 문자열에서 JSON 부분만 추출해 파싱한다."""
    # 코드블록(```json ... ```) 이 섞여 나올 때 대비
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    # 가장 바깥 중괄호 범위만 추출
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def get_recommendation(date_str, errors):
    """
    Gemini로 추천 정보를 받아온다.
    1차 실패(파싱 오류) 시 강화 프롬프트로 1회 재시도한다.
    """
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY가 설정되지 않았습니다.")
        print('   .env 파일에 다음과 같이 추가하세요: GEMINI_API_KEY="발급받은키"')
        sys.exit(1)

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    for attempt in range(2):  # 최초 1회 + 재시도 1회
        try:
            prompt = build_prompt(date_str, retry=(attempt == 1))
            response = model.generate_content(prompt)
            data = extract_json(response.text)

            # 필수 키 확인
            if "recommended_city" not in data:
                raise ValueError("필수 키(recommended_city) 누락")
            return data

        except Exception as e:
            if attempt == 0:
                print(f"    - LLM 응답 파싱 실패, 강화 프롬프트로 재시도합니다... ({e})")
                continue
            # 재시도까지 실패 → 오류 기록 후 None 반환
            errors.append({
                "step": "LLM_API",
                "type": "PARSE_ERROR",
                "message": str(e)
            })
            return None


# ─────────────────────────────────────────────
# 3. 지도 API 호출 (맛집 검색)
# ─────────────────────────────────────────────
def search_restaurants(city, errors):
    """Kakao 키워드 검색으로 맛집 목록을 가져와 최소 필드로 정규화한다."""
    if not KAKAO_API_KEY:
        errors.append({
            "step": "MAP_API",
            "type": "AUTH_ERROR",
            "message": "KAKAO_API_KEY가 설정되지 않았습니다."
        })
        return []

    # ⭐ 한글 인코딩 버그 해결 포인트:
    #    헤더는 ASCII(영문 키)만, 한글은 params(query)로 전달 → requests가 자동 URL 인코딩
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    params = {"query": f"{city} 맛집", "size": 5}

    try:
        res = requests.get(KAKAO_SEARCH_URL, headers=headers,
                           params=params, timeout=10)

        # 인증/권한 오류를 명확히 구분
        if res.status_code in (401, 403):
            errors.append({
                "step": "MAP_API",
                "type": "AUTH_ERROR",
                "message": f"HTTP {res.status_code}: {res.text}"
            })
            return []

        res.raise_for_status()  # 그 외 4xx/5xx는 예외 발생
        documents = res.json().get("documents", [])

        if not documents:
            # 결과 0건 → 오류로 기록하되 프로그램은 계속 진행
            errors.append({
                "step": "MAP_API",
                "type": "EMPTY_RESULT",
                "message": "검색 결과 0건"
            })
            return []

        # ⭐ raw 구조 의존 제거: 미션이 요구하는 최소 필드로 정규화
        restaurants = []
        for doc in documents:
            restaurants.append({
                "name": doc.get("place_name", ""),
                "address": doc.get("road_address_name") or doc.get("address_name", ""),
                "category": doc.get("category_group_name", ""),
                "url": doc.get("place_url", ""),
                "x": doc.get("x", ""),
                "y": doc.get("y", ""),
            })
        return restaurants

    except requests.exceptions.RequestException as e:
        errors.append({
            "step": "MAP_API",
            "type": "NETWORK_ERROR",
            "message": str(e)
        })
        return []


# ─────────────────────────────────────────────
# 4. 결과 저장 (JSON + Markdown)
# ─────────────────────────────────────────────
def save_results(date_str, recommendation, restaurants, errors):
    """결과를 results/ 폴더에 JSON과 Markdown 리포트로 저장한다."""
    os.makedirs(RESULT_DIR, exist_ok=True)

    # ── 4-1. JSON 저장 ──
    data = {
        "date": date_str,
        "recommendation": recommendation,
        "restaurants": restaurants,
        "errors": errors,
    }
    json_path = os.path.join(RESULT_DIR, f"{date_str}_data.json")
    # ⭐ ensure_ascii=False → 한글이 깨지지 않고 그대로 저장됨
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    # ── 4-2. Markdown 리포트 저장 ──
    md_path = os.path.join(RESULT_DIR, f"{date_str}_report.md")
    lines = []
    lines.append(f"# {date_str} 국내 여행 추천 리포트\n")

    if recommendation:
        city = recommendation.get("recommended_city", "정보 없음")
        lines.append(f"## 📍 추천 지역: {city}\n")
        lines.append("## 📝 추천 이유")
        lines.append(recommendation.get("reason", "정보 없음") + "\n")
        lines.append("## 🌤 날씨 요약")
        lines.append(recommendation.get("weather", "정보 없음") + "\n")
        lines.append("## 🎊 행사/축제")
        events = recommendation.get("events", [])
        if events:
            for ev in events:
                lines.append(f"- {ev}")
        else:
            lines.append("- 정보 없음")
        lines.append("")
    else:
        # LLM 실패 시에도 리포트는 정상 생성
        city = "데이터 없음"
        lines.append("## 📍 추천 지역: 데이터 없음\n")
        lines.append("## 📝 추천 이유\n정보 없음\n")
        lines.append("## 🌤 날씨 요약\n정보 없음\n")
        lines.append("## 🎊 행사/축제\n- 정보 없음\n")

    # 맛집 섹션
    lines.append("## 🍴 맛집 추천")
    if restaurants:
        for r in restaurants:
            lines.append(f"- **{r['name']}** ({r['category']})")
            lines.append(f"  - 주소: {r['address']}")
            lines.append(f"  - [상세보기]({r['url']})")
    else:
        lines.append("- 데이터 없음 (장소 검색 결과 0건)")
    lines.append("")

    # 1일 일정 제안
    lines.append("## 📅 1일 일정 제안")
    lines.append(f"- 오전: {city} 도착 및 주변 산책")
    lines.append("- 오후: 주요 행사 참여 및 맛집 방문")
    lines.append("- 저녁: 지역 야경 감상 후 귀가\n")

        # 오류 요약
    lines.append("## ⚠️ 오류 요약(errors)")
    if errors:
        for err in errors:
            # [단계] 유형: 메시지  형태로 보기 좋게 출력
            lines.append(f"- [{err['step']}] {err['type']}: {err['message']}")
    else:
        lines.append("- 발생한 오류가 없습니다.")
    lines.append("")

    # ⭐ ensure_ascii 걱정 없이 utf-8로 파일 저장 → 한글 안 깨짐
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return json_path, md_path


# ─────────────────────────────────────────────
# 5. 메인 실행 흐름
# ─────────────────────────────────────────────
def main():
    args = parse_args()
    date_str = args.date

    # 5-1. 입력값 검증
    if not validate_date(date_str):
        print('에러: 날짜 형식이 잘못되었습니다. 사용법: python main.py -date "YYYY-MM-DD"')
        return  # 잘못된 입력이면 여기서 종료

    # 오류를 누적해서 담을 리스트 (각 단계에서 실패해도 여기에 기록)
    errors = []

    # 5-2. LLM으로 추천 지역 생성
    print(f"\n[1/3] {date_str} 추천 지역 생성 중(LLM)...")
    recommendation = get_recommendation(date_str, errors)
    if recommendation:
        print(f'    - recommended_city: "{recommendation.get("recommended_city")}"')
    else:
        print("    - LLM 추천 생성 실패 → '데이터 없음'으로 처리하고 계속 진행합니다.")

    # 5-3. 지도 API로 맛집 검색
    #      LLM이 실패했으면 검색할 도시가 없으므로 건너뜀
    restaurants = []
    if recommendation and recommendation.get("recommended_city"):
        city = recommendation["recommended_city"]
        print(f"[2/3] '{city}' 맛집 검색 중(지도 API)...")
        restaurants = search_restaurants(city, errors)
        if restaurants:
            print(f"    - 맛집 {len(restaurants)}곳 검색 완료")
        else:
            print("    - EMPTY_RESULT: 맛집 섹션을 '데이터 없음'으로 처리하고 계속 진행합니다.")
    else:
        print("[2/3] 추천 도시가 없어 맛집 검색을 건너뜁니다.")

    # 5-4. 최종 리포트 저장
    print("[3/3] 최종 리포트 생성 및 저장 중...")
    json_path, md_path = save_results(date_str, recommendation, restaurants, errors)

    print(f"\n✅ 완료! {md_path} 를 확인하세요.")


# ─────────────────────────────────────────────
# 6. 프로그램 진입점
# ─────────────────────────────────────────────
if __name__ == "__main__":
    main()