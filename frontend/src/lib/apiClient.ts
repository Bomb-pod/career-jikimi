/**
 * HTTP 호출 래퍼 — JWT 부착, 오류 정규화, 타임아웃.
 *
 * **예외는 네트워크 오류와 5xx에만 쓴다** (`components.md` § apiClient). 4xx는 던지지
 * 않고 `{ok: false, error}`로 돌려준다. 이 단위에서 4xx는 전부 사용자가 화면에서
 * 고칠 수 있는 것(짧은 비밀번호, 중복 아이디, 빈 별칭)이므로 정상 흐름의 갈래다.
 * 특히 **409를 던지지 않는다** — U5의 부적절 판정(409)이 같은 규약을 쓰며, 규약이
 * 엔드포인트마다 갈라지면 호출부가 매번 다르게 생긴다.
 *
 * 경로에 `/api` 접두사를 붙이지 않는다 — `component-methods.md`가 `POST /auth/signup`
 * 처럼 접두사 없이 확정했다. 개발 중에는 Vite dev 서버의 프록시가, 배포에서는 같은
 * 오리진의 FastAPI가 받는다.
 */

import { REQUEST_TIMEOUT_MS } from './constants'

// --------------------------------------------------------------------------
// 타입
// --------------------------------------------------------------------------

/** 서버가 `{"error": {...}}`로 보내는 오류를 정규화한 모양. */
export interface ApiError {
  /** 분기 키. 서버의 `code` 그대로 (`WEAK_PASSWORD`, `USERNAME_TAKEN`, ...). */
  code: string
  /** 사람이 읽는 문구. **화면에는 이 값을 그대로 쓴다.** */
  message: string
  /** HTTP 상태. 코드로 분기할 수 없는 예외 상황의 판단용. */
  status: number
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError }

/**
 * 로그인한 나 자신.
 *
 * `display_name`을 **일부러 넣지 않았다.** 서버는 보내주지만 프론트엔드가 그 값을
 * 쓸 곳이 없다(FR-2.4). 타입에 없으면 렌더링 코드가 컴파일되지 않으므로, 실수로
 * 화면에 새는 경로가 타입 검사에서 막힌다.
 */
export interface CurrentUser {
  id: number
  username: string
}

/**
 * 검색으로 찾은 상대.
 *
 * `CurrentUser`와 같은 이유로 `display_name`이 없다. 검색 결과에 보여주는 것은
 * 사용자가 방금 입력한 **아이디**이며, 그것이 "이 사람이 맞나"를 확인하는 값이다.
 */
export interface SearchedUser {
  id: number
  username: string
}

/** 친구 목록의 한 항목. **상대의 이름이 아니라 내가 붙인 별칭뿐이다** (FR-2.4). */
export interface Friend {
  /** `friendships.id` — 별칭 수정의 대상. */
  id: number
  /** `users.id` — U4가 방을 만들 때 참여자로 지정한다. */
  friend_user_id: number
  alias: string
}

export interface AuthPayload {
  token: string
  user: CurrentUser
}

/**
 * 방 참여자 한 명. **표시명뿐이다** — 서버가 `resolve_display_names()`로 해석해 보낸다.
 *
 * `ai_check_enabled`가 없는 것이 의도다 (FR-6.1). 개인 설정이라 서버가 남의 값을
 * 보내지 않으며, 타입에도 없어 화면이 그릴 방법이 없다.
 */
export interface RoomMember {
  user_id: number
  display_name: string
}

/** 방 목록의 한 항목. `unread_count`는 서버가 계산한 배지 값이다 (BR-5.1). */
export interface RoomSummary {
  id: number
  /** `null`이면 화면이 참여자 표시명으로 조립한다. */
  name: string | null
  last_seq: number
  created_at: string
  unread_count: number
  last_read_seq: number
  /** **내** 검증 토글 (FR-6.1). 다른 참여자의 값은 서버가 보내지 않는다. */
  ai_check_enabled: boolean
  members: RoomMember[]
}

/** 방 상세. `ai_check_enabled`·`last_read_seq`는 **호출자 본인의 값**이다 (FR-6.1). */
export interface RoomDetail {
  id: number
  name: string | null
  last_seq: number
  created_at: string
  members: RoomMember[]
  ai_check_enabled: boolean
  last_read_seq: number
}

