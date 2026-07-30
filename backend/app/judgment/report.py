"""지표 리포트 CLI — `python -m app.judgment.report` (ADR-008).

    docker compose exec app python -m app.judgment.report
    docker compose exec app python -m app.judgment.report --since 2026-07-29

**UI 화면을 만들지 않는다.** ADR-008이 관리자 화면과 `GET /metrics` 엔드포인트를
모두 기각했다 — 화면·라우팅·권한 처리에 쓸 시간이 이 프로젝트의 가설과 무관하고,
판정 로그는 대화 내용의 파생물이라 "누가 볼 수 있는가"를 정해야 하기 때문이다.
관리자 화면이 필요해지면 나중에 `compute_metrics()`를 라우터에 붙이면 된다.

출력 형식은 `business-logic-model.md` § 리포트 출력 그대로다. 두 문구가 특히
중요하다:

- **precision 옆의 `※ 근사`** — 없으면 숫자가 정확한 측정값으로 읽힌다 (ASM-1).
- **recall의 `산출 불가 — 라벨 데이터셋 필요`** — 수치를 넣거나 항목을 빼지
  않는다 (BR-7.5).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import unicodedata
from datetime import datetime

from app.judgment.constants import (
    PRECISION_APPROXIMATE_MARK,
    PRECISION_FOOTNOTE,
    PRECISION_UNAVAILABLE,
    use_utf8_console,
)
from app.judgment.metrics import compute_metrics
from app.judgment.types import MetricsReport

#: 표의 가로줄. 값 열이 시작하는 자리와 맞춘다.
_RULE = "─" * 45

#: 라벨 열의 폭 — **글자 수가 아니라 터미널 칸 수다.**
_LABEL_WIDTH = 18


def _display_width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글·전각 문자는 두 칸이다.

    `f"{label:<16}"`처럼 글자 수로 채우면 한글 라벨과 영문 라벨의 값 시작 위치가
    어긋난다 — `판정 건수`(4글자)는 8칸을 먹고 `flag rate`(9글자)는 9칸을 먹는데
    파이썬은 둘을 4와 9로 세기 때문이다.
    """
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _row(label: str, value: str) -> str:
    return label + " " * max(1, _LABEL_WIDTH - _display_width(label)) + value


def _percent(value: float | None, numerator: int, denominator: int) -> str:
    """`18.3%  (26/142)`. 분모가 0이면 비율 없이 건수만 보여준다."""
    if value is None:
        return f"—      ({numerator}/{denominator})"
    return f"{value * 100:.1f}%  ({numerator}/{denominator})"


def _timestamp(value: datetime | None) -> str:
    return "—" if value is None else value.strftime("%Y-%m-%d")


def _latency(report: MetricsReport) -> str:
    if report.latency_p50_ms is None:
        return "—"
    return (
        f"p50 {report.latency_p50_ms / 1000:.1f}s  "
        f"p95 {report.latency_p95_ms / 1000:.1f}s  "  # type: ignore[operator]  # p50과 함께 채워진다
        f"max {report.latency_max_ms / 1000:.1f}s"  # type: ignore[operator]
    )


def _precision(report: MetricsReport) -> str:
    """precision 줄. **어느 경우에도 `※ 근사` 표시가 붙는다** (ASM-1).

    분모가 0이면 `산출 불가 — 부적절 판정 건이 없음`을 쓴다. recall의 문구와
    **다르다** — recall은 원리적으로 산출할 수 없고(라벨 모수가 없다), precision은
    이번 기간에 표본이 없을 뿐이다. 같은 문구를 쓰면 "데이터가 쌓이면 나오는 값"과
    "영원히 안 나오는 값"이 구별되지 않는다.
    """
    if report.precision is None:
        return f"{PRECISION_UNAVAILABLE}     {PRECISION_APPROXIMATE_MARK}"
    return (
        f"{report.precision:.3f}  "
        f"(TP {report.true_positives} / FP {report.false_positives})     "
        f"{PRECISION_APPROXIMATE_MARK}"
    )


