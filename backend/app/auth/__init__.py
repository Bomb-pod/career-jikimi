"""`auth` 모듈 — 회원가입·로그인·토큰 검증.

`unit-of-work-dependency.md`가 기록한 **U3이 다른 단위에 제공하는 계약** 두 개를
여기서 재노출한다. **이 두 이름과 시그니처를 바꾸면 U4·U5가 깨진다:**

    from app.auth import verify_token   # 동기 순수 함수 — U4의 WebSocket 첫 프레임
    from app.auth import current_user   # FastAPI 의존성 — 모든 보호 엔드포인트

`verify_token()`이 의존성이 **아닌** 것이 FR-1.3의 요구다. 브라우저는 WebSocket에
커스텀 헤더를 붙일 수 없어(CON-4) 토큰이 첫 프레임으로 온다. 의존성으로 만들면
U4가 재사용할 수 없어 검증 로직이 두 벌이 되고, 두 벌은 반드시 어긋난다.

`router`를 여기서 import하지 않는다 — 그러면 `verify_token`만 쓰려는 U4가 FastAPI
라우터 정의까지 끌고 들어온다. `main.py`만 `app.auth.router`를 본다.
"""

from app.auth.security import verify_token
from app.auth.service import current_user

__all__ = ["current_user", "verify_token"]
