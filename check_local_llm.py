"""로컬 LLM이 이 프로젝트의 판정 경로를 그대로 소화할 수 있는지 검사한다.

프로젝트 코드를 건드리기 **전에** 돌린다. 확인하는 것 네 가지:

1. 엔드포인트가 살아 있는가
2. `prompt.py`의 실제 프롬프트를 소화하는가
3. `RESPONSE_FORMAT`(`strict: true`)을 받아주는가 — 안 받으면 대안이 무엇인가
4. NFR-1(정상 5초)을 지키는가

사용:
    cd backend
    .venv/Scripts/python.exe ../check_local_llm.py --model qwen3.5:4b
    .venv/Scripts/python.exe ../check_local_llm.py --model qwen3.5:4b --n 10   # 지연 표본 10회
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time

DEFAULT_BASE = "http://localhost:11434/v1"

# 프로젝트의 단일 출처를 그대로 쓴다. 여기서 문안을 복사해두면 두 벌이 되어
# 검사 결과와 운영이 어긋난다.
try:
    from app.judgment.constants import TEMPERATURE
    from app.judgment.prompt import RESPONSE_FORMAT, SCORE_KEY, build_messages
    from app.judgment.types import ContextMessage
except ImportError as exc:
    print(f"[중단] 프로젝트 모듈을 못 찾았다: {exc}")
    print("       backend/ 디렉터리에서 실행할 것:  cd backend && python ../check_local_llm.py")
    raise SystemExit(1)

# 오발송 상황 — 업무방 문맥 10개 + 잡담 후보
ROOM = [
    (12, "내일 배포 리허설 몇 시로 할까요?"),
    (7, "오전 10시면 될 것 같습니다"),
    (19, "저는 10시 좋습니다. 스테이징 먼저 올릴게요"),
    (12, "그럼 10시로 잡죠. 롤백 절차도 한 번 봐주세요"),
    (7, "롤백은 alembic downgrade 한 단계로 정리해뒀습니다"),
    (19, "스테이징 DB 스냅샷도 떠둘까요?"),
    (12, "네 부탁드려요. 용량은 얼마나 되나요"),
    (19, "덤프가 약 400MB 정도입니다"),
    (7, "그 정도면 복원도 2분 안 걸립니다"),
    (12, "좋네요. 그럼 내일 10시에 봅시다"),
]
CTX = [ContextMessage(sender_id=s, text=t, seq=41 + i) for i, (s, t) in enumerate(ROOM)]

# (후보 문장, 부적합해야 하는가)
CASES = [
    ("오늘 저녁에 치킨 어때? 양념 vs 후라이드", True),
    ("복원 스크립트도 같이 올려둘게요. 10시 전에 확인 부탁드립니다", False),
    ("아 맞다, 리허설 끝나고 점심 같이 하실 분?", False),  # 자연스러운 화제 전환 — 잡으면 안 된다
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--model", required=True, help="예: qwen3.5:4b")
    ap.add_argument("--api-key", default="ollama", help="Ollama는 무시하지만 SDK가 요구한다")
    ap.add_argument("--n", type=int, default=3, help="지연 표본 수")
    ap.add_argument("--timeout", type=float, default=30.0, help="검사용 — 운영값(4초)보다 넉넉히")
    args = ap.parse_args()

    try:
        from openai import OpenAI
    except ImportError:
        print("[중단] openai 패키지가 없다. backend/.venv 에서 실행할 것.")
        return 1

    client = OpenAI(base_url=args.base_url, api_key=args.api_key, max_retries=0)
    messages = build_messages(context=CTX, candidate_sender_id=7, candidate_text=CASES[0][0])

    print(f"엔드포인트 {args.base_url}")
    print(f"모델       {args.model}\n")

    # --- 1) strict json_schema 를 받아주는가 -------------------------------
    print("[1] Structured Outputs (strict: true)")
    mode = None
    try:
        t0 = time.time()
        r = client.chat.completions.create(
            model=args.model, messages=messages,
            response_format=RESPONSE_FORMAT, temperature=TEMPERATURE,
            timeout=args.timeout,
        )
        json.loads(r.choices[0].message.content or "")[SCORE_KEY]
        mode = "strict"
        print(f"    지원함 ({time.time()-t0:.1f}초) — 코드 변경 없이 그대로 쓸 수 있다\n")
    except Exception as exc:
        print(f"    거절: {type(exc).__name__}: {str(exc)[:150]}")
        print("[1-b] JSON 모드 폴백 시도")
        try:
            t0 = time.time()
            r = client.chat.completions.create(
                model=args.model, messages=messages,
                response_format={"type": "json_object"}, temperature=TEMPERATURE,
                timeout=args.timeout,
            )
            json.loads(r.choices[0].message.content or "")[SCORE_KEY]
            mode = "json_object"
            print(f"    JSON 모드는 됨 ({time.time()-t0:.1f}초)")
            print("    → prompt.py 의 RESPONSE_FORMAT 을 {'type': 'json_object'} 로 바꾸고,")
            print("      system 프롬프트 끝에 '{\"score\": 0.0} 형태로만 답하십시오.' 한 줄 추가 필요\n")
        except Exception as exc2:
            print(f"    실패: {type(exc2).__name__}: {str(exc2)[:150]}")
            print("    → 이 모델/엔드포인트로는 구조화 출력이 안 된다. 다른 모델을 볼 것.\n")
            return 1

    fmt = RESPONSE_FORMAT if mode == "strict" else {"type": "json_object"}

    # --- 2) 판정이 방향을 맞히는가 ---------------------------------------
    print("[2] 판정 방향 (threshold 0.7 기준)")
    ok = 0
    for text, should_flag in CASES:
        msgs = build_messages(context=CTX, candidate_sender_id=7, candidate_text=text)
        try:
            r = client.chat.completions.create(
                model=args.model, messages=msgs, response_format=fmt,
                temperature=TEMPERATURE, timeout=args.timeout,
            )
            score = float(json.loads(r.choices[0].message.content or "")[SCORE_KEY])
        except Exception as exc:
            print(f"    실패 {type(exc).__name__} — {text[:28]}")
            continue
        flagged = score >= 0.7
        hit = flagged == should_flag
        ok += hit
        print(f"    {'O' if hit else 'X'} score={score:.2f}  기대={'부적합' if should_flag else '적합'}"
              f"  | {text[:34]}")
    print(f"    {ok}/{len(CASES)} 일치\n")

    # --- 3) 지연 ----------------------------------------------------------
    print(f"[3] 지연 ({args.n}회)")
    lat = []
    for _ in range(args.n):
        t0 = time.time()
        try:
            client.chat.completions.create(
                model=args.model, messages=messages, response_format=fmt,
                temperature=TEMPERATURE, timeout=args.timeout,
            )
        except Exception:
            continue
        lat.append(time.time() - t0)
    if lat:
        print(f"    중앙값 {statistics.median(lat):.2f}s | 최대 {max(lat):.2f}s")
        print(f"    AI_TIMEOUT_SECONDS=4.0 초과: {sum(l > 4.0 for l in lat)}/{len(lat)}건")
        if max(lat) > 4.0:
            print("    → 운영 타임아웃(4초)을 넘는다. 더 작은 모델이나 양자화를 볼 것.")
        else:
            print("    → NFR-1(정상 5초) 안에 든다.")
    print()

    # --- 4) 적용 방법 -----------------------------------------------------
    print("=" * 62)
    print("적용 방법 (검사를 통과했다면)")
    print("=" * 62)
    print("1) core/config.py 에 한 줄 추가:")
    print("       OPENAI_BASE_URL: str | None = None")
    print("2) judgment/client.py 의 AsyncOpenAI(...) 에 인자 추가:")
    print("       base_url=settings.OPENAI_BASE_URL,")
    print("3) .env:")
    print(f"       OPENAI_BASE_URL={args.base_url.replace('localhost', 'host.docker.internal')}")
    print(f"       OPENAI_MODEL={args.model}")
    print("       OPENAI_API_KEY=ollama")
    if mode != "strict":
        print("4) prompt.py 의 RESPONSE_FORMAT 을 json_object 로 교체 (위 1-b 참조)")
    print("\n그 뒤 evaluate 로 1000행 실측:")
    print("       python -m app.judgment.evaluate --limit 40")
    return 0


if __name__ == "__main__":
    sys.exit(main())
