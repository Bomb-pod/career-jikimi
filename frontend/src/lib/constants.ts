/**
 * 프론트엔드 상수.
 *
 * `PASSWORD_MIN_LENGTH`는 백엔드 `app/auth/constants.py`의 같은 이름과 **같은 값**
 * 이어야 한다. 두 곳에 값을 두는 것을 받아들인 이유 — 제출 전에 클라이언트에서도
 * 검사하면 확실히 실패할 요청의 왕복을 아낀다.
 *
 * **문구는 복제하지 않는다.** 서버가 8자 미만에 붙여 보내는 `message`를 그대로
 * 화면에 띄우고, 클라이언트는 자기 문구를 만들지 않는다. 문구를 두 곳에 두면 한쪽만
 * 바뀌어 "8자 이상"이라고 말하면서 12자를 요구하는 화면이 나온다
 * (`code-generation-plan.md` § 이 계획이 닫는 열린 항목).
 *
 * 클라이언트 검사가 막은 경우에만 아래 `PASSWORD_TOO_SHORT_MESSAGE`를 쓴다 — 그때는
 * 서버에 묻지 않았으므로 서버 문구가 없다.
 */

/** BR-1.2. 백엔드 `PASSWORD_MIN_LENGTH`와 같은 값. */
export const PASSWORD_MIN_LENGTH = 8

/**
 * 클라이언트 검사가 제출을 막았을 때의 문구. 서버에 묻지 않았으므로 서버 문구가 없다.
 *
 * 서버의 `WEAK_PASSWORD` 응답이 왔을 때는 이것을 쓰지 않고 그 응답의 `message`를 쓴다.
 */
export const PASSWORD_TOO_SHORT_MESSAGE = `비밀번호는 ${PASSWORD_MIN_LENGTH}자 이상이어야 합니다`

/** `users.username`·`friendships.alias`의 VARCHAR(50). 입력칸의 `maxLength`로 쓴다. */
export const USERNAME_MAX_LENGTH = 50
export const ALIAS_MAX_LENGTH = 50

/** `rooms.name`의 VARCHAR(100). 백엔드 `ROOM_NAME_MAX_LENGTH`와 같은 값이어야 한다. */
export const ROOM_NAME_MAX_LENGTH = 100

/**
 * HTTP 요청 타임아웃(ms).
 *
 * 회원가입·로그인은 argon2 해싱 때문에 의도적으로 느리다(수십~수백 ms). 10초는 그것에
 * 넉넉하고, 응답이 오지 않는 요청을 영원히 기다리지 않는 값이다 — 기다리면 제출 버튼이
 * 계속 비활성 상태로 남아 사용자가 아무것도 할 수 없다.
 */
export const REQUEST_TIMEOUT_MS = 10_000

/** `localStorage`에 토큰을 담는 키. */
export const TOKEN_STORAGE_KEY = 'career-jikimi.token'

/**
 * WebSocket 재연결 백오프 — 1 → 2 → 4 → 8 → 16초, **상한 16초로 시도 무제한**
 * (`code-generation-plan.md` § 열린 항목에서 확정).
 *
 * 시도를 유한하게 막지 않는 이유 — 시도가 끝나면 앱이 조용히 죽은 채로 남고,
 * 사용자는 새 메시지가 오지 않는 이유를 알 수 없다. 상한을 두면 재연결 트래픽은
 * 억제되고 복구는 자동으로 일어난다.
 *
 * **`session_replaced`에는 이 백오프가 적용되지 않는다** — 그때는 아예 재연결하지
 * 않는다 (BR-5.5).
 */
export const WS_BACKOFF_START_MS = 1_000
export const WS_BACKOFF_MAX_MS = 16_000

/**
 * 토스트 표시 시간(ms)과 동시 표시 상한 (`code-generation-plan.md` § 열린 항목).
 *
 * 4초는 읽고 클릭할 시간이고, 3개를 넘으면 화면을 가려 오히려 방해가 된다. 넘치면
 * 가장 오래된 것부터 제거한다.
 */
export const TOAST_TIMEOUT_MS = 4_000
export const TOAST_MAX_VISIBLE = 3

/**
 * `rooms.name`이 비었을 때 방 이름에 나열하는 참여자 수 (§ 열린 항목).
 *
 * 3명이면 한 줄에 들어가고 방을 구별하기에 충분하다. **본인은 제외한다** — 넣으면
 * 모든 방 이름이 내 이름으로 시작해 구별에 기여하지 않는다.
 */
export const ROOM_NAME_MEMBER_LIMIT = 3

/**
 * 메시지 본문 길이 상한. 백엔드 `app/messages/constants.py`의 `MESSAGE_MAX_LENGTH`와
 * **같은 값**이어야 한다.
 *
 * 입력칸의 `maxLength`로 쓴다 — 서버가 400 `MESSAGE_TOO_LONG`으로 막지만, 2000자를
 * 다 쓴 뒤에 거절당하는 것보다 애초에 넘겨 입력할 수 없는 편이 낫다. 두 곳에 값을
 * 두는 것을 받아들인 이유는 `PASSWORD_MIN_LENGTH`와 같다.
 */
export const MESSAGE_MAX_LENGTH = 2000

/**
 * degraded 상태에서 몇 번째 전송마다 프로브를 보내는가 (BR-8.5, FR-8.5).
 *
 * `degradedSendCount % PROBE_EVERY === PROBE_EVERY - 1`이 프로브 차례다. 0-index
 * 기준 다섯 번째다 — 0,1,2,3을 보낸 뒤 인덱스 4에서 프로브가 나간다.
 *
 * degraded 진입 직후를 프로브로 삼지 않는 이유(`% 5 === 0`이 아닌 이유) — 방금 실패한
 * API를 곧바로 다시 부르는 것은 의미가 적다.
 */
export const PROBE_EVERY = 5

/** 프로브가 성공해 정상 검증으로 돌아왔을 때의 안내 문구 (FR-8.5). */
export const DEGRADED_RECOVERED_MESSAGE = 'AI 검증이 다시 켜졌습니다'

/**
 * 판정에 들어가는 문맥 메시지 수 `N` — 백엔드 `AI_CONTEXT_N`의 **기본값**이다 (FR-6.2).
 *
 * **화면 안내에만 쓴다.** 콜드스타트 안내(FR-6.4)와 프라이버시 고지(NFR-5)가 "최근
 * 몇 개"를 말해야 하는데, 서버가 이 값을 응답에 실어 보내지 않는다. 판정 여부를
 * 클라이언트가 이 값으로 **결정하지 않는다** — 그 판단은 전적으로 서버의 것이며,
 * 여기 값이 서버 설정과 달라도 안내 문구의 숫자만 어긋난다.
 */
export const AI_CONTEXT_N = 10