def render_report(report: MetricsReport) -> str:
    """리포트를 사람이 읽는 표로 만든다. **출력과 계산을 분리해 테스트 가능하게 둔다.**"""
    lines = [
        f"판정 기간: {_timestamp(report.period_from)} ~ {_timestamp(report.period_to)}",
        _RULE,
        _row("판정 건수", str(report.judged_count)),
        _row(
            "flag rate",
            _percent(report.flag_rate, report.inappropriate_count, report.judged_count),
        ),
        _row("precision", _precision(report)),
        _row("미응답", f"{report.unanswered_count}건   ← 팝업 무시 신호"),
        _row("지연", _latency(report)),
        _row(
            "토큰",
            f"{report.tokens_total:,}  (프롬프트 {report.prompt_tokens_total:,} / "
            f"응답 {report.completion_tokens_total:,})",
        ),
        _row(
            "API 실패율",
            _percent(report.api_failure_rate, report.failed_count, report.attempted_count),
        ),
        _row(
            "신고율",
            _percent(report.report_rate, report.reported_count, report.messages_total),
        ),
        _row(
            "미검출 후보",
            f"{report.undetected_candidates}건   ← 모델이 ok라 했는데 사용자가 신고",
        ),
        # **문자열 그대로다.** 수치를 만들거나 항목을 빼지 않는다 (BR-7.5).
        _row("recall", report.recall),
        _RULE,
        PRECISION_FOOTNOTE,
    ]
    return "\n".join(lines)


def _parse_since(raw: str) -> datetime:
    """`--since`를 파싱한다. `YYYY-MM-DD`와 ISO 8601 둘 다 받는다."""
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"날짜 형식이 올바르지 않습니다: {raw!r} (예: 2026-07-29 또는 2026-07-29T09:00:00)"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.judgment.report",
        description="판정 지표 리포트 (FR-7.5, ADR-008)",
    )
    parser.add_argument(
        "--since",
        type=_parse_since,
        default=None,
        metavar="YYYY-MM-DD",
        help="이 날짜 이후의 판정만 집계한다. 없으면 전 기간",
    )
    return parser


async def _run(since: datetime | None) -> str:
    """세션을 열어 지표를 산출한다. **읽기만 하므로 커밋하지 않는다.**"""
    # DB 엔진은 여기서만 import한다 — 리포트를 돌리지 않는 경로가 커넥션 풀을
    # 만들 이유가 없다.
    from app.core.db import SessionLocal, dispose_engine

    try:
        async with SessionLocal() as session:
            report = await compute_metrics(session, since)
    finally:
        # **이벤트 루프가 닫히기 전에 커넥션을 정리한다.** 빼면 `asyncio.run()`이
        # 루프를 닫은 뒤 드라이버의 소멸자가 돌면서 "Event loop is closed"가
        # 리포트 뒤에 붙는다 — 지표를 보러 온 사람에게 오류처럼 보인다.
        await dispose_engine()
    return render_report(report)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점. 종료 코드를 돌려준다 — 0이면 성공.

    **DB에 닿지 못하면 스택트레이스가 아니라 사람이 읽을 수 있는 한 줄을 낸다.**
    이 명령을 컨테이너 밖에서 돌리면 `DATABASE_URL`의 호스트명 `db`가 풀리지
    않는데(compose 내부 이름이다), 그때 드라이버 예외를 그대로 토하면 원인이
    묻힌다. 원문은 `--` 없이 뒤에 붙여 남긴다.
    """
    # 리포트 본문과 `--help` 양쪽에 `—`·`※`가 들어 있다. cp949 콘솔에서 죽지
    # 않게 파싱 **전에** 부른다.
    use_utf8_console()
    args = build_parser().parse_args(argv)

    try:
        output = asyncio.run(_run(args.since))
    except Exception as exc:  # noqa: BLE001 - CLI 경계에서 예외를 사람 말로 바꾼다
        print(f"지표를 산출하지 못했습니다: {exc}", file=sys.stderr)
        print(
            "DB에 닿는지 확인하세요. 컨테이너 안에서 실행합니다: "
            "docker compose exec app python -m app.judgment.report",
            file=sys.stderr,
        )
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
