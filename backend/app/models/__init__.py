"""테이블 6개의 SQLAlchemy 정의.

**스키마 전체를 U1에서 만드는 이유** — 테이블을 단위마다 나눠 만들면 마이그레이션
순서가 단위 순서에 묶여 병렬 작업이 막힌다. 스키마는 한 번에 세우고, 각 단위는
자기 테이블을 쓰기만 한다 (`inception/units-generation/unit-of-work.md` § U1).

**U1은 어떤 테이블도 읽거나 쓰지 않는다.** 여기 있는 것은 구조뿐이며, 각 테이블을
소유하는 단위는 다음과 같다:

| 테이블          | 소유 단위          |
|-----------------|--------------------|
| `users`         | U3 auth-friends    |
| `friendships`   | U3 auth-friends    |
| `rooms`         | U4 rooms-realtime  |
| `room_members`  | U4 rooms-realtime  |
| `messages`      | U5 messaging       |
| `judgment_logs` | U2 judgment-core   |

**이 파일이 전부를 import하는 이유** — Alembic의 `--autogenerate`가
`Base.metadata`를 보고 모델과 실제 스키마를 비교하는데, import되지 않은 모델은
metadata에 등록되지 않는다. 그러면 뒤 단위가 컬럼을 추가할 때 autogenerate가
"이 테이블은 DB에만 있고 모델에 없다"고 판단해 **DROP TABLE 마이그레이션을 만든다.**
"""

from app.models.friendship import Friendship
from app.models.judgment_log import (
    USER_ACTION_VALUES,
    VERDICT_VALUES,
    JudgmentLog,
)
from app.models.message import VERIFICATION_STATUS_VALUES, Message
from app.models.room import Room
from app.models.room_member import RoomMember
from app.models.user import User

__all__ = [
    "USER_ACTION_VALUES",
    "VERDICT_VALUES",
    "VERIFICATION_STATUS_VALUES",
    "Friendship",
    "JudgmentLog",
    "Message",
    "Room",
    "RoomMember",
    "User",
]
