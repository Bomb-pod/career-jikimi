# Unit Dependency DAG — career-jikimi

`unit-of-work.md`가 정의한 다섯 단위 사이의 의존 위상이다. `../application-design/component-dependency.md`의 컴포넌트 의존 행렬을 단위 수준으로 접은 것이며, `../application-design/components.md`의 소유권 경계와 `../application-design/component-methods.md`의 호출 관계가 그 근거다. 통합 방식은 `../application-design/services.md`와 `../application-design/decisions.md`(ADR-002)가 정한 단일 프로세스 구조를 따른다. 기능 대응은 `../requirements-analysis/requirements.md`의 FR 번호로 표기한다.

**이 문서는 위상만 기술한다.** 무엇을 먼저 만들지는 정하지 않는다 — 그 선택은 여러 유효한 위상 정렬 중 하나를 고르는 경제적 판단이며, 이 워크플로에서는 `delivery-planning`(2.8)이 스코프에서 제외되어 엔진의 배치 계산이 그 자리를 대신한다.

## 그래프

```
              U1 foundation
               /          \
              /            \
   U2 judgment-core    U3 auth-friends
              \              |
               \        U4 rooms-realtime
                \            /
                 \          /
                  U5 messaging
```

<!-- Text fallback: U1 foundation이 뿌리다. 그 위에 U2 judgment-core와 U3 auth-friends가 서로 독립적으로 선다. U3 위에 U4 rooms-realtime이 선다. U5 messaging은 U2와 U4 양쪽에 의존한다. 순환은 없다. -->

## 간선과 근거

| 간선 | 근거 |
|---|---|
| U2 → U1 | `judgment`가 `core/config`(API 키·임계값·문맥 개수)와 `core/db`(`judgment_logs`)를 쓴다 |
| U3 → U1 | `auth`·`friends`가 `core/db`와 설정을 쓴다 |
| U4 → U3 | `rooms`가 `auth.current_user()`로 호출자를 확인하고, `friends.resolve_display_names()`로 참여자 표시명을 해석한다 (FR-2.4) |
| U5 → U4 | `messages`가 `rooms.get_membership()`으로 참여자 자격과 AI 토글을 확인하고, `member_user_ids()`로 브로드캐스트 대상을 얻으며, `ws_registry.push_to_users()`로 밀어낸다 |
| U5 → U2 | `messages`가 `judgment.judge()`를 호출하고 `JudgeResult`의 세 갈래로 분기한다 (FR-6.4~FR-6.6) |

**U5는 U3에도 간접 의존한다** — 히스토리 응답에 발신자 표시명을 실으려면 `friends.resolve_display_names()`가 필요하다. U4를 통해 U3에 도달하므로 DAG에 직접 간선을 그리지 않았다. 위상 순서는 같다.

**U2와 U3 사이에 간선이 없다.** `judgment`는 사용자도 친구도 방도 알지 못한다 — 판정 입력에 참여자 정보를 넣지 않기 때문이다(FR-6.2). 이 격리가 U2를 단독 검증 가능하게 만든다.

## 기계 판독 간선 블록

```yaml
units:
  - name: foundation
    kind: packaging
    depends_on: []
  - name: judgment-core
    kind: service
    depends_on: [foundation]
  - name: auth-friends
    kind: service
    depends_on: [foundation]
  - name: rooms-realtime
    kind: service
    depends_on: [auth-friends]
  - name: messaging
    kind: service
    depends_on: [rooms-realtime, judgment-core]
```

## 통합 지점

단위 경계는 **작업 경계이지 배포 경계가 아니다** (ADR-002 — 단일 서비스). 따라서 통합은 전부 같은 프로세스 안의 함수 호출이며, 네트워크 실패 모드가 없다.

| 소비 단위 | 제공 단위 | 계약 |
|---|---|---|
| U2, U3, U4, U5 | U1 | `settings` 싱글턴, `get_session()` 의존성, `Base` |
| U4 | U3 | `auth.current_user()`, `auth.verify_token()`(WS 첫 프레임 인증용), `friends.resolve_display_names()` |
| U5 | U4 | `rooms.get_membership()`, `rooms.member_user_ids()`, `ws_registry.push_to_users()` |
| U5 | U2 | `judgment.judge()` → `JudgeResult`, `judgment.get_log_for_force()`, `judgment.set_user_action()`, `judgment.link_message()` |

**가장 중요한 계약은 `JudgeResult`다.** U5는 이 세 갈래(`appropriate` / `inappropriate` / `failed`)만 알고 프롬프트·모델·스키마·임계값을 모른다. 이 좁은 표면 덕분에 U2의 내부를 바꿔도 U5가 흔들리지 않는다.

**공유 데이터 하나** — `rooms.last_seq`를 U4가 소유하고 U5가 증가시킨다. 소유권 경계를 넘는 예외이며 근거는 ADR-003(채번이 메시지 저장과 같은 트랜잭션 안에 있어야 한다)이다.

## 병렬 가능성

이 DAG는 여러 위상 정렬을 허용한다.

| 형제 집합 | 조건 |
|---|---|
| {U2, U3} | U1 완료 후. 서로 의존하지 않는다 |

**U2와 U3가 형제인 것이 이 DAG의 실질적 값어치다.** 1인 작업이라 실제로 동시에 짜지는 않지만, 선택지가 생긴다 — 판정 품질이 기대에 못 미쳐 프롬프트를 손봐야 할 때, 그동안 껍데기(인증·친구)를 만들 수 있다. 반대로 껍데기에서 막혀도 판정 실험은 계속 돌아간다.

U4와 U5는 선형이다. 방이 없으면 메시지를 보낼 곳이 없고, 실시간 연결이 없으면 브로드캐스트를 검증할 수 없다.

## 순환 없음 확인

위상 정렬이 존재하므로 순환이 없다. 유효한 순서의 예:

```
U1 → U2 → U3 → U4 → U5
U1 → U3 → U2 → U4 → U5
U1 → U3 → U4 → U2 → U5
```

셋 다 유효하다. **어느 것을 고를지는 이 문서가 정하지 않는다.**

## Assumptions & Open Questions

- U5 → U3의 간접 의존(히스토리 표시명)을 직접 간선으로 그리지 않았다. 위상 순서에 영향이 없으나, 나중에 U4를 건너뛰는 재구성이 생기면 이 간선이 드러나야 한다.
- `delivery-planning`이 없으므로 walking-skeleton 의례가 어떻게 해소될지는 Construction 진입 시 엔진이 결정한다. 첫 배치가 `foundation` 단독이 될 것으로 보이며, 그 경우 "종단 간 얇은 슬라이스"라는 walking skeleton의 원래 의미와는 다르다.
- 단위마다 프론트엔드 몫이 백엔드와 묶여 있어, 프론트만 먼저 훑고 싶을 때의 순서는 이 DAG가 표현하지 못한다.
