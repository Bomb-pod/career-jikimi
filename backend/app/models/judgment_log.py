"""`judgment_logs` — 모델 호출을 **시도한** 모든 건의 기록.

호출하지 않은 건(`disabled`·`skipped_no_context`·`degraded`)은 행이 없다 (FR-7.2).

출처: `construction/judgment-core/functional-design/domain-entities.md` § judgment_logs
소유: U2 judgment-core. **U1은 구조만 만들고 읽거나 쓰지 않는다.**
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Final

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TABLE_KWARGS, Base

#: 점수를 임계값으로 가른 결과. 호출이 실패하면 NULL이다.
VERDICT_VALUES: Final[tuple[str, ...]] = ("appropriate", "inappropriate")

#: 판정 이후 사용자가 실제로 한 행동 — **사실상의 정답 라벨**이다.
#:
#: | 값          | 언제                                    |
#: |-------------|-----------------------------------------|
#: | `auto_sent` | 적절 판정 → 묻지 않고 전송              |
#: | `sent`      | 부적절 판정 → 사용자가 "보내기"         |
#: | `cancelled` | 부적절 판정 → 사용자가 "취소"           |
#: | NULL        | 팝업이 떴는데 사용자가 답하지 않고 이탈  |
#:
#: NULL은 **오류가 아니라 관찰값이다.** "경고를 받고 아무것도 하지 않았다"는
#: 사실이 데이터다. precision 계산에서는 빼되 "미응답 건수"로 따로 센다 (BR-7.4).
USER_ACTION_VALUES: Final[tuple[str, ...]] = ("auto_sent", "sent", "cancelled")


class JudgmentLog(Base):
    """판정 시도 한 건.

    생애주기: 호출 시작과 함께 행이 생기고, 성공하면 score/verdict가 채워지며,
    사용자 응답으로 `user_action`이 종결된다. 응답 없이 이탈하면 `user_action`이
    NULL인 미해소 상태로 남는다.

    **`user_action`은 한 번만 쓰인다.** 이미 값이 있으면 덮어쓰지 않고 예외를
    던진다 — 이것이 `force_log_id`의 1회성을 실제로 보장하는 장치다 (BR-6.8).
    그 검사는 원자적 조건부 UPDATE여야 한다(`UPDATE ... WHERE user_action IS NULL`
    후 영향 행 수 확인). 읽고-나서-쓰기로 구현하면 이중 클릭에서 경쟁이 생긴다.
    강제는 U2의 `set_user_action()`이 한다 — DB 제약으로는 표현할 수 없다.
    """

    __tablename__ = "judgment_logs"
    __table_args__ = (
        # `force_log_id` 검증 조회를 커버한다 (소유자·방·미소비 확인).
        sa.Index("ix_judgment_logs_user_room_id", "user_id", "room_id", "id"),
        # 지표 집계의 기간 필터.
        sa.Index("ix_judgment_logs_created_at", "created_at"),
        # 집계가 `verdict IS NOT NULL`로 거르므로 (FR-7.4).
        sa.Index("ix_judgment_logs_verdict", "verdict"),
        TABLE_KWARGS,
    )

    #: U5가 `force_log_id`로 참조한다 (부적절 판정 후 강행 전송).
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)

    #: 로그 소유자. `force_log_id`의 소유권 검증에 쓰인다 — 남의 판정 로그로
    #: 강행 전송하는 것을 막는다.
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", name="fk_judgment_logs_user_id_users"),
        nullable=False,
    )

    #: 방 일치 검증에 쓰인다 — A방의 판정으로 B방에 강행 전송하는 것을 막는다.
    room_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("rooms.id", name="fk_judgment_logs_room_id_rooms"),
        nullable=False,
    )

    #: **NULL 허용.** 취소된 건은 메시지가 없다.
    #:
    #: 참조 방향이 중요하다 — 메시지가 로그를 가리키지 않고 로그가 메시지를
    #: 가리킨다. 메시지 없는 판정은 있어도, 판정 없는 메시지가 훨씬 흔하다
    #: (`disabled` 등).
    message_id: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("messages.id", name="fk_judgment_logs_message_id_messages"),
        nullable=True,
    )

    #: 실제로 모델에 넣은 문맥의 시작·끝 seq. 재현성을 위해 기록한다 —
    #: N은 환경변수라 언제든 바뀌고, 방에 메시지가 N개보다 적을 수도 있다.
    context_from_seq: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    context_to_seq: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)

    #: 판정 대상 문장. U5가 `force_log_id`로 재요청할 때 텍스트가 원래 판정받은
    #: 것과 같은지 검증해야 하므로 원문이 남아 있어야 한다 (BR-6.9).
    candidate_text: Mapped[str] = mapped_column(sa.Text, nullable=False)

    #: 0.000~1.000. **호출 실패면 NULL.**
    score: Mapped[Decimal | None] = mapped_column(sa.Numeric(4, 3), nullable=True)

    #: **호출 실패면 NULL.** score와 함께 NULL인 것이 호출 실패를 표현하는 방식이다
    #: (FR-8.1). 실패해도 행은 남는다 — API가 얼마나 자주 실패했는지 세려면
    #: 실패한 시도도 기록되어야 한다.
    verdict: Mapped[str | None] = mapped_column(
        sa.Enum(*VERDICT_VALUES, name="judgment_verdict"),
        nullable=True,
    )

    #: 판정 당시의 임계값. **점수만 남기고 기준을 안 남기면 데이터가 반쪽이 된다** —
    #: 임계값은 환경변수라 언제든 바뀌고, 나중에 로그를 볼 때 "이 판정은 어떤
    #: 기준으로 내려졌나"를 알 수 없으면 재현이 불가능하다.
    threshold: Mapped[Decimal] = mapped_column(sa.Numeric(4, 3), nullable=False)

    #: 실패해도 기록한다 — 타임아웃이 실제로 몇 초에서 끊겼는지가 관찰값이다.
    latency_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False)

    #: 비용 추적. 호출 실패면 NULL.
    prompt_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: **NULL 허용** — 미해소 로그(팝업에 응답하지 않고 이탈)는 NULL이다.
    #: 모듈 상단 `USER_ACTION_VALUES` 주석 참조.
    user_action: Mapped[str | None] = mapped_column(
        sa.Enum(*USER_ACTION_VALUES, name="judgment_user_action"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )

    def __repr__(self) -> str:
        return (
            f"<JudgmentLog id={self.id} room_id={self.room_id} "
            f"verdict={self.verdict!r} user_action={self.user_action!r}>"
        )