/**
 * 메시지 하나. **U5 messaging이 소유하는 타입이며 여기에는 최소한만 있다.**
 *
 * 이 단위가 다루는 것은 WebSocket으로 도착한 메시지를 목록에 넣고 중복을 제거하는
 * 일뿐이다(FR-3.3, FR-5.2). 판정 상태·신고 여부처럼 U5가 쓰는 필드는 그 단위가
 * 더한다 — 지금 추측해서 넣으면 서버와 어긋난 필드가 화면에 남는다.
 *
 * `id`가 **중복 제거의 키다** (FR-4.3). 내가 보낸 메시지는 HTTP 응답과 WebSocket
 * 푸시 양쪽으로 오고, 히스토리와 구독 스트림에도 같은 메시지가 겹쳐 들어온다.
 */
export interface ChatMessage {
  id: number
  room_id: number
  sender_id: number
  /** 정렬 기준. `created_at`이 아니다 (FR-4.2, NFR-4). */
  seq: number
  body: string
  created_at: string
  /**
   * 6값 중 하나 (FR-7.1). **U5가 더한 필드다.**
   *
   * `failed`·`degraded`·`skipped_no_context`에만 "검증 안 됨" 배지가 붙는다
   * (BR-8.6). 메시지에 붙은 속성이라 **스크롤해서 다시 봐도 남는다** (FR-8.6) —
   * 히스토리 응답과 WebSocket 프레임 양쪽에 실려 있어야 그 성질이 유지된다.
   */
  verification_status: VerificationStatus
  /** 오발송 신고 시각. `null`이면 신고되지 않았다 (FR-11.3). */
  misdirect_reported_at: string | null
  /**
   * 히스토리 응답에만 있다 — **보는 사람마다 다른 값**이라(내가 붙인 별칭, FR-2.4)
   * 전원에게 같은 프레임을 보내는 브로드캐스트에는 담을 수 없다. 화면은 방
   * 참여자 목록에서 해석하고 이 값을 보조로 쓴다.
   */
  sender_display_name?: string
}

/** `messages.verification_status`의 6값 (FR-7.1). 백엔드 ENUM과 같은 목록이다. */
export type VerificationStatus =
  | 'ok'
  | 'flagged_sent'
  | 'failed'
  | 'degraded'
  | 'skipped_no_context'
  | 'disabled'

/**
 * `POST /rooms/{id}/messages`의 결과 — **판별 가능한 세 갈래** (`component-methods.md`).
 *
 * `409`를 예외로 던지지 않는다. 정상 분기다 (BR-6.3) — `reason`이 판별자이며,
 * `inappropriate`는 부적절 판정 팝업을, `judge_failed`는 검증 실패 팝업을 띄운다.
 * **두 경우 모두** 사용자가 강행하면 같은 `logId`를 `forceLogId`로 실어 재요청한다.
 */
export type SendOutcome =
  | { kind: 'sent'; message: ChatMessage }
  | { kind: 'blocked'; reason: 'inappropriate'; logId: number; score: number }
  | { kind: 'blocked'; reason: 'judge_failed'; logId: number }
  | { kind: 'error'; error: ApiError }

/**
 * 네트워크 실패·타임아웃·5xx. **이것만 throw한다.**
 *
 * 별도 클래스인 이유 — 호출부가 "사용자가 고칠 수 있는 실패"(ApiError)와 "지금
 * 서버에 닿지 못한다"를 다르게 다뤄야 한다. 전자는 폼에 문구를 띄우고, 후자는
 * 재시도를 권한다.
 */
export class ApiTransportError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiTransportError'
    this.status = status
  }
}

// --------------------------------------------------------------------------
// 토큰
// --------------------------------------------------------------------------
let authToken: string | null = null

/**
 * 이후 모든 요청에 붙일 토큰을 설정한다. `null`이면 헤더를 붙이지 않는다.
 *
 * **스토어를 import하지 않고 스토어가 이것을 호출하는 방향인 이유** — 반대로 하면
 * `apiClient -> chatStore -> apiClient` 순환이 생긴다. 토큰의 소유자는 스토어이고
 * 여기는 그 사본을 받아 쓰는 쪽이다.
 */
