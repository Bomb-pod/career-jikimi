"""`friends` 모듈 — 친구 검색·등록·별칭 관리.

`unit-of-work-dependency.md`가 기록한 **U3이 다른 단위에 제공하는 계약**을 여기서
재노출한다. **이 시그니처를 바꾸면 U4·U5가 깨진다:**

    from app.friends import resolve_display_names
    await resolve_display_names(session, owner_id, user_ids) -> dict[int, str]

U4가 방 참여자를, U5가 히스토리 발신자를 이 함수로 해석한다. **표시명 규칙의 단일
출처**이므로 두 단위가 자기 쪽에서 별칭을 조회하지 않는다 — 복제하면 한 화면에서만
상대의 본명이 보이는 버그가 생긴다 (FR-2.4, BR-2.8).

`router`를 여기서 import하지 않는다 — `main.py`만 `app.friends.router`를 본다.
"""

from app.friends.service import resolve_display_names

__all__ = ["resolve_display_names"]
