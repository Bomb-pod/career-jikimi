"""데모용 친구·방·대화 시드 — `test1`~`test8` 계정 위에 쌓는다.

발표 리허설을 몇 번이든 같은 상태에서 다시 시작할 수 있게 하는 것이 이 스크립트의
목적이다. 손으로 만든 데이터는 두 번째 리허설에서 이미 달라져 있다.

**계정은 만들지도 지우지도 않는다.** 사람이 화면에서 가입한 `test1`~`test8`을
찾아 쓸 뿐이다. 하나라도 없으면 아무것도 하지 않고 멈춘다 — 절반만 심긴 상태가
가장 나쁘다.

실행 (컨테이너에 바인드 마운트가 없으므로 stdin으로 밀어 넣는다):

    docker compose exec -T app python - < backend/scripts/seed_demo.py

`--keep`을 주면 기존 친구·방·대화를 지우지 않고 덧붙인다. 기본은 **지우고 다시
심는다** — 리허설마다 같은 화면에서 시작하는 것이 목적이기 때문이다.

    docker compose exec -T app python - --keep < backend/scripts/seed_demo.py

---

## 왜 방 네 개인가

이 앱이 잡으려는 것은 **문맥 부적합**이다. 그러므로 데모 데이터의 값어치는 방의
개수가 아니라 **방과 방 사이의 거리**에 있다. 네 방의 말투와 화제가 서로 멀수록
"이 방에 맞지 않는다"는 판정이 눈에 보인다:

| 방 | 말투 | 화제 |
|---|---|---|
| 개발 3팀 | 존댓말·업무 | 배포, 리뷰, 일정 |
| 가족방 | 반말·가족 | 밥, 주말, 생신 |
| 동아리 번개 | 반말·또래 | 약속, 고깃집 |
| (1:1) 이수민 | 반말·동기 | 회의 뒷담화 |

시연은 한 방의 문장을 다른 방에 넣어보는 것으로 충분하다. 예를 들어 **개발 3팀**에
"엄마 나 토요일 6시에 갈게"를 치거나, **가족방**에 "스테이징 배포 금요일 3시로
잡겠습니다"를 친다.

## 심는 메시지의 `verification_status`가 `disabled`인 이유

여섯 값 중 **모델을 부르지 않았다는 사실을 그대로 말하는 값**이면서 화면에
"검증 안 됨" 배지를 띄우지 않는 유일한 값이다.

- `ok`는 거짓이다 — 모델이 통과시킨 적이 없다. 지표의 `_STATUS_OK` 필터에도 걸린다
- `skipped_no_context`가 사실에 더 가깝지만 배지가 붙어 시연 화면이 지저분해진다
- `failed`·`degraded`도 배지가 붙고, 있지도 않았던 장애를 암시한다

`ai_check_enabled`는 전원 켜짐인데 심은 메시지는 `disabled`라 둘이 어긋나 보인다.
이것은 시드의 흔적이며, 시연 중 **실제로 보내는** 메시지부터는 정상 경로를 탄다.

## 문맥 개수

`AI_CONTEXT_N`(기본 10)보다 방 메시지가 적으면 판정이 통째로 건너뛰어진다
(FR-6.4, `skipped_no_context`). 네 방 모두 그 값보다 넉넉히 많게 심는 이유다 —
메시지가 모자라면 시연에서 팝업이 아예 뜨지 않고, 그 원인은 화면에 나타나지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa

from app.core.config import settings
from app.core.db import SessionLocal, dispose_engine
from app.models import Friendship, JudgmentLog, Message, Room, RoomMember, User

#: 시드가 쓰는 계정. 이 순서가 아래 표의 키다.
USERNAMES: Final[tuple[str, ...]] = (
    "test1",
    "test2",
    "test3",
    "test4",
    "test5",
    "test6",
    "test7",
    "test8",
)

#: `(등록자, 대상) -> 별칭`. 별칭은 **등록자마다 다르다** — 같은 사람이 화면마다
#: 다른 이름으로 보이는 것이 FR-2.4·BR-2.8이 의도한 동작이고, 시드가 그것을
#: 보여주지 못하면 시연에서 표시명 해석이 그냥 계정 이름처럼 보인다.
#:
#: **양방향으로 등록한다.** 친구 관계는 단방향이지만(BR-2.3), 한쪽만 등록하면
#: 반대쪽 계정으로 로그인했을 때 상대가 `test4` 같은 계정명으로 보이고 방을 새로
#: 만들 수도 없다. 여덟 대의 화면 중 어느 것을 열어도 말이 되게 하려면 양쪽이 필요하다.
ALIASES: Final[dict[tuple[str, str], str]] = {
    # 개발 3팀 — 존댓말, 직급이 별칭에 드러난다
    ("test1", "test2"): "서연 팀장님",
    ("test1", "test3"): "준호 대리님",
    ("test1", "test4"): "수민 동기",
    ("test2", "test1"): "지환 사원",
    ("test2", "test3"): "박준호 대리",
    ("test2", "test4"): "이수민 사원",
    ("test3", "test1"): "지환씨",
    ("test3", "test2"): "서연 팀장님",
    ("test3", "test4"): "수민씨",
    ("test4", "test1"): "지환",
    ("test4", "test2"): "서연 팀장님",
    ("test4", "test3"): "준호 대리님",
    # 가족
    ("test1", "test5"): "엄마",
    ("test1", "test6"): "형",
    ("test5", "test1"): "지환",
    ("test5", "test6"): "도현",
    ("test6", "test1"): "지환",
    ("test6", "test5"): "엄마",
    # 동아리
    ("test1", "test7"): "민지 (동아리)",
    ("test1", "test8"): "태현 (동아리)",
    ("test7", "test1"): "지환 선배",
    ("test7", "test8"): "태현",
    ("test8", "test1"): "지환 선배",
    ("test8", "test7"): "민지",
}

#: 방 하나의 정의 — `(이름, 만든 사람, 참여자, 대화)`.
#:
#: 대화는 `(보낸 사람, 본문)`의 순서 있는 목록이다. `seq`는 1부터 이 순서 그대로
#: 매긴다 — 정렬 기준이 `created_at`이 아니라 `(room_id, seq)`이기 때문이다.
ROOMS: Final[tuple[dict[str, Any], ...]] = (
    {
        "name": "개발 3팀",
        "created_by": "test1",
        "members": ("test1", "test2", "test3", "test4"),
        "messages": (
            ("test2", "다들 좋은 아침입니다. 오늘 스탠드업은 10시에 하겠습니다"),
            ("test1", "네 팀장님, 준비하겠습니다"),
            ("test3", "확인했습니다"),
            ("test4", "넵"),
            ("test2", "지환 사원, 어제 말한 결제 모듈 리팩터링은 어디까지 됐나요"),
            (
                "test1",
                "인터페이스 분리까지 끝냈고 지금 테스트 보강 중입니다. 오늘 중으로 PR 올리겠습니다",
            ),
            ("test2", "좋습니다. 리뷰는 준호 대리가 맡아주세요"),
            ("test3", "알겠습니다. PR 올라오면 오늘 안에 보겠습니다"),
            ("test4", "저는 로그 수집 쪽 이슈를 하나 잡고 있는데 내일까지 걸릴 것 같습니다"),
            ("test2", "네, 무리하지 말고 진행 상황만 공유해주세요"),
            ("test1", "팀장님, 스테이징 배포는 언제로 잡을까요"),
            ("test2", "금요일 오후 3시로 봅시다. 그 전까지 QA를 마무리하는 걸로 하죠"),
            ("test3", "그럼 목요일까지 리뷰 다 끝내겠습니다"),
            ("test4", "QA 시나리오는 제가 오늘 정리해서 공유드리겠습니다"),
            ("test2", "좋습니다. 회의록은 공유 문서에 정리해두겠습니다"),
        ),
    },
    {
        "name": "가족방",
        "created_by": "test1",
        "members": ("test1", "test5", "test6"),
        "messages": (
            ("test5", "지환아 밥은 먹었니"),
            ("test1", "응 엄마 방금 먹었어"),
            ("test5", "뭐 먹었어"),
            ("test1", "회사 앞에서 김치찌개"),
            ("test6", "나도 방금 점심 먹음"),
            ("test5", "도현이는 뭐 먹었어"),
            ("test6", "편의점 도시락 ㅋㅋ"),
            ("test5", "그런 거 그만 먹고 밥 좀 제대로 챙겨 먹어라"),
            ("test6", "넵"),
            ("test5", "이번 주말에 다 올 수 있니? 아빠 생신이잖아"),
            ("test1", "나는 토요일 저녁에 갈 수 있어"),
            ("test6", "나도 토요일 괜찮아"),
            ("test5", "그래 그럼 토요일 6시에 보자"),
            ("test1", "케이크는 내가 사갈게"),
        ),
    },
    {
        "name": "동아리 번개",
        "created_by": "test1",
        "members": ("test1", "test7", "test8"),
        "messages": (
            ("test7", "얘들아 이번 주 금요일에 번개 어때"),
            ("test8", "콜"),
            ("test1", "좋지 금요일 몇 시"),
            ("test7", "7시쯤? 학교 앞에서 보자"),
            ("test8", "나 7시 반까지는 갈 수 있을 듯"),
            ("test1", "그럼 7시 반으로 하자"),
            ("test7", "ㅇㅋ 어디서 먹을지 정하자"),
            ("test8", "저번에 갔던 고깃집 어때"),
            ("test1", "거기 좋았지 나 찬성"),
            ("test7", "그럼 거기로 예약할게"),
            ("test8", "굿굿"),
            ("test7", "예약했다 금요일 7시 반 3명"),
            ("test1", "오키 금요일에 보자"),
        ),
    },
    {
        # 이름이 없는 1:1 방 — 화면이 참여자 표시명으로 제목을 조립한다.
        "name": None,
        "created_by": "test1",
        "members": ("test1", "test4"),
        "messages": (
            ("test4", "야 오늘 회의 어땠어"),
            ("test1", "아 진짜 길더라"),
            ("test4", "그니까 30분이면 될 걸 한 시간 반 했잖아 ㅋㅋ"),
            ("test1", "ㅋㅋㅋㅋ 나 중간에 졸 뻔했어"),
            ("test4", "근데 너 리팩터링 그거 진짜 혼자 다 하는 거야?"),
            ("test1", "어 일단은"),
            ("test4", "무리하지 마 그거 원래 두 명이 붙을 일이야"),
            ("test1", "알지 근데 일정이 이미 잡혀서"),
            ("test4", "팀장님한테 그냥 말해봐"),
            ("test1", "말하면 또 회의 잡을걸 ㅋㅋ"),
            ("test4", "ㅋㅋㅋㅋㅋ 맞네"),
            ("test1", "이따 커피나 마시자"),
            ("test4", "콜 3시에 1층에서"),
        ),
    },
)

#: 시연 시작 화면에 배지 하나를 남긴다 — `(방 index, 계정, 안 읽은 개수)`.
#:
#: 전부 읽음으로 두면 배지 기능이 화면에 아예 나타나지 않고, 전부 안 읽음으로 두면
#: 어느 방이 새 소식인지 구분이 안 된다. 하나만 남기는 것이 둘 다 피한다.
UNREAD: Final[tuple[tuple[int, str, int], ...]] = ((2, "test1", 3),)

#: 심는 메시지의 검증 상태. 모듈 docstring § 참조.
SEED_STATUS: Final[str] = "disabled"


async def _resolve_users(session: Any) -> dict[str, User]:
    """`test1`~`test8`을 찾는다. 하나라도 없으면 멈춘다.

    Raises:
        SystemExit: 계정이 하나라도 없다.

    **여기서 가입시키지 않는다.** 비밀번호를 이 스크립트가 정하면 사람이 화면에서
    쓰던 비밀번호와 달라지고, 시연 직전에 로그인이 안 되는 것으로 드러난다.
    """
    rows = await session.execute(sa.select(User).where(User.username.in_(USERNAMES)))
    found = {user.username: user for user in rows.scalars().all()}

    missing = [username for username in USERNAMES if username not in found]
    if missing:
        raise SystemExit(
            f"계정이 없습니다: {', '.join(missing)}\n"
            "화면에서 먼저 가입한 뒤 다시 실행하세요 — 이 스크립트는 계정을 만들지 않습니다."
        )
    return found


async def _wipe(session: Any) -> None:
    """기존 친구·방·대화를 지운다.

    **삭제 순서가 FK 역순이다.** `judgment_logs`가 `messages`와 `rooms`를,
    `messages`와 `room_members`가 `rooms`를 참조하므로 자식부터 지운다. FK가
    RESTRICT라(ondelete 없음) 순서를 틀리면 지워지지 않고 오류가 난다.

    **`users`는 건드리지 않는다.** 사람이 가입한 계정이고, 지우면 다시 가입해야 한다.
    """
    for model in (JudgmentLog, Message, RoomMember, Room, Friendship):
        result = await session.execute(sa.delete(model))
        print(f"  {model.__tablename__} {result.rowcount}행 삭제")


async def _seed_friendships(session: Any, users: dict[str, User]) -> int:
    """`ALIASES` 표 그대로 친구 행을 만든다."""
    session.add_all(
        [
            Friendship(owner_id=users[owner].id, friend_id=users[friend].id, alias=alias)
            for (owner, friend), alias in ALIASES.items()
        ]
    )
    await session.flush()
    return len(ALIASES)


async def _seed_room(
    session: Any, users: dict[str, User], spec: dict[str, Any], started_at: datetime
) -> Room:
    """방 하나와 그 대화를 만든다.

    Args:
        started_at: 이 방의 첫 메시지 시각. 이후 메시지는 여기서 2분씩 벌어진다.

    **`rooms.last_seq`를 메시지 개수에 맞춘다.** 안 맞추면 시연 중 첫 전송이 seq 1을
    다시 받아 `UNIQUE (room_id, seq)`에 걸린다 — 화면에는 전송 실패로만 보이고
    원인은 드러나지 않는다.

    `created_at`을 명시하는 이유는 서버 기본값(`CURRENT_TIMESTAMP`)을 쓰면 심은
    메시지 수십 개가 전부 같은 초에 몰려 시각이 무의미해지기 때문이다.
    """
    room = Room(
        name=spec["name"],
        created_by=users[spec["created_by"]].id,
        created_at=started_at - timedelta(minutes=5),
    )
    session.add(room)
    await session.flush()

    messages = spec["messages"]
    session.add_all(
        [
            Message(
                room_id=room.id,
                sender_id=users[sender].id,
                seq=offset + 1,
                body=body,
                verification_status=SEED_STATUS,
                created_at=started_at + timedelta(minutes=2 * offset),
            )
            for offset, (sender, body) in enumerate(messages)
        ]
    )
    room.last_seq = len(messages)

    session.add_all(
        [
            RoomMember(
                room_id=room.id,
                user_id=users[username].id,
                ai_check_enabled=True,
                # 기본은 **전부 읽음**이다. 심은 대화는 이미 지나간 것이므로
                # 시연이 배지 네 개로 시작하면 무엇이 새 소식인지 알 수 없다.
                last_read_seq=len(messages),
            )
            for username in spec["members"]
        ]
    )
    await session.flush()
    return room


async def _apply_unread(session: Any, users: dict[str, User], rooms: list[Room]) -> None:
    """`UNREAD` 표대로 읽음 위치를 되돌려 배지를 만든다."""
    for room_index, username, count in UNREAD:
        room = rooms[room_index]
        await session.execute(
            sa.update(RoomMember)
            .where(
                RoomMember.room_id == room.id,
                RoomMember.user_id == users[username].id,
            )
            .values(last_read_seq=max(0, room.last_seq - count))
        )
    await session.flush()


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="seed_demo",
        description="test1~test8 위에 데모용 친구·방·대화를 심는다.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="기존 친구·방·대화를 지우지 않고 덧붙인다 (기본은 지우고 다시 심는다)",
    )
    args = parser.parse_args(argv)

    async with SessionLocal() as session:
        users = await _resolve_users(session)
        print(f"계정 {len(users)}개를 찾았습니다: {', '.join(USERNAMES)}")

        if args.keep:
            print("기존 데이터를 유지합니다 (--keep)")
        else:
            print("기존 친구·방·대화를 지웁니다 (계정은 남깁니다)")
            await _wipe(session)

        count = await _seed_friendships(session, users)
        print(f"친구 {count}건 등록 (양방향, 별칭 포함)")

        # 방마다 하루씩 앞으로 당겨 심는다 — 방 목록의 시각이 전부 같으면
        # 어느 대화가 최근인지 화면에서 구분되지 않는다.
        base = datetime.now().replace(microsecond=0) - timedelta(days=len(ROOMS))
        rooms: list[Room] = []
        for index, spec in enumerate(ROOMS):
            room = await _seed_room(session, users, spec, base + timedelta(days=index, hours=index))
            rooms.append(room)
            label = spec["name"] or "(이름 없는 1:1 방)"
            print(f"방 '{label}' — 참여자 {len(spec['members'])}명, 메시지 {room.last_seq}개")

        await _apply_unread(session, users, rooms)
        for room_index, username, count in UNREAD:
            label = ROOMS[room_index]["name"] or "(이름 없는 1:1 방)"
            print(f"안 읽은 배지: {username} → '{label}' {count}개")

        # **커밋 전에 센다.** 커밋 후에는 `expire_on_commit`이 속성을 만료시켜
        # `room.last_seq` 접근이 닫힌 세션에 다시 질의하려 든다.
        thin = [
            spec["name"] or "(이름 없는 1:1 방)"
            for spec in ROOMS
            if len(spec["messages"]) < settings.AI_CONTEXT_N
        ]

        await session.commit()

    if thin:
        print(
            f"\n경고: 메시지가 AI_CONTEXT_N({settings.AI_CONTEXT_N})보다 적은 방이 있습니다 — "
            f"{', '.join(thin)}. 그 방에서는 판정이 건너뛰어집니다 (skipped_no_context).",
            file=sys.stderr,
        )

    print("\n완료. 시연 각본:")
    print("  개발 3팀   ← '엄마 나 토요일 6시에 갈게'        (가족방 문장)")
    print("  가족방     ← '스테이징 배포 금요일 3시로 잡겠습니다'  (업무 문장)")
    print("  개발 3팀   ← '야 오늘 회의 개길었지 ㅋㅋ'        (동기 1:1 문장)")
    await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