export function setAuthToken(token: string | null): void {
  authToken = token
}

export function getAuthToken(): string | null {
  return authToken
}

// --------------------------------------------------------------------------
// 내부
// --------------------------------------------------------------------------
const GENERIC_TRANSPORT_MESSAGE = '서버에 연결할 수 없습니다. 잠시 후 다시 시도하세요'

/**
 * 응답 본문에서 `{code, message}`를 뽑는다.
 *
 * 세 가지 모양을 받아야 한다:
 *   1. 우리 도메인 오류 — `{"error": {"code", "message"}}`
 *   2. FastAPI/pydantic 형식 오류(422) — `{"detail": [...]}`
 *   3. 그 외 — 프록시가 낀 HTML 오류 페이지 등, JSON이 아닐 수도 있다
 *
 * 3번을 대비해 파싱 실패를 삼키고 일반 문구를 쓴다. 여기서 예외가 나가면 사용자는
 * 아무 문구도 못 보고 콘솔에만 오류가 남는다.
 */
function normalizeError(status: number, body: unknown): ApiError {
  if (typeof body === 'object' && body !== null) {
    const wrapper = body as { error?: { code?: unknown; message?: unknown }; detail?: unknown }

    if (
      wrapper.error &&
      typeof wrapper.error.code === 'string' &&
      typeof wrapper.error.message === 'string'
    ) {
      return { code: wrapper.error.code, message: wrapper.error.message, status }
    }

    if (status === 422) {
      // pydantic의 형식 오류. 사용자가 읽을 문구가 아니므로 우리 문구로 바꾼다.
      return { code: 'VALIDATION_FAILED', message: '입력값을 확인하세요', status }
    }
  }

  return { code: 'UNKNOWN', message: '요청을 처리할 수 없습니다', status }
}

/**
 * 응답을 정규화하지 않고 그대로 돌려주는 하위 계층.
 *
 * **`sendMessage()`만 이것을 직접 쓴다.** U5의 409는 `{"error": {...}}` 봉투가 아니라
 * `{log_id, reason, score}`를 최상위에 담고, 그 `log_id`가 재요청에 반드시 필요하다
 * (BR-6.4). `request()`의 오류 정규화를 태우면 그 값이 사라진다.
 *
 * 예외 규약은 `request()`와 같다 — 네트워크 실패·타임아웃·5xx만 throw한다.
 */
interface RawResponse {
  status: number
  ok: boolean
  body: unknown
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  const raw = await requestRaw(method, path, body)
  if (!raw.ok) {
    return { ok: false, error: normalizeError(raw.status, raw.body) }
  }
  return { ok: true, data: raw.body as T }
}

async function requestRaw(
  method: string,
  path: string,
  body?: unknown,
): Promise<RawResponse> {
  const controller = new AbortController()
  // `AbortSignal.timeout()`을 쓰지 않는 이유 — jsdom 환경에서 구현 여부가 갈린다.
  // 명시적인 타이머는 어디서든 같게 동작한다.
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (authToken !== null) headers.Authorization = `Bearer ${authToken}`

  let response: Response
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch {
    // 네트워크 실패와 타임아웃(abort)이 여기로 온다. 상태 코드가 없으므로 0을 쓴다.
    throw new ApiTransportError(GENERIC_TRANSPORT_MESSAGE, 0)
  } finally {
    clearTimeout(timer)
  }

  // 본문이 비어 있거나 JSON이 아닐 수 있다 — 그 자체가 예외가 되면 안 된다.
  let parsed: unknown = null
  const text = await response.text()
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = null
    }
  }

  if (response.status >= 500) {
    // 5xx는 사용자가 고칠 수 없다 — 던진다.
    throw new ApiTransportError(GENERIC_TRANSPORT_MESSAGE, response.status)
  }

  return { status: response.status, ok: response.ok, body: parsed }
}

// --------------------------------------------------------------------------
// 엔드포인트 (component-methods.md가 고정한 경로)
// --------------------------------------------------------------------------

/** `POST /auth/signup` — 성공 응답에 토큰이 함께 온다(자동 로그인). */
export function signup(username: string, password: string): Promise<ApiResult<AuthPayload>> {
  return request<AuthPayload>('POST', '/auth/signup', { username, password })
}

