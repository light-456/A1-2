# main.py
import os
import re
import sys
import json
import argparse
from datetime import datetime
import requests
from dotenv import load_dotenv
from google import genai

# 윈도우 터미널 인코딩 에러 방지 설정
if sys.platform.startswith('win'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding='utf-8')

# 0. 환경설정
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")

GEMINI_MODEL = "gemini-3.5-flash"
KAKAO_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
RESULT_DIR = "results"

def parse_args():
    parser = argparse.ArgumentParser(description="국내 여행 추천 리포트 생성기")
    parser.add_argument("-date", "--date", dest="date", required=True, help='날짜 (YYYY-MM-DD)')
    return parser.parse_args()

def validate_date(date_str):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str): return False
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError: return False

def build_prompt(date_str, retry=False):
    base = f"""당신은 국내 여행 추천 전문가입니다. '{date_str}'에 가기 좋은 국내 여행지 한 곳을 추천해 주세요.
반드시 아래 JSON 형식으로만 답변하세요. 다른 설명이나 마크다운 백틱은 절대 붙이지 말고 순수 JSON만 출력하세요.
{{
  "recommended_city": "도시명",
  "weather": "해당 시기 날씨 요약",
  "events": ["행사1", "행사2"],
  "reason": "추천 이유"
}}"""
    if retry: base += "\n\n중요: 앞뒤 설명 없이 위 필수 키를 가진 순수 JSON 객체 하나만 출력하세요."
    return base

def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match: text = match.group(1)
    return json.loads(text)

def get_recommendation(date_str, errors):
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY가 없습니다.")
        sys.exit(1)
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(2):
        try:
            prompt = build_prompt(date_str, retry=(attempt == 1))
            response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
            return extract_json(response.text)
        except Exception as e:
            if attempt == 0: 
                print(f"    - LLM 파싱 재시도 중... ({e})")
                continue
            errors.append({"step": "LLM_API", "type": "PARSE_ERROR", "message": str(e)})
            return None

def search_restaurants(city, errors):
    if not KAKAO_API_KEY:
        errors.append({"step": "MAP_API", "type": "AUTH_ERROR", "message": "KAKAO_API_KEY 누락"})
        return []
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    try:
        res = requests.get(KAKAO_SEARCH_URL, headers=headers, params={"query": f"{city} 맛집", "size": 5}, timeout=10)
        res.raise_for_status()
        docs = res.json().get("documents", [])
        if not docs:
            errors.append({"step": "MAP_API", "type": "EMPTY_RESULT", "message": "검색 결과 0건"})
            return []
        return [{
            "name": d.get("place_name", ""),
            "address": d.get("road_address_name") or d.get("address_name", ""),
            "category": d.get("category_group_name", ""),
            "url": d.get("place_url", "")
        } for d in docs]
    except Exception as e:
        errors.append({"step": "MAP_API", "type": "NETWORK_ERROR", "message": str(e)})
        return []

def save_results(date_str, rec, rest, errors):
    os.makedirs(RESULT_DIR, exist_ok=True)
    
    # 1. JSON 저장
    with open(f"{RESULT_DIR}/{date_str}_data.json", "w", encoding="utf-8") as f:
        json.dump({"date": date_str, "recommendation": rec, "restaurants": rest, "errors": errors}, f, ensure_ascii=False, indent=4)
    
    # 2. Markdown 리포트 작성
    city = rec.get("recommended_city", "데이터 없음") if rec else "데이터 없음"
    lines = [f"# {date_str} 국내 여행 추천 리포트\n"]
    
    lines.append(f"## 📍 추천 지역: {city}\n")
    if rec:
        lines.append("## 📝 추천 이유")
        lines.append(rec.get("reason", "정보 없음") + "\n")
        lines.append("## 🌤 날씨 요약")
        lines.append(rec.get("weather", "정보 없음") + "\n")
        lines.append("## 🎊 행사/축제")
        events = rec.get("events", [])
        if events:
            for ev in events: lines.append(f"- {ev}")
        else:
            lines.append("- 정보 없음")
        lines.append("")
    else:
        lines.append("## 📝 추천 이유\n정보 없음\n")
        lines.append("## 🌤 날씨 요약\n정보 없음\n")
        lines.append("## 🎊 행사/축제\n- 정보 없음\n")

    lines.append("## 🍴 맛집 추천")
    if rest:
        for r in rest:
            lines.append(f"- **{r['name']}** ({r['category']})")
            lines.append(f"  - 주소: {r['address']}")
            if r['url']: lines.append(f"  - [상세보기]({r['url']})")
    else:
        lines.append("- 데이터 없음 (장소 검색 결과 0건)")
    lines.append("")

    lines.append("## 📅 1일 일정 제안")
    lines.append(f"- 오전: {city} 도착 및 주변 산책")
    lines.append("- 오후: 주요 행사 참여 및 맛집 탐방")
    lines.append("- 저녁: 지역 야경 감상 및 귀가\n")

    lines.append("## ⚠️ 오류 요약(errors)")
    if errors:
        for e in errors:
            lines.append(f"- [{e['step']}] {e['type']}: {e['message']}")
    else:
        lines.append("- 발생한 오류가 없습니다.")
    lines.append("")
    
    with open(f"{RESULT_DIR}/{date_str}_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def main():
    args = parse_args()
    if not validate_date(args.date):
        print('에러: 날짜 형식이 잘못되었습니다. 사용법: python main.py -date "YYYY-MM-DD"')
        sys.exit(1)
        
    errors = []
    print(f"\n[1/3] {args.date} 추천 지역 생성 중(LLM)...")
    rec = get_recommendation(args.date, errors)
    
    rest = []
    if rec and rec.get("recommended_city"):
        city = rec["recommended_city"]
        print(f"[2/3] '{city}' 맛집 검색 중(지도 API)...")
        rest = search_restaurants(city, errors)
    else:
        print("[2/3] 추천 도시가 없어 맛집 검색을 건너뜁니다.")
        
    print("[3/3] 최종 리포트 생성 중...")
    save_results(args.date, rec, rest, errors)
    print(f"\n✅ 완료! results/{args.date}_report.md 파일을 확인하세요.")

if __name__ == "__main__":
    main()