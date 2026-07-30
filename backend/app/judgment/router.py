"""`PATCH /judgments/{id}` — 판정 팝업에 대한 사용자의 응답을 기록한다 (W3).

**이 단위의 유일한 HTTP 표면이다.** 지표는 화면이 아니라 CLI로 노출하므로
(ADR-008) `GET /metrics`도 관리자 화면도 없다.

**왜 이 엔드포인트가 필요한가** — 부적절 판정 후 "보내기"는 U5의
`POST /rooms/{id}/messages`가 `force_log_id`와 함께 처리하면서 `user_action='sent'`를
남긴다. 그런데 **"취소"는 전송이 없어서** 그 경로를 타지 않는다. 취소를 기록할 곳이
없으면 TP가 영원히 0이 되어 precision이 계산되지 않는다 (FR-7.3, BR-7.2).
"""

from __future__ import annotations

from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import current_user
from app.core.db import get_session
from app.judgment.exceptions import ForceTokenForbidden
from app.judgment.service import set_user_action
from app.models import JudgmentLog, User

router = APIRouter(tags=["judgment"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(current_user)]


class UserActionRequest(BaseModel):
    """팝업에서 사용자가 고른 것.

    **`auto_sent`를 받지 않는다.** 그것은 "적절 판정이라 묻지 않고 보냈다"는
    서버가 붙이는 라벨이며(FR-7.2), U5가 전송 경로에서 직접 기록한다. 클라이언트가
    그 값을 주장하게 두면 "물어봤는데 안 물어본 것으로 기록된" 로그가 생겨
    FR-7.3의 라벨 의미가 무너진다. 팝업의 선택지는 둘뿐이다 (FR-6.6).
    """

    user_action: Annotated[
        Literal["sent", "cancelled"],
        Field(description="팝업에서 고른 것. `sent`=보내기, `cancelled`=취소"),
    ]


@router.patch(
    "/judgments/{log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    # **명시적 `None`이 필요하다.** 생략하면 FastAPI가 `-> None` 반환 애노테이션에서
    # 응답 모델을 추론하고, 204는 본문을 가질 수 없어 기동 시점에 단언이 깨진다.
    response_model=None,
    summary="판정 팝업에 대한 사용자의 응답 기록",
    responses={
        403: {
            "description": (
                "`FORBIDDEN` — 남의 판정 로그이거나 **존재하지 않는 id**. "
                "404를 주지 않는 이유는 id의 존재 여부가 새기 때문이다"
            )
        },
        409: {"description": "`ALREADY_RESOLVED` — 이미 응답이 기록됨 (BR-7.1)"},
    },
)
async def record_user_action(
    payload: UserActionRequest,
    session: SessionDep,
    caller: CurrentUser,
    log_id: Annotated[int, Path(ge=1, description="`judgment_logs.id`")],
) -> None:
    """판정 로그에 `user_action`을 기록한다 — **한 번만 쓰인다** (BR-7.1).

    두 번째 호출은 409다. 더블클릭이 라벨을 덮어쓰지 못하게 하는 것이 그 규칙의
    목적이며, 실제 강제는 서비스의 조건부 UPDATE가 한다.

    **소유권 확인이 갱신과 별개인 이유** — `set_user_action()`의 조건절은
    "아직 비어 있는가"만 본다(그것이 경쟁 조건이 실제로 발생하는 지점이다).
    소유권은 경쟁하지 않는다 — 로그의 주인은 바뀌지 않으므로 미리 확인해도 안전하고,
    그래야 403(남의 것)과 409(이미 응답함)를 구분해 돌려줄 수 있다.

    없는 id에도 404가 아니라 403을 준다 — U3의 `PATCH /friends/{id}`와 같은 이유다
    (BR-2.7). 404를 주면 남의 판정 로그 id의 존재 여부가 새어나간다.
    """
    owned = await session.scalar(
        sa.select(JudgmentLog.id).where(
            JudgmentLog.id == log_id,
            JudgmentLog.user_id == caller.id,
        )
    )
    if owned is None:
        raise ForceTokenForbidden("이 판정 결과에 대한 권한이 없습니다")

    await set_user_action(session, log_id, payload.user_action)


__all__ = ["UserActionRequest", "router"]
