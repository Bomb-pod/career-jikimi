"""`rooms` 모듈 — 방 생성·목록·상세·읽음 처리·AI 검증 토글, 그리고 WebSocket 수명주기.

`unit-of-work-dependency.md`가 기록한 **U4가 U5에 제공하는 계약** 둘을 여기서
재노출한다. **이 두 이름과 시그니처를 바꾸면 U5가 깨진다:**

    from app.rooms import get_membership   # 참여 자격 + ai_check_enabled를 한 번에
    from app.rooms import member_user_ids  # 브로드캐스트 대상

세 번째 계약인 `push_to_users()`는 `app.core.ws_registry`에 있다 — 연결 레지스트리는
`components.md`가 `core` 소유로 두었고, 방 개념과 무관하게 사용자 id로만 동작한다.

`get_membership()`이 자격과 토글을 **한 번에** 주는 것이 계약의 요점이다. U5의
`send_message()` 1단계가 그 둘을 함께 필요로 하며, 나눠 두면 같은 행을 두 번 읽는다.

`router`와 `ws`를 여기서 import하지 않는다 — 그러면 서비스 함수만 쓰려는 U5가
FastAPI 라우터 정의까지 끌고 들어온다. `main.py`만 `app.rooms.router`를 본다.
"""

from app.rooms.service import get_membership, member_user_ids

__all__ = ["get_membership", "member_user_ids"]
