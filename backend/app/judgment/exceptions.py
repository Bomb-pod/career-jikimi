"""`judgment`의 도메인 예외.

`auth`·`friends`와 같은 원리다 — U1의 `DomainError` 계열을 상속하면
`register_error_handlers()`가 붙여둔 단일 핸들러가 상태 코드와 본문을 만든다.
`code`가 클라이언트의 분기 키다.

**`Failed`는 여기에 없다.** 호출 실패는 예외가 아니라 `types.Failed`라는
반환값이다 (BR-6.7). 이 파일에 넣으면 호출자가 정상 흐름을 `try/except`로 쓰게
되고, 진짜 오류와 섞인다. FR-8이 정의한 degraded 경로가 그 정상 흐름이다.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import Conflict, DomainError, Forbidden


class AlreadyResolved(Conflict):
    """`user_action`이 이미 채워져 있다 — BR-7.1, 409.

    **이 예외가 `force_log_id`의 1회성을 실제로 보장하는 장치다.** 조건부 UPDATE의
    영향 행이 0일 때만 던진다 — SELECT 후 UPDATE로 짜면 동시 요청 둘이 모두 NULL을
    보고 모두 갱신해서, 더블클릭에 메시지가 두 개 저장된다.

    라벨이 덮어써지면 집계도 왜곡된다 (FR-7.3).
    """

    code = "ALREADY_RESOLVED"


class InvalidForceToken(DomainError):
    """`force_log_id`가 이 요청에 쓸 수 없는 값이다 — BR-6.9, 400.

    BR-6.9의 여섯 검사 중 **소유자 불일치를 뺀 다섯 개**가 전부 이 예외다:
    로그 없음 / 방 불일치 / 이미 소진됨 / 텍스트 불일치 / `verdict`가
    `appropriate`.

    **다섯 경우를 구분해 알려주지 않는다.** 구분하면 남의 로그 id의 존재 여부와
    상태가 새어나간다. 어느 쪽이든 클라이언트가 할 일은 같다 — 판정부터 다시 한다.

    `DomainError`를 직접 상속하는 이유 — U1의 하위 클래스 중 400이 없다.
    `ValidationFailed`는 422이고, 여기는 형식이 아니라 토큰의 유효성 문제다.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVALID_FORCE_TOKEN"


class ForceTokenForbidden(Forbidden):
    """그 판정 로그의 소유자가 호출자가 아니다 — BR-6.9, 403.

    **BR-6.9의 여섯 검사 중 유일한 403이다.** 남의 판정 로그로 강행 전송하는 것을
    막는다. 나머지 다섯은 `InvalidForceToken`(400)이다.

    소유자 불일치만 403인 이유 — 나머지는 "이 토큰은 못 쓴다"이고 이것은 "이건 네
    것이 아니다"다. 400으로 덮으면 서버가 남의 자원에 대한 접근을 입력 오류로
    보고하는 셈이 되어, 로그에서 공격 시도를 구분할 수 없게 된다.
    """

    code = "FORBIDDEN"


__all__ = [
    "AlreadyResolved",
    "ForceTokenForbidden",
    "InvalidForceToken",
]