/** `POST /auth/login` — 실패는 401 `INVALID_CREDENTIALS` 하나뿐이다 (BR-1.4). */
export function login(username: string, password: string): Promise<ApiResult<AuthPayload>> {
  return request<AuthPayload>('POST', '/auth/login', { username, password })
}

/**
 * `GET /users/search` — 아이디 정확 일치.
 *
 * **없어도 성공이다** — `{ok: true, data: {user: null}}`가 온다 (BR-2.1).
 * 호출부는 `data.user === null`로 "결과 없음"을 판단하며 오류로 다루지 않는다.
 */
export function searchUser(username: string): Promise<ApiResult<{ user: SearchedUser | null }>> {
  const query = new URLSearchParams({ username })
  return request<{ user: SearchedUser | null }>('GET', `/users/search?${query.toString()}`)
}

/** `GET /friends` — 내가 등록한 친구만 (단방향, BR-2.3). */
export function listFriends(): Promise<ApiResult<{ friends: Friend[] }>> {
  return request<{ friends: Friend[] }>('GET', '/friends')
}

/** `POST /friends` — 단방향 즉시 등록. 별칭 필수 (BR-2.2). */
export function addFriend(username: string, alias: string): Promise<ApiResult<Friend>> {
  return request<Friend>('POST', '/friends', { username, alias })
}

/** `PATCH /friends/{id}` — 별칭 수정. 없는 id와 남의 id 모두 403 (BR-2.7). */
export function updateAlias(friendshipId: number, alias: string): Promise<ApiResult<Friend>> {
  return request<Friend>('PATCH', `/friends/${friendshipId}`, { alias })
}

/**
 * `POST /rooms` — 친구를 초대해 방을 만든다 (FR-3.1).
 *
 * 실패는 400 두 가지다 — `EMPTY_ROOM`(아무도 고르지 않음)과 `NOT_A_FRIEND`. 둘 다
 * 사용자가 화면에서 고칠 수 있으므로 던지지 않고 `{ok:false}`로 온다.
 */
export function createRoom(
  friendUserIds: number[],
  name: string | null,
): Promise<ApiResult<RoomDetail>> {
  return request<RoomDetail>('POST', '/rooms', { friend_user_ids: friendUserIds, name })
}

/** `GET /rooms` — 내 방 목록. **빈 배열도 성공이다** (BR-3.4). */
export function listRooms(): Promise<ApiResult<{ rooms: RoomSummary[] }>> {
  return request<{ rooms: RoomSummary[] }>('GET', '/rooms')
}

/** `GET /rooms/{id}` — 참여자가 아니거나 **없는 방이면 403이다** (BR-3.3). */
export function getRoom(roomId: number): Promise<ApiResult<RoomDetail>> {
  return request<RoomDetail>('GET', `/rooms/${roomId}`)
}

/**
 * `POST /rooms/{id}/read` — 읽음 위치 전진 (FR-5.2).
 *
 * **전진하지 못해도 200이다** (BR-5.3). 순서가 뒤바뀐 요청은 서버가 무시하며,
 * 응답에는 현재 값이 담긴다 — 호출부가 실패로 다루지 않아야 한다.
 */
export function markRead(
  roomId: number,
  upToSeq: number,
): Promise<ApiResult<{ last_read_seq: number }>> {
  return request<{ last_read_seq: number }>('POST', `/rooms/${roomId}/read`, {
    up_to_seq: upToSeq,
  })
}

/** `PATCH /rooms/{id}/ai-check` — **내** 검증 토글만 바꾼다 (BR-6.1). */
export function setAiCheck(
  roomId: number,
  enabled: boolean,
): Promise<ApiResult<{ ai_check_enabled: boolean }>> {
  return request<{ ai_check_enabled: boolean }>('PATCH', `/rooms/${roomId}/ai-check`, { enabled })
}

