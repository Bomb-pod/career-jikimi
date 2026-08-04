# -*- coding: utf-8 -*-
"""데모용 채팅 데이터 시드 — 사용자·친구·방·메시지를 채운다.

    docker compose exec app python -m app.seed_demo --reset
    # 또는 로컬 venv에서 (.env의 DATABASE_URL을 본다)
    .venv/Scripts/python.exe -m app.seed_demo --reset

## 왜 방마다 12개 이상인가

`AI_CONTEXT_N=10`이라 **방 메시지가 10개 미만이면 판정을 건너뛴다**
(`skipped_no_context`, FR-6.4). 데모에서 팝업이 안 뜨는 가장 흔한 원인이므로
모든 방을 12턴 이상으로 채운다.

## verification_status를 `disabled`로 두는 이유

시드 메시지는 판정을 거치지 않았다. 6값 중 그 사실에 가장 가까운 것이
`disabled`이고, 무엇보다 **성능 집계(`ok` + `flagged_sent`)에서 제외된다** —
가짜 데이터가 지표를 오염시키면 안 된다. `failed`/`degraded`가 아니므로
"검증 안 됨" 배지도 붙지 않는다.

## 방 구성

| 방 | 성격 | 데모에서의 쓸모 |
|---|---|---|
| 서버TF | 업무·단체 | 여기에 잡담을 보내면 **부적절** |
| 점심팟 | 잡담·단체 | 같은 잡담이 여기서는 **적절** |
| 앱TF | 업무·단체 | 서버TF와 같은 도메인 — hard negative |
| 엄마 | 가족·1:1 | |

**서버TF와 앱TF가 둘 다 업무방인 것이 의도다.** 말투도 화제도 비슷하고
인명·일정만 다르다 — 단순 유사도로는 못 가리는 경우를 보여준다.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta

import sqlalchemy as sa

from app.auth.security import hash_password
from app.core.db import SessionLocal, dispose_engine
from app.models import Friendship, JudgmentLog, Message, Room, RoomMember, User

PASSWORD = "demo1234"

#: (username, display_name)
USERS = [
    ("jihwan", "지환"),
    ("minsu", "민수"),
    ("soyeon", "소연"),
    ("taeho", "태호"),
    ("mom", "엄마"),
]

#: 지환이 등록한 별칭 (친구 등록 시 별칭 필수, FR-3)
ALIASES = {"minsu": "민수 팀장님", "soyeon": "소연님", "taeho": "태호", "mom": "엄마"}

#: (방 이름, 참여자 username, [(발신자, 본문)])
ROOMS: list[tuple[str, list[str], list[tuple[str, str]]]] = [
    (
        "서버TF",
        ["jihwan", "minsu", "soyeon"],
        [
            ("minsu", "내일 배포 리허설 몇 시로 할까요?"),
            ("jihwan", "오전 10시면 될 것 같습니다"),
            ("soyeon", "저는 10시 좋습니다. 스테이징 먼저 올릴게요"),
            ("minsu", "그럼 10시로 잡죠. 롤백 절차도 한 번 봐주세요"),
            ("jihwan", "롤백은 alembic downgrade 한 단계로 정리해뒀습니다"),
            ("soyeon", "스테이징 DB 스냅샷도 떠둘까요?"),
            ("minsu", "네 부탁드려요. 용량은 얼마나 되나요"),
            ("soyeon", "덤프가 약 400MB 정도입니다"),
            ("jihwan", "그 정도면 복원도 2분 안 걸립니다"),
            ("minsu", "좋네요. 체크리스트는 누가 정리하죠?"),
            ("jihwan", "제가 오늘 안에 문서로 올리겠습니다"),
            ("soyeon", "헬스체크 엔드포인트도 목록에 넣어주세요"),
            ("jihwan", "네, /health 응답까지 확인 항목으로 넣을게요"),
            ("minsu", "그럼 내일 10시에 봅시다"),
        ],
    ),
    (
        "점심팟",
        ["jihwan", "taeho", "soyeon"],
        [
            ("taeho", "오늘 점심 뭐 먹지"),
            ("soyeon", "어제 국밥 먹어서 오늘은 다른 거"),
            ("jihwan", "1층에 새로 생긴 파스타집 어때?"),
            ("taeho", "거기 웨이팅 길다던데"),
            ("soyeon", "11시 40분에 나가면 괜찮을걸"),
            ("jihwan", "그럼 40분에 로비에서 볼까"),
            ("taeho", "콜"),
            ("soyeon", "나 회의가 11시 반에 끝나서 조금 늦을 수도"),
            ("jihwan", "먼저 가서 자리 잡고 있을게"),
            ("taeho", "메뉴는 가서 정하자"),
            ("soyeon", "거기 크림파스타가 유명하대"),
            ("jihwan", "좋다 그거 먹자"),
        ],
    ),
    (
        "앱TF",
        ["jihwan", "minsu", "taeho"],
        [
            ("taeho", "푸시 알림 문구 초안 공유드립니다"),
            ("jihwan", "확인했습니다. 길이 제한이 있나요?"),
            ("taeho", "iOS는 178자에서 잘립니다"),
            ("minsu", "그럼 핵심을 앞에 두는 게 낫겠네요"),
            ("jihwan", "제목에 방 이름을 넣는 건 어떨까요"),
            ("taeho", "좋습니다. 다만 단체방은 이름이 길어서요"),
            ("minsu", "20자 넘으면 말줄임 처리하죠"),
            ("jihwan", "그건 클라이언트에서 자르는 게 편합니다"),
            ("taeho", "서버는 원문 그대로 내려주는 걸로"),
            ("minsu", "정리해서 목요일 회의 때 확정합시다"),
            ("jihwan", "네, 그때까지 문구 후보 세 개 준비하겠습니다"),
            ("taeho", "저는 아이콘 시안 가져오겠습니다"),
        ],
    ),
    (
        "엄마",
        ["jihwan", "mom"],
        [
            ("mom", "밥은 먹었니"),
            ("jihwan", "네 방금 먹었어요"),
            ("mom", "이번 주말에 집에 오니?"),
            ("jihwan", "토요일 저녁에 갈게요"),
            ("mom", "몇 시쯤 도착할 것 같아"),
            ("jihwan", "7시쯤이요. 차 막히면 조금 늦을 수도"),
            ("mom", "그럼 저녁 그때 맞춰 준비할게"),
            ("jihwan", "먹고 싶은 거 있으면 미리 말해요"),
            ("mom", "김치찌개 끓여놓을까"),
            ("jihwan", "좋아요 그거 먹고 싶었어요"),
            ("mom", "올 때 우산 챙기고"),
            ("jihwan", "네 알겠습니다"),
        ],
    ),
]


async def seed(reset: bool) -> None:
    async with SessionLocal() as s:
        if reset:
            # FK 순서를 지킨다 — 자식부터 지운다.
            for model in (JudgmentLog, Message, RoomMember, Room, Friendship, User):
                await s.execute(sa.delete(model))
            await s.flush()
            print("기존 데이터를 지웠습니다")

        pw = hash_password(PASSWORD)
        users: dict[str, User] = {}
        for name, display in USERS:
            u = User(username=name, display_name=display, password_hash=pw)
            s.add(u)
            users[name] = u
        await s.flush()
        print(f"사용자 {len(users)}명 (비밀번호 전부 {PASSWORD!r})")

        # 친구는 단방향 즉시 등록이다 (FR-3). 데모에서 누구로 로그인해도
        # 친구 목록이 보이도록 양쪽 다 넣는다.
        n = 0
        for a, _ in USERS:
            for b, _ in USERS:
                if a == b:
                    continue
                alias = ALIASES.get(b) if a == "jihwan" else dict(USERS)[b]
                s.add(Friendship(owner_id=users[a].id, friend_id=users[b].id,
                                 alias=alias or dict(USERS)[b]))
                n += 1
        await s.flush()
        print(f"친구 관계 {n}건")

        base = datetime.now().replace(microsecond=0) - timedelta(hours=6)
        total = 0
        for r_i, (room_name, members, lines) in enumerate(ROOMS):
            room = Room(name=room_name, created_by=users[members[0]].id,
                        last_seq=len(lines), created_at=base + timedelta(minutes=r_i))
            s.add(room)
            await s.flush()

            for m in members:
                s.add(RoomMember(
                    room_id=room.id, user_id=users[m].id,
                    ai_check_enabled=True,          # 신규 방 기본값은 켜짐 (README)
                    # 지환은 마지막 2개를 안 읽은 상태로 둔다 — 안 읽은 배지 확인용.
                    last_read_seq=len(lines) - 2 if m == "jihwan" else len(lines),
                    joined_at=room.created_at,
                ))

            for i, (sender, body) in enumerate(lines, start=1):
                s.add(Message(
                    room_id=room.id, sender_id=users[sender].id, seq=i, body=body,
                    # 시드 메시지는 판정을 거치지 않았다. 성능 집계에서 제외되는
                    # 값이라 지표를 오염시키지 않는다.
                    verification_status="disabled",
                    created_at=room.created_at + timedelta(minutes=i * 3),
                ))
                total += 1
            print(f"  {room_name:8s} 참여 {len(members)}명 · 메시지 {len(lines)}개"
                  f" {'(판정 가능)' if len(lines) >= 10 else '(문맥 부족 — 판정 건너뜀)'}")

        await s.commit()
        print(f"\n메시지 {total}개 · 방 {len(ROOMS)}개")
        print(f"\n로그인: jihwan / {PASSWORD}")
        print("\n데모 시나리오")
        print("  1. [점심팟]에 '오늘 저녁에 치킨 어때?' → 통과해야 정상")
        print("  2. [서버TF]에 같은 문장 → 팝업이 떠야 정상")
        print("  3. [앱TF]에 '롤백은 alembic downgrade로 정리했습니다' → 같은 업무 말투인데")
        print("     인명·일정이 다른 방이다. 단순 유사도로는 못 가리는 경우다.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true",
                    help="기존 사용자·방·메시지·판정로그를 모두 지우고 새로 만든다")
    args = ap.parse_args()
    if not args.reset:
        print("[주의] --reset 없이 실행하면 기존 데이터 위에 추가한다.")
        print("       username이 겹치면 UNIQUE 제약으로 실패한다.")
    asyncio.run(_run(args.reset))
    return 0


async def _run(reset: bool) -> None:
    # **dispose를 같은 루프 안에서 한다.** asyncio.run을 두 번 부르면 두 번째가
    # 새 루프를 열고, 첫 루프에 매여 있던 풀 커넥션을 거기서 닫으려다
    # `RuntimeError: Event loop is closed`로 터진다 — 커밋은 이미 끝난 뒤라
    # 데이터는 멀쩡하지만, 성공한 실행이 트레이스백으로 끝나 실패처럼 보인다.
    try:
        await seed(reset)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
