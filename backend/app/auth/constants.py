"""`auth` 모듈의 상수.

값을 별도 모듈에 두는 이유 — 비밀번호 최소 길이는 **서버 검증**(`service.py`)과
**오류 문구**(`exceptions.py`) 두 곳에서 쓰인다. 리터럴을 두 곳에 두면 하나만
바꿨을 때 "8자 이상이어야 합니다"라는 문구와 실제 검사가 어긋난다.

프론트엔드에도 같은 값이 `frontend/src/lib/constants.ts`에 있다(제출 전 검사로
왕복을 아끼기 위해서다). **문구는 복제하지 않는다** — 프론트는 서버가 준
`message`를 그대로 보여주고 자기 문구를 만들지 않는다
(`code-generation-plan.md` § 이 계획이 닫는 열린 항목).
"""

from __future__ import annotations

from typing import Final

#: BR-1.2. 8자는 이 프로젝트에서 정한 값이다(requirements.md ASM-5).
#: **상한은 두지 않는다** — argon2는 bcrypt의 72바이트 절단이 없으므로
#: 상한을 둘 이유가 없다.
PASSWORD_MIN_LENGTH: Final[int] = 8

#: `users.username`·`users.display_name`의 VARCHAR(50)과 같은 값
#: (`domain-entities.md` § users). 요청 스키마가 이 길이로 입력을 자른다 —
#: 없으면 51자 아이디가 DB까지 내려가 드라이버 오류(500)가 된다.
USERNAME_MAX_LENGTH: Final[int] = 50