/**
 * `POST /rooms/{id}/messages` — 전송 (FR-4.1~FR-4.3, FR-6.6, FR-8.2).
 *
 * **409를 예외로 던지지 않는다.** 부적절 판정도 판정 실패도 정상 분기이며, 응답의
 * `log_id`가 강행 재요청의 열쇠다 (BR-6.4).
 *
 * @param opts.forceLogId 팝업에서 강행을 고른 경우의 판정 로그 id.
 * @param opts.degraded 클라이언트가 degraded 상태인가 (ADR-007). 서버는 브라우저 탭
 *   단위 상태를 알 수 없어 클라이언트가 알려준다.
 * @param opts.probe 이번 전송이 프로브인가 (BR-8.5). **`degraded`와 별개 필드인
 *   이유** — 프로브 실패는 팝업 없이 201 `failed`로 끝나야 하는데(BR-8.5), 서버가
 *   프로브임을 모르면 세션 첫 실패와 구분하지 못해 409를 준다.
 */
export async function sendMessage(
  roomId: number,
  text: string,
  opts: { forceLogId?: number; degraded?: boolean; probe?: boolean } = {},
): Promise<SendOutcome> {
  const raw = await requestRaw('POST', `/rooms/${roomId}/messages`, {
    text,
    force_log_id: opts.forceLogId ?? null,
    degraded: opts.degraded ?? false,
    probe: opts.probe ?? false,
  })

  if (raw.ok) {
    return { kind: 'sent', message: raw.body as ChatMessage }
  }

  if (raw.status === 409) {
    const blocked = raw.body as { log_id?: unknown; reason?: unknown; score?: unknown }
    if (typeof blocked.log_id === 'number' && blocked.reason === 'inappropriate') {
      // 점수가 없는 응답은 오지 않지만, 있다고 단정하지 않는다 — 없으면 0으로 둔다.
      // 화면이 점수를 문구에 쓰지 않으므로 이 폴백이 사용자에게 보이지 않는다.
      return {
        kind: 'blocked',
        reason: 'inappropriate',
        logId: blocked.log_id,
        score: typeof blocked.score === 'number' ? blocked.score : 0,
      }
    }
    if (typeof blocked.log_id === 'number' && blocked.reason === 'judge_failed') {
      return { kind: 'blocked', reason: 'judge_failed', logId: blocked.log_id }
    }
    // `ALREADY_RESOLVED`도 409로 온다 (BR-7.1). 그것은 오류 봉투를 쓰므로 위 두 분기에
    // 걸리지 않고 여기로 떨어진다 — 사용자에게는 "다시 시도"가 맞는 안내다.
  }

  return { kind: 'error', error: normalizeError(raw.status, raw.body) }
}

/**
 * `GET /rooms/{id}/messages` — 히스토리 (FR-3.3, FR-4.4).
 *
 * `before`는 **경계를 포함하지 않는다** (`seq < before`). 포함하면 페이지 경계에서
 * 한 건이 중복된다.
 */
export function listMessages(
  roomId: number,
  opts: { before?: number; limit?: number } = {},
): Promise<ApiResult<{ messages: ChatMessage[] }>> {
  const query = new URLSearchParams()
  if (opts.before !== undefined) query.set('before', String(opts.before))
  if (opts.limit !== undefined) query.set('limit', String(opts.limit))
  const suffix = query.toString() === '' ? '' : `?${query.toString()}`
  return request<{ messages: ChatMessage[] }>('GET', `/rooms/${roomId}/messages${suffix}`)
}

/**
 * `PATCH /judgments/{id}` — 팝업에서 "취소"를 고른 사실을 기록한다 (BR-6.5, FR-7.2).
 *
 * **취소는 전송이 없어서** `sendMessage()` 경로를 타지 않는다. 여기서 기록하지 않으면
 * TP가 영원히 0이 되어 precision이 계산되지 않는다 (FR-7.3).
 */
export function judgmentAction(
  logId: number,
  action: 'sent' | 'cancelled',
): Promise<ApiResult<null>> {
  return request<null>('PATCH', `/judgments/${logId}`, { user_action: action })
}

/**
 * `POST`/`DELETE /messages/{id}/report` — 오발송 신고와 취소 (FR-11).
 *
 * **검증 상태와 무관하게 가능하다** (BR-11.2). 남의 메시지와 없는 메시지 모두 403이다.
 */
export function reportMisdirect(
  messageId: number,
  on: boolean,
): Promise<ApiResult<{ misdirect_reported_at: string | null }>> {
  return request<{ misdirect_reported_at: string | null }>(
    on ? 'POST' : 'DELETE',
    `/messages/${messageId}/report`,
  )
}
