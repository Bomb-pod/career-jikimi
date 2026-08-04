"""단독 검증 CLI — `python -m app.judgment.try`.

**이 단위를 DAG에서 앞으로 당긴 값어치가 여기서 나온다.** 채팅 UI도, 방도,
사용자도, DB도 필요 없다. 프롬프트를 고치고 바로 다시 돌릴 수 있다:

    python -m app.judgment.try \\
        --context "내일 회의 몇 시죠?" "10시입니다" "자료는 제가 준비할게요" \\
        --candidate "오늘 저녁에 치킨 어때?"

    score: 0.82  → 부적절 (threshold 0.7)
    latency: 1.4s   tokens: 312/8

**로그를 남기지 않는다.** DB에 붙지 않으므로 `judgment_logs`에 행이 생기지 않고,
지표도 오염되지 않는다. 실험은 실험으로 남는다.

**프롬프트 상수는 운영 경로와 같은 것을 쓴다** (`prompt.build_messages`). 두 벌이
되면 여기서 튜닝한 결과가 운영에 반영되지 않아 튜닝 자체가 무의미해진다.

요구사항에 없는 개발 도구다. 만들지 않아도 FR은 충족되지만, 없으면 앱이 완성될
때까지 프롬프트를 한 번도 돌려볼 수 없다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Final

from app.core.config import settings
from app.judgment.backend import call_model
from app.judgment.client import KIND_TIMEOUT, ModelCall
from app.judgment.constants import SCORE_MAX, SCORE_MIN, use_utf8_console
from app.judgment.prompt import build_messages
from app.judgment.types import ContextMessage

#: 문맥 화자를 몇 명으로 돌릴지의 기본값. `business-logic-model.md`의 예시가
#: A, B, A 세 줄 두 화자라 그 모양을 기본으로 둔다.
DEFAULT_SPEAKERS: Final[int] = 2

#: 화자 id는 아무 값이어도 된다 — 익명화가 라벨로 바꾼다. 실제 `users.id`와
#: 겹치지 않게 음수를 쓴다. **이 CLI는 DB를 보지 않으므로 충돌 자체가 없지만,**
#: 출력에 섞여도 실재하는 사용자로 오해되지 않게 한다.
_SENDER_BASE: Final[int] = -1


def build_context(texts: list[str], speakers: int) -> list[ContextMessage]:
    """문맥 문장들을 화자에 번갈아 배정한다.

    `seq`는 1부터 붙인다 — 이 CLI는 로그를 남기지 않아 실제 방의 seq와 맞출
    필요가 없고, `ContextMessage`가 seq를 요구하기 때문이다.
    """
    return [
        ContextMessage(sender_id=_SENDER_BASE - (index % speakers), text=text, seq=index + 1)
        for index, text in enumerate(texts)
    ]


def resolve_candidate_sender(speakers: int, sender: int | None) -> int:
    """후보 발신자의 화자 id를 정한다.

    Args:
        speakers: 문맥에 등장하는 화자 수.
        sender: 문맥의 몇 번째 화자인지(1-based). `None`이면 **문맥에 없는 새 화자**를
            준다 — 처음 말하는 사람이 끼어든 상황이 기본값이다.
    """
    if sender is None:
        return _SENDER_BASE - speakers
    return _SENDER_BASE - (sender - 1)


def format_result(call: ModelCall, threshold: float) -> str:
    """성공한 호출을 `business-logic-model.md` § 단독 검증 경로의 형식으로 출력한다."""
    raw = call.score if call.score is not None else 0.0
    score = min(SCORE_MAX, max(SCORE_MIN, raw))
    verdict = "부적절" if score >= threshold else "적절"

    lines = [f"score: {score:.2f}  → {verdict} (threshold {threshold})"]
    if score != raw:
        # 클램프는 조용히 하지 않는다 — 모델이 범위를 벗어나고 있다는 사실 자체가
        # 프롬프트 튜닝의 관찰값이다 (BR-6.6).
        lines.append(f"       (모델 원값 {raw} 를 클램프했습니다)")
    lines.append(
        f"latency: {call.latency_ms / 1000:.1f}s   "
        f"tokens: {call.prompt_tokens or 0}/{call.completion_tokens or 0}"
    )
    return "\n".join(lines)


def format_failure(call: ModelCall) -> str:
    """실패를 **원문 그대로** 보여준다.

    **판정 실패로 위장하지 않는다.** API 키가 없거나 모델이 `json_schema`를
    거부하는 것은 설정 문제이며, 그것을 "판정에 실패했습니다"로 덮으면 며칠을
    헤맨다. 이 CLI의 존재 이유가 원인을 즉시 보는 것이다.
    """
    lines = [
        f"호출 실패 ({call.error_kind}) — 시도 {call.attempts}회, {call.latency_ms / 1000:.1f}s",
        f"원문: {call.error}",
    ]
    if call.error_kind == KIND_TIMEOUT:
        lines.append(
            f"AI_TIMEOUT_SECONDS={settings.AI_TIMEOUT_SECONDS}초 안에 응답이 오지 않았습니다"
        )
    else:
        lines.append(
            "API 장애가 아니라 설정 문제일 수 있습니다 — OPENAI_API_KEY와 "
            f"모델({settings.active_model})을 확인하세요"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.judgment.try",
        description="채팅 앱 없이 판정 프롬프트를 돌려본다 (개발 도구, DB에 쓰지 않는다)",
    )
    parser.add_argument(
        "--context",
        nargs="*",
        default=[],
        metavar="문장",
        help="최근 대화. 오래된 것부터 순서대로 준다",
    )
    parser.add_argument(
        "--candidate",
        required=True,
        metavar="문장",
        help="판정 대상 — 지금 보내려는 메시지",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=DEFAULT_SPEAKERS,
        help=f"문맥의 화자 수. 문장을 번갈아 배정한다 (기본 {DEFAULT_SPEAKERS})",
    )
    parser.add_argument(
        "--sender",
        type=int,
        default=None,
        metavar="N",
        help="후보 발신자를 문맥의 N번째 화자로 둔다 (1-based). 기본은 문맥에 없는 새 화자",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=f"판정 임계값. 기본은 AI_VERDICT_THRESHOLD({settings.AI_VERDICT_THRESHOLD})",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="조립된 프롬프트를 그대로 출력한다 — 익명화가 맞는지 눈으로 본다",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="모델을 부르지 않고 프롬프트만 보여준다 (API 키 없이 익명화를 확인할 때)",
    )
    return parser


def _validate(args: argparse.Namespace) -> str | None:
    """인자 조합을 검사한다. 문제가 없으면 `None`."""
    if args.speakers < 1:
        return f"--speakers는 1 이상이어야 합니다: {args.speakers}"
    if args.sender is not None and not (1 <= args.sender <= args.speakers):
        return f"--sender는 1에서 {args.speakers} 사이여야 합니다: {args.sender}"
    if args.threshold is not None and not (SCORE_MIN <= args.threshold <= SCORE_MAX):
        return f"--threshold는 0.0에서 1.0 사이여야 합니다: {args.threshold}"
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 종료 코드를 돌려준다 — 0이면 점수를 받았다."""
    # `--help`의 문구에도 `—`가 들어 있으므로 파싱 **전에** 부른다.
    use_utf8_console()
    args = build_parser().parse_args(argv)

    problem = _validate(args)
    if problem is not None:
        print(problem, file=sys.stderr)
        return 2

    context = build_context(args.context, args.speakers)
    candidate_sender = resolve_candidate_sender(args.speakers, args.sender)
    messages = build_messages(context, candidate_sender, args.candidate)

    if args.show_prompt or args.dry_run:
        for message in messages:
            print(f"===== {message['role']} =====")
            print(message["content"])
            print()

    if args.dry_run:
        return 0

    threshold = args.threshold if args.threshold is not None else settings.AI_VERDICT_THRESHOLD
    call = asyncio.run(call_model(messages))

    if not call.ok:
        print(format_failure(call), file=sys.stderr)
        return 1

    print(format_result(call, threshold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
