# -*- coding: utf-8 -*-
"""시연용 전체 리셋 시드 — `test1`~`test10` 계정과 방 10개를 처음부터 만든다.

    docker compose exec -T app python - --reset < backend/scripts/seed_demo10.py

`backend/scripts/seed_demo.py`와 다른 점은 **계정까지 만든다는 것**이다. 그쪽은
사람이 화면에서 가입한 `test1`~`test8`을 찾아 쓰고 없으면 멈추지만, 이 스크립트는
`users`를 포함해 전부 지우고 다시 심는다. 시연 영상을 여러 번 다시 찍을 때 매번
같은 화면에서 시작하는 것이 목적이다.

**비밀번호는 `test`다.** 회원가입 규칙(BR-1.2)의 최소 8자에 미달하는 값이라
화면에서는 이 비밀번호로 가입할 수 없다. 여기서는 `hash_password()`를 직접 불러
DB에 넣으므로 통과하고, **로그인 경로에는 길이 검사가 없어**(`service.login()`,
`AuthView.tsx`의 검사는 `isSignup`일 때만 돈다) 시연에는 지장이 없다. 다만 시연
중에 새 계정을 가입시키는 장면이 있다면 그 계정만 8자 이상이어야 한다.

## 방 10개의 구성 원칙

이 앱이 잡는 것은 **문맥 부적합**이므로, 데이터의 값어치는 방의 개수가 아니라
**방과 방 사이의 거리**에 있다. 10개를 말투·관계 축으로 벌려놓고, 그중 세 쌍은
일부러 가깝게 두었다 (아래 표의 ← 표시). 가까운 쌍이 있어야 "단순 유사도가 아니라
문맥을 본다"를 보여줄 수 있다.

| # | 방 | 말투 | 관계 |
|---|---|---|---|
| 1 | 개발 3팀 | 존댓말·업무 | 사내 팀 |
| 2 | 백엔드 스터디 | 존댓말·업무 | 외부 스터디 ← 1과 가깝다 |
| 3 | 가족방 | 반말 | 가족 |
| 4 | 동아리 번개 | 반말 | 또래 |
| 5 | (1:1) 수민 | 반말 | 회사 동기 |
| 6 | (1:1) 서연 팀장님 | 존댓말 | 상사 ← 1과 가깝다 |
| 7 | 헬스 메이트 | 반말 | 취미 |
| 8 | OO물산 PoC | 격식체 | 고객사 |
| 9 | (1:1) 엄마 | 반말 | 가족 ← 3과 가깝다 |
| 10 | 동네 풋살 | 반말 | 동네 |

## 방마다 12개 이상인 이유

`AI_CONTEXT_N`(기본 10)보다 방 메시지가 적으면 판정이 통째로 건너뛰어진다
(FR-6.4, `skipped_no_context`). 시연에서 팝업이 안 뜨는 가장 흔한 원인이므로 모든
방을 그 값보다 넉넉히 채운다. 마지막에 실제 설정값과 대조해 경고를 낸다.

## 심는 메시지가 `disabled`인 이유

시드 메시지는 모델을 거치지 않았다. 6값 중 그 사실을 그대로 말하면서 화면에
"검증 안 됨" 배지를 띄우지 않는 유일한 값이 `disabled`이고, 무엇보다 **성능
집계(`ok` + `flagged_sent`)에서 제외된다** — 가짜 데이터가 지표를 오염시키면 안 된다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa

from app.auth.security import hash_password
from app.core.config import settings
from app.core.db import SessionLocal, dispose_engine
from app.models import Friendship, JudgmentLog, Message, Room, RoomMember, User

#: 모든 계정의 비밀번호. 모듈 docstring § 참조 — 가입 규칙의 8자 미만이지만
#: 로그인에는 길이 검사가 없다.
PASSWORD: Final[str] = "test"

#: `username -> display_name`. 순서가 곧 `test1`~`test10`의 순서다.
#:
#: `display_name`을 계정명과 다르게 두는 이유 — 친구로 등록하지 않은 방 참여자는
#: 이 값으로 표시된다(`resolve_display_names()`의 폴백). 전부 `test7` 같은
#: 계정명이면 시연 화면에서 누가 누구인지 읽히지 않는다.
USERS: Final[tuple[tuple[str, str], ...]] = (
    ("test1", "지환"),   # 주인공 — 시연은 이 계정으로 로그인한다
    ("test2", "서연"),   # 팀장
    ("test3", "준호"),   # 같은 팀 대리
    ("test4", "수민"),   # 입사 동기
    ("test5", "엄마"),
    ("test6", "도현"),   # 형
    ("test7", "민지"),   # 동아리 후배
    ("test8", "태현"),   # 동아리 친구
    ("test9", "하늘"),   # 스터디 멤버이자 고객사 담당
    ("test10", "지우"),  # 헬스·풋살
)

#: `(등록자, 대상) -> 별칭`. 여기 없는 쌍은 대상의 `display_name`을 쓴다.
#:
#: 같은 사람이 보는 사람마다 다른 이름으로 보이는 것이 FR-2.4·BR-2.8의 의도다.
#: 시드가 그것을 보여주지 못하면 표시명 해석이 그냥 계정명처럼 보인다 — 그래서
#: **관계가 드러나는 쌍만** 손으로 적는다.
ALIAS_OVERRIDES: Final[dict[tuple[str, str], str]] = {
    # 지환이 보는 사람들 — 시연에서 가장 많이 보이는 목록이다
    ("test1", "test2"): "서연 팀장님",
    ("test1", "test3"): "준호 대리님",
    ("test1", "test4"): "수민 동기",
    ("test1", "test5"): "엄마",
    ("test1", "test6"): "도현이 형",
    ("test1", "test7"): "민지 (동아리)",
    ("test1", "test8"): "태현 (동아리)",
    ("test1", "test9"): "하늘 매니저님",
    ("test1", "test10"): "지우 (헬스)",
    # 사람들이 보는 지환 — 관계에 따라 호칭이 다르다
    ("test2", "test1"): "지환 사원",
    ("test3", "test1"): "지환씨",
    ("test4", "test1"): "지환",
    ("test5", "test1"): "우리 아들",
    ("test6", "test1"): "지환이",
    ("test7", "test1"): "지환 선배",
    ("test8", "test1"): "지환",
    ("test9", "test1"): "지환 님",
    ("test10", "test1"): "지환",
    # 사내
    ("test2", "test3"): "박준호 대리",
    ("test2", "test4"): "이수민 사원",
    ("test2", "test9"): "하늘 매니저님",
    ("test3", "test2"): "서연 팀장님",
    ("test3", "test4"): "수민씨",
    ("test3", "test9"): "하늘님",
    ("test4", "test2"): "서연 팀장님",
    ("test4", "test3"): "준호 대리님",
    ("test9", "test2"): "서연 팀장님",
    ("test9", "test3"): "준호 대리님",
    # 가족
    ("test5", "test6"): "도현",
    ("test6", "test5"): "엄마",
    # 동아리·동네
    ("test7", "test8"): "태현",
    ("test8", "test7"): "민지",
    ("test6", "test8"): "태현",
    ("test8", "test6"): "도현이 형",
    ("test6", "test10"): "지우",
    ("test10", "test6"): "도현이 형",
    ("test8", "test10"): "지우",
    ("test10", "test8"): "태현",
}

#: 방 하나 — `(이름, 만든 사람, 참여자, 대화)`.
#:
#: `name`이 `None`이면 1:1 방이고, 화면이 참여자 표시명으로 제목을 조립한다.
#: 대화는 `(보낸 사람, 본문)`의 순서 있는 목록이며 `seq`는 이 순서대로 1부터
#: 매긴다 — 정렬 기준이 `created_at`이 아니라 `(room_id, seq)`이기 때문이다.
ROOMS: Final[tuple[dict[str, Any], ...]] = (
    {
        "name": "개발 3팀",
        "created_by": "test2",
        "members": ("test1", "test2", "test3", "test4"),
        "messages": (
            ("test2", "다들 좋은 아침입니다. 오늘 스탠드업은 10시에 하겠습니다"),
            ("test1", "네 팀장님, 준비하겠습니다"),
            ("test3", "확인했습니다"),
            ("test4", "넵 알겠습니다"),
            ("test2", "지환 사원, 결제 모듈 리팩터링은 어디까지 진행됐나요"),
            ("test1", "인터페이스 분리까지 끝냈고 지금 테스트 보강 중입니다. 오늘 중으로 PR 올리겠습니다"),
            ("test2", "좋습니다. 리뷰는 준호 대리가 맡아주세요"),
            ("test3", "알겠습니다. PR 올라오면 오늘 안에 확인하겠습니다"),
            ("test4", "저는 로그 수집 이슈를 보고 있는데 내일까지 걸릴 것 같습니다"),
            ("test2", "네, 무리하지 말고 진행 상황만 공유해주세요"),
            ("test1", "팀장님, 스테이징 배포는 언제로 잡을까요"),
            ("test2", "금요일 오후 3시로 봅시다. 그 전까지 QA를 마무리하죠"),
            ("test3", "그럼 목요일까지 리뷰 다 끝내겠습니다"),
            ("test4", "QA 시나리오는 제가 오늘 정리해서 공유드리겠습니다"),
            ("test2", "좋습니다. 회의록은 공유 문서에 올려두겠습니다"),
        ),
    },
    {
        # 1번과 같은 존댓말·기술 화제다. **의도된 hard negative** — 인명과 맥락만
        # 다르므로 단순 유사도로는 두 방을 가르지 못한다.
        "name": "백엔드 스터디",
        "created_by": "test9",
        "members": ("test1", "test3", "test9"),
        "messages": (
            ("test9", "이번 주 발제는 인덱스 설계 맞죠?"),
            ("test1", "네 제가 준비했습니다. 자료는 오늘 밤에 올리겠습니다"),
            ("test3", "지난주 트랜잭션 격리 수준 정리해주신 거 잘 봤습니다"),
            ("test9", "저도요. 팬텀 리드 예시가 특히 좋았습니다"),
            ("test1", "이번엔 복합 인덱스의 선행 컬럼 이야기를 해보려고 합니다"),
            ("test3", "카디널리티 순서 이야기가 나오겠네요"),
            ("test9", "실제 실행 계획도 같이 보면 좋을 것 같습니다"),
            ("test1", "네 EXPLAIN 결과를 몇 개 캡처해서 넣겠습니다"),
            ("test3", "저는 커버링 인덱스 사례를 하나 준비해오겠습니다"),
            ("test9", "그럼 시간은 지난주처럼 목요일 8시로 할까요"),
            ("test1", "좋습니다. 온라인으로 하시죠"),
            ("test3", "링크는 당일에 여기 올려주세요"),
            ("test9", "넵 제가 회의방 만들어서 공유하겠습니다"),
            ("test1", "감사합니다"),
        ),
    },
    {
        "name": "가족방",
        "created_by": "test5",
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
            ("test6", "나는 과일 사갈게"),
        ),
    },
    {
        "name": "동아리 번개",
        "created_by": "test7",
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
            ("test8", "늦으면 먼저 시켜놔"),
        ),
    },
    {
        "name": None,  # 1:1 — 화면이 참여자 표시명으로 제목을 조립한다
        "created_by": "test4",
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
    {
        # 1번과 같은 상대·같은 존댓말이지만 **1:1 보고**다. 단체 업무방에 맞는 말이
        # 여기서는 어색할 수 있고 그 반대도 마찬가지다.
        "name": None,
        "created_by": "test2",
        "members": ("test1", "test2"),
        "messages": (
            ("test2", "지환 사원, 잠깐 시간 괜찮아요?"),
            ("test1", "네 팀장님 말씀하세요"),
            ("test2", "이번 분기 목표를 정리하는데 본인 생각도 듣고 싶어서요"),
            ("test1", "저는 결제 모듈 안정화를 1순위로 두고 싶습니다"),
            ("test2", "좋습니다. 장애가 거기서 제일 많이 났죠"),
            ("test1", "네 로그를 보면 재시도 처리가 빠진 구간이 있습니다"),
            ("test2", "그 부분 정리해서 다음 주에 공유해줄 수 있나요"),
            ("test1", "네 수요일까지 문서로 올리겠습니다"),
            ("test2", "그리고 교육 예산이 남아서 필요한 강의가 있으면 신청하세요"),
            ("test1", "감사합니다. 성능 튜닝 쪽으로 찾아보겠습니다"),
            ("test2", "좋네요. 신청서는 총무팀에 내면 됩니다"),
            ("test1", "알겠습니다"),
            ("test2", "고생 많습니다. 오늘은 일찍 들어가세요"),
        ),
    },
    {
        "name": "헬스 메이트",
        "created_by": "test10",
        "members": ("test1", "test8", "test10"),
        "messages": (
            ("test10", "오늘 몇 시에 갈 거야"),
            ("test1", "나 8시쯤 갈 듯"),
            ("test8", "나도 그때 맞춰서 갈게"),
            ("test10", "오늘 등 하는 날이지"),
            ("test1", "ㅇㅇ 데드리프트부터 하자"),
            ("test8", "나 지난주에 무게 좀 올렸어"),
            ("test10", "오 얼마나"),
            ("test8", "100까지 쳤음"),
            ("test1", "오 대단하네"),
            ("test10", "나는 아직 80에서 못 넘어감"),
            ("test1", "자세부터 잡는 게 먼저야"),
            ("test8", "맞아 급하게 올리면 허리 나간다"),
            ("test10", "알겠어 오늘 좀 봐줘"),
            ("test1", "ㅇㅋ 8시에 보자"),
        ),
    },
    {
        # 가장 격식이 높은 방. 반말 문장을 여기 넣으면 판정이 확실히 걸린다.
        "name": "OO물산 PoC",
        "created_by": "test2",
        "members": ("test1", "test2", "test9"),
        "messages": (
            ("test9", "안녕하세요. OO물산 김하늘입니다. 방 초대 감사합니다"),
            ("test2", "안녕하세요 하늘 매니저님. 저희 쪽 담당은 저와 지환 사원입니다"),
            ("test1", "안녕하세요. 개발 담당 지환입니다. 잘 부탁드립니다"),
            ("test9", "네 반갑습니다. PoC 일정부터 확인 부탁드립니다"),
            ("test2", "다음 주 월요일에 착수해 3주간 진행하는 것으로 계획하고 있습니다"),
            ("test9", "좋습니다. 저희 쪽 테스트 데이터는 금요일까지 전달드리겠습니다"),
            ("test1", "감사합니다. 형식은 CSV로 주시면 됩니다"),
            ("test9", "확인했습니다. 개인정보가 포함되어 있어 마스킹 후 드리겠습니다"),
            ("test2", "네 그 편이 좋겠습니다"),
            ("test9", "중간 보고는 언제쯤 가능할까요"),
            ("test2", "2주 차 수요일에 한 번 드리겠습니다"),
            ("test1", "그때까지 기본 지표는 뽑아둘 수 있을 것 같습니다"),
            ("test9", "알겠습니다. 그럼 그렇게 진행하시죠"),
            ("test2", "네 감사합니다. 자료는 이 방에 공유드리겠습니다"),
        ),
    },
    {
        # 3번 가족방과 같은 사람·같은 반말이지만 1:1이다.
        "name": None,
        "created_by": "test5",
        "members": ("test1", "test5"),
        "messages": (
            ("test5", "지환아 잘 지내지"),
            ("test1", "응 엄마 잘 지내"),
            ("test5", "요즘 회사 많이 바쁘니"),
            ("test1", "좀 바쁜데 할 만해"),
            ("test5", "끼니 거르지 말고"),
            ("test1", "알겠어요"),
            ("test5", "이번에 김장했는데 좀 보내줄까"),
            ("test1", "좋지 조금만 보내줘"),
            ("test5", "택배로 내일 부칠게"),
            ("test1", "고마워요"),
            ("test5", "주소는 그대로지?"),
            ("test1", "응 그대로야"),
            ("test5", "그래 받으면 연락하고"),
            ("test1", "응 도착하면 전화할게"),
        ),
    },
    {
        "name": "동네 풋살",
        "created_by": "test10",
        "members": ("test1", "test6", "test8", "test10"),
        "messages": (
            ("test10", "이번 주 일요일 풋살 인원 체크할게"),
            ("test1", "나 참석"),
            ("test8", "나도"),
            ("test6", "나 이번 주는 좀 애매해"),
            ("test10", "지금 3명인데 최소 8명은 돼야 해"),
            ("test8", "내가 두 명 정도 데려올 수 있어"),
            ("test1", "나도 회사 사람 한 명 물어볼게"),
            ("test10", "오케이 그럼 6명은 되겠다"),
            ("test6", "나 오후 늦게면 갈 수 있을 것 같은데"),
            ("test10", "시간은 3시부터 5시야"),
            ("test6", "그럼 나도 가능"),
            ("test1", "구장비는 얼마야"),
            ("test10", "인당 8천원. 계좌는 나중에 올릴게"),
            ("test8", "ㅇㅋ"),
            ("test1", "공은 누가 가져와?"),
            ("test10", "내가 가져갈게"),
        ),
    },
)

#: 시연 시작 화면에 남길 안 읽은 배지 — `(방 index, 계정, 안 읽은 개수)`.
#:
#: 전부 읽음으로 두면 배지 기능이 화면에 아예 안 나타나고, 전부 안 읽음으로 두면
#: 어느 방이 새 소식인지 구분이 안 된다. 셋만 남긴다.
UNREAD: Final[tuple[tuple[int, str, int], ...]] = (
    (0, "test1", 3),   # 개발 3팀
    (3, "test1", 2),   # 동아리 번개
    (8, "test1", 1),   # (1:1) 엄마
)

#: 심는 메시지의 검증 상태. 모듈 docstring § 참조.
SEED_STATUS: Final[str] = "disabled"

# --------------------------------------------------------------------------
# 시각 배치 — 심은 대화가 **방금 나눈 것처럼** 보이게 한다
# --------------------------------------------------------------------------
# 시각은 컨테이너 시계를 따른다. `docker-compose.yml`이 app·db 양쪽에
# `TZ=Asia/Seoul`을 준다 — 기본값(UTC)으로 두면 심은 시각과 시연 중 보낸 메시지가
# 둘 다 화면에서 9시간 어긋난다 (그 이유는 compose의 db 서비스 주석에 있다).

#: 한 방 안에서 메시지 사이의 간격.
MESSAGE_GAP: Final[timedelta] = timedelta(minutes=1)

#: 방과 방 사이에서 **마지막 메시지 시각**이 벌어지는 간격.
#:
#: 0으로 두면 열 방의 시각이 같아져 방 목록에서 어느 대화가 최근인지 구분되지
#: 않는다. 반대로 너무 벌리면 앞쪽 방이 어제로 넘어가 목록에 `어제`가 뜬다.
ROOM_GAP: Final[timedelta] = timedelta(minutes=12)

#: 가장 최근 방의 마지막 메시지를 현재로부터 얼마나 앞에 둘 것인가.
#:
#: 정확히 `now`로 두지 않는 이유 — 심는 데 걸리는 몇 초 사이에 시계가 지나가
#: 미래 시각이 되는 것을 피한다. 화면에는 어차피 분 단위로만 보인다.
NEWEST_OFFSET: Final[timedelta] = timedelta(minutes=1)


async def _wipe(session: Any) -> None:
    """모든 데이터를 지운다 — **`users`까지 포함한다.**

    삭제 순서가 FK 역순이다. `judgment_logs`가 `messages`·`rooms`·`users`를,
    `messages`와 `room_members`가 `rooms`·`users`를, `friendships`가 `users`를
    참조한다. FK에 `ondelete`가 없어 RESTRICT이므로 순서를 틀리면 지워지지 않고
    오류가 난다.
    """
    for model in (JudgmentLog, Message, RoomMember, Room, Friendship, User):
        result = await session.execute(sa.delete(model))
        print(f"  {model.__tablename__:15s} {result.rowcount}행 삭제")
    await session.flush()


async def _seed_users(session: Any) -> dict[str, User]:
    """`test1`~`test10`을 만든다. 비밀번호는 전부 `PASSWORD`다.

    **계정마다 따로 해싱한다.** 해시 하나를 열 번 재사용하면 열 계정이 같은 솔트를
    쓰게 된다 — 데모 계정이라 실질 위험은 없지만, 같은 비밀번호가 DB에서 같은
    문자열로 보이는 것은 argon2를 쓴 이유(`security.py` § 비밀번호 해싱)와 어긋난다.
    열 번이면 1초 남짓이다.
    """
    users: dict[str, User] = {}
    for username, display_name in USERS:
        user = User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(PASSWORD),
        )
        session.add(user)
        users[username] = user
    await session.flush()
    return users


async def _seed_friendships(session: Any, users: dict[str, User]) -> int:
    """같은 방에 있는 사람끼리 **양방향으로** 친구를 맺는다.

    친구 관계는 단방향이지만(BR-2.3), 한쪽만 등록하면 반대쪽 계정으로 로그인했을 때
    상대가 `test4` 같은 계정명으로 보이고 방을 새로 만들 수도 없다. 열 대의 화면 중
    어느 것을 열어도 말이 되게 하려면 양쪽이 필요하다.

    별칭은 `ALIAS_OVERRIDES`에 있으면 그 값, 없으면 상대의 `display_name`이다 —
    `friendships.alias`가 NOT NULL이라 폴백이 반드시 있어야 한다 (FR-2.2).
    """
    display_of = dict(USERS)

    pairs: set[tuple[str, str]] = set()
    for spec in ROOMS:
        members = spec["members"]
        for owner in members:
            for friend in members:
                if owner != friend:
                    pairs.add((owner, friend))

    session.add_all(
        [
            Friendship(
                owner_id=users[owner].id,
                friend_id=users[friend].id,
                alias=ALIAS_OVERRIDES.get((owner, friend), display_of[friend]),
            )
            # 정렬해서 넣는다 — 집합의 순회 순서는 실행마다 달라질 수 있고,
            # 그러면 `friendships.id`가 리허설마다 뒤바뀌어 비교가 어려워진다.
            for owner, friend in sorted(pairs)
        ]
    )
    await session.flush()
    return len(pairs)


async def _seed_room(
    session: Any, users: dict[str, User], spec: dict[str, Any], started_at: datetime
) -> Room:
    """방 하나와 그 대화를 만든다.

    Args:
        started_at: 이 방 첫 메시지의 시각. 이후 메시지는 `MESSAGE_GAP`씩 벌어진다.

    **`rooms.last_seq`를 메시지 개수에 맞춘다.** 안 맞추면 시연 중 첫 전송이 seq 1을
    다시 받아 `UNIQUE (room_id, seq)`에 걸린다 — 화면에는 전송 실패로만 보이고
    원인은 드러나지 않는다.

    `created_at`을 명시하는 이유는 서버 기본값(`CURRENT_TIMESTAMP`)을 쓰면 심은
    메시지 수십 개가 전부 같은 초에 몰려 시각 표시가 무의미해지기 때문이다.

    **`rooms.created_at`도 첫 메시지 직전으로 당긴다.** 방 목록이 보여주는 시각이
    마지막 메시지가 아니라 이 값이다 (`RoomListView.tsx`의 `formatListTime(room.created_at)`) —
    여기가 과거면 대화만 최근이고 목록은 옛날 날짜를 보여준다.
    """
    room = Room(
        name=spec["name"],
        created_by=users[spec["created_by"]].id,
        created_at=started_at - MESSAGE_GAP,
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
                created_at=started_at + MESSAGE_GAP * offset,
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
                # 신규 방 기본값은 켜짐 (README). 시연에서 판정이 돌아야 한다.
                ai_check_enabled=True,
                # 기본은 **전부 읽음**이다. 심은 대화는 이미 지나간 것이므로
                # 방 열 개가 모두 배지를 달고 시작하면 무엇이 새 소식인지 모른다.
                # 배지는 아래 `_apply_unread()`가 세 개만 되돌려 만든다.
                last_read_seq=len(messages),
                joined_at=room.created_at,
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
        prog="seed_demo10",
        description="계정·친구·방·대화를 전부 지우고 test1~test10으로 다시 심는다.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="필수. 계정을 포함해 모든 데이터를 지우는 것을 확인한다",
    )
    args = parser.parse_args(argv)

    if not args.reset:
        print(
            "이 스크립트는 users를 포함한 모든 데이터를 지웁니다.\n"
            "실행하려면 --reset을 붙이세요.",
            file=sys.stderr,
        )
        return 2

    async with SessionLocal() as session:
        print("기존 데이터를 지웁니다 (계정 포함)")
        await _wipe(session)

        users = await _seed_users(session)
        print(f"\n계정 {len(users)}개 — 비밀번호 전부 {PASSWORD!r}")

        count = await _seed_friendships(session, users)
        print(f"친구 {count}건 (같은 방 참여자끼리 양방향, 별칭 포함)")

        # **끝에서부터 거꾸로 배치한다.** 마지막 방의 마지막 메시지를 현재 근처에
        # 두고 앞으로 거슬러 올라간다 — 시작점을 기준으로 배치하면 방마다 메시지
        # 개수가 달라 마지막 메시지가 제각각 다른 거리에서 끝나고, 결국 "방금 나눈
        # 대화"로 보이지 않는다.
        #
        # 전체 폭은 `ROOM_GAP × (방 수 - 1) + 가장 긴 방의 길이`이므로 현재 설정에서
        # 약 2시간이다. 자정 직후에 돌리면 앞쪽 방이 어제로 넘어가 목록에 `어제`가
        # 뜨는데, 그것은 실제로 어제인 것이라 그대로 둔다.
        now = datetime.now().replace(microsecond=0)
        rooms: list[Room] = []
        print()
        for index, spec in enumerate(ROOMS):
            last_at = now - NEWEST_OFFSET - ROOM_GAP * (len(ROOMS) - 1 - index)
            started_at = last_at - MESSAGE_GAP * (len(spec["messages"]) - 1)
            room = await _seed_room(session, users, spec, started_at)
            rooms.append(room)
            label = spec["name"] or f"(1:1) {'·'.join(spec['members'])}"
            print(
                f"  {index + 1:2d}. {label:22s} 참여 {len(spec['members'])}명"
                f" · 메시지 {room.last_seq}개"
                f" · 마지막 {last_at:%H:%M}"
            )

        await _apply_unread(session, users, rooms)
        print()
        for room_index, username, count in UNREAD:
            label = ROOMS[room_index]["name"] or "(이름 없는 1:1 방)"
            print(f"  안 읽은 배지: {username} → '{label}' {count}개")

        # **커밋 전에 센다.** 커밋 후에는 `expire_on_commit`이 속성을 만료시켜
        # `room.last_seq` 접근이 닫힌 세션에 다시 질의하려 든다.
        total_messages = sum(len(spec["messages"]) for spec in ROOMS)
        thin = [
            spec["name"] or "(이름 없는 1:1 방)"
            for spec in ROOMS
            if len(spec["messages"]) < settings.AI_CONTEXT_N
        ]

        await session.commit()

    print(f"\n방 {len(ROOMS)}개 · 메시지 {total_messages}개")

    if thin:
        print(
            f"\n경고: 메시지가 AI_CONTEXT_N({settings.AI_CONTEXT_N})보다 적은 방이 있습니다 — "
            f"{', '.join(thin)}. 그 방에서는 판정이 건너뛰어집니다 (skipped_no_context).",
            file=sys.stderr,
        )

    print(f"\n로그인: test1 ~ test10 / 비밀번호 {PASSWORD!r} (주인공은 test1)")
    print("\n시연 각본 — 한 방의 말을 다른 방에 넣어본다")
    print("  개발 3팀     ← '엄마 나 토요일 6시에 갈게'              (가족방 문장)")
    print("  OO물산 PoC   ← '오늘 등 하는 날이지 데드리프트부터 하자'  (헬스 문장)")
    print("  가족방       ← '스테이징 배포는 금요일 3시로 하겠습니다'  (업무 문장)")
    print("  백엔드 스터디 ← '결제 모듈 리팩터링 PR 오늘 올리겠습니다'  (같은 말투·다른 맥락)")
    await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
