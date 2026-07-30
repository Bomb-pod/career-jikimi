"""`messages` — 저장된 메시지.

출처: `construction/messaging/functional-design/domain-entities.md` § messages
소유: U5 messaging. **U1은 구조만 만들고 읽거나 쓰지 않는다.**
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TABLE_KWARGS, Base

#: `verification_status`의 6값. **구분 기준은 "모델 호출을 시도했는가"다.**
#:
#: | 값                   | 모델 호출 | 판정 로그        | 언제                          |
#: |----------------------|-----------|------------------|-------------------------------|
#: | `ok`                 | 함        | 남김             | 성공, 점수 < 임계값           |
#: | `flagged_sent`       | 함        | 남김             | 성공, 부적절, 사용자가 강행    |
#: | `failed`             | 시도함    | 남김(verdict NULL)| 에러·타임아웃                 |
#: | `degraded`           | 안 함     | 안 남김          | degraded 상태여서 건너뜀       |
#: | `skipped_no_context` | 안 함     | 안 남김          | 방 메시지 < N                 |
#: | `disabled`           | 안 함     | 안 남김          | 발신자 토글 꺼짐              |
#:
#: `failed`와 `degraded`를 합치지 않는 이유가 여기 있다 — 합치면 API 실패 빈도를
#: 셀 때 degraded 구간이 섞여 과대 집계된다 (FR-7.1).
#:
#: U1은 이 값들을 **스키마 사실로만** 둔다. 어떤 상황에 어떤 값을 쓰는지는
#: U5(호출하지 않는 세 값)와 U2의 `JudgeResult`(호출 결과 세 값)가 정한다.
VERIFICATION_STATUS_VALUES: Final[tuple[str, ...]] = (
    "ok",
    "flagged_sent",
    "failed",
    "degraded",
    "skipped_no_context",
    "disabled",
)


class Message(Base):
    """방에 저장된 메시지 하나.

    생애주기: 저장된 뒤 신고/신고 취소만 오간다. **수정·삭제가 없다** —
    `seq` 기반 정렬과 히스토리 커서가 불변을 전제한다.

    **취소된 메시지는 이 테이블에 없다** (FR-7.2). 부적절 판정 후 사용자가
    취소하면 판정 로그만 남는다. 그래서 판정 성능 집계를 `verification_status`가
    아니라 `judgment_logs` 위에 정의해야 한다 — 그러지 않으면 TP가 영원히 0이 된다.
    """

    __tablename__ = "messages"
    __table_args__ = (
        # 채번 중복을 DB가 최종 방어한다. 애플리케이션 버그가 있어도 중복 seq가
        # 들어가지 않는다 (FR-4.2).
        sa.UniqueConstraint("room_id", "seq", name="uq_messages_room_seq"),
        # 히스토리 커서 페이지네이션 (FR-4.4) — 최신부터 거슬러 읽는다.
        # MariaDB 10.8+가 내림차순 인덱스를 실제로 지원한다(그 이전 버전은 DESC를
        # 파싱만 하고 무시했다). 이미지가 mariadb:11이므로 유효하다.
        sa.Index("ix_messages_room_seq_desc", "room_id", sa.text("seq DESC")),
        TABLE_KWARGS,
    )

    #: 클라이언트 중복 제거 키. 자기가 보낸 메시지가 HTTP 응답과 WebSocket 푸시
    #: 양쪽으로 오므로 이 ID로 걸러낸다 (FR-3.3, FR-4.3).
    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)

    room_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("rooms.id", name="fk_messages_room_id_rooms"),
        nullable=False,
    )
    sender_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", name="fk_messages_sender_id_users"),
        nullable=False,
    )

    #: **방 안에서 단조 증가** (FR-4.2). `rooms.last_seq`를 `FOR UPDATE`로 잠근
    #: 채 채번하므로 방 안에서 전순서가 보장된다.
    #:
    #: **정렬 기준은 이 컬럼이고 `created_at`이 아니다.** created_at은 동시 도착 시
    #: 같은 마이크로초를 가질 수 있고 시계가 뒤로 갈 수도 있다 (NFR-4).
    seq: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)

    #: 길이 상한이 없다(TEXT). 매우 긴 메시지가 판정 토큰 비용을 키우고
    #: `judgment_logs.candidate_text`에도 그대로 들어간다 — 상한은 U5가 정한다.
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)

    #: 6값 ENUM. `native_enum=True`(기본)이라 MariaDB에 ENUM(...)으로 만들어진다 —
    #: 정의에 없는 값이 들어가면 DB가 거부한다.
    verification_status: Mapped[str] = mapped_column(
        sa.Enum(*VERIFICATION_STATUS_VALUES, name="verification_status"),
        nullable=False,
    )

    #: 오발송 신고 시각 (FR-11.3). NULL이면 신고되지 않은 상태다.
    #:
    #: 별도 신고 테이블을 두지 않았다 — 발신자 본인이 자기 메시지에 한 번
    #: 신고하므로 1:1이다. 대신 **신고 이력이 남지 않는다**: 취소하면 NULL로
    #: 돌아가고 언제 신고했다 취소했는지 알 수 없다. 데모 범위에서 수용한다.
    misdirect_reported_at: Mapped[datetime | None] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=True,
    )

    #: **정렬 기준이 아니다.** 표시용이다 (위 `seq` 주석 참조).
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )

    def __repr__(self) -> str:
        return f"<Message id={self.id} room_id={self.room_id} seq={self.seq}>"
