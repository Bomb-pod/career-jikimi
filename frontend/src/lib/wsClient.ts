/**
 * `wsClient` — WebSocket 연결·인증·재연결·수신 프레임 분배
 * (`components.md` § wsClient, `business-logic-model.md` § wsClient).
 *
 * **보내는 것은 인증 프레임 하나뿐이다** (ADR-001, FR-1.3). 전송은 HTTP가 담당하고
 * 이 채널은 서버 → 클라이언트 푸시 전용이다.
 *
 * **컴포넌트 밖에서 스토어를 갱신한다** (ADR-004). 수신 핸들러는 React 트리 안에
 * 없으므로 `useChatStore.getState()`로 접근한다 — Zustand를 고른 이유가 이 한 줄이다.
 *
 * 대응: FR-1.3, FR-5.1, FR-5.4, BR-5.5.
 */

import { useChatStore } from '../store/chatStore'
import type { ChatMessage } from './apiClient'
import { WS_BACKOFF_MAX_MS, WS_BACKOFF_START_MS } from './constants'

/** 연결 상태. 화면이 "재연결 중"을 보여주는 근거다. */
export type WsStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'replaced' | 'unauthorized'

// --------------------------------------------------------------------------
// 모듈 상태
// --------------------------------------------------------------------------
// 모듈 전역인 이유 — 연결은 앱 전체에 하나다 (FR-5.1). 컴포넌트에 두면 마운트·언마운트마다
// 연결이 생겼다 사라지고, 방마다 연결을 새로 여는 구조로 미끄러진다.
let socket: WebSocket | null = null
let token: string | null = null
let attempt = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

/**
 * **밀려난 탭인가** (BR-5.5).
 *
 * 이 플래그가 재연결을 막는 유일한 장치다. 없으면 밀려난 탭이 다시 붙어 원래 탭을
 * 밀어내고, 두 탭이 서로를 밀어내는 순환이 생긴다. `session_replaced`를 받은 뒤에는
 * **새로고침(=모듈 재평가)이나 명시적 `connect()` 호출로만** 되살아난다.
 */
let replaced = false

/** `disconnect()`로 스스로 끊었는가. 재연결 대상이 아니다. */
let intentionalClose = false

function setStatus(status: WsStatus): void {
  useChatStore.getState().setWsStatus(status)
}

/**
 * `ws(s)://<현재 오리진>/ws`.
 *
 * 오리진을 상수로 두지 않는 이유 — 개발에서는 Vite dev 서버(5173)가 프록시하고
 * 배포에서는 같은 오리진의 FastAPI가 받는다. 하드코딩하면 그 차이가 코드에 조건문으로
 * 남고, 한쪽에서만 동작하는 빌드가 나온다.
 */
function socketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws`
}

function clearReconnectTimer(): void {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
}

/**
 * 지수 백오프로 재연결을 예약한다 — 1 → 2 → 4 → 8 → 16초, **상한 16초로 무제한 시도**.
 *
 * 시도 횟수를 유한하게 막지 않는 이유 (`code-generation-plan.md` § 열린 항목) —
 * 시도가 끝나면 앱이 **조용히 죽은 채로** 남는다. 사용자는 새 메시지가 오지 않는
 * 이유를 알 수 없고, 데모 도중이라면 그 침묵이 그대로 노출된다. 상한을 16초로 두면
 * 재연결 트래픽은 억제되고 복구는 자동으로 일어난다.
 *
 * 재연결 중임을 상태로 알린다 — 화면이 그 사실을 보여줄 수 있어야 한다.
 */
function scheduleReconnect(): void {
  if (replaced || intentionalClose || token === null) return

  clearReconnectTimer()
  const delay = Math.min(WS_BACKOFF_START_MS * 2 ** attempt, WS_BACKOFF_MAX_MS)
  attempt += 1
  setStatus('reconnecting')
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    if (token !== null) open(token)
  }, delay)
}

/**
 * 수신 프레임을 타입별로 분배한다.
 *
 * 알 수 없는 `type`은 **조용히 버린다.** 서버가 프레임을 하나 추가했을 때 구버전
 * 클라이언트가 예외로 죽는 것보다, 모르는 것을 무시하고 아는 것을 계속 처리하는
 * 편이 낫다.
 */
function route(raw: string): void {
  let frame: unknown
  try {
    frame = JSON.parse(raw)
  } catch {
    // 서버가 JSON이 아닌 것을 보낼 일은 없지만, 프록시가 낀 경우를 대비한다.
    return
  }
  if (typeof frame !== 'object' || frame === null) return

  const envelope = frame as { type?: unknown; room_id?: unknown; message?: unknown }
  const store = useChatStore.getState()

  switch (envelope.type) {
    case 'auth_ok':
      attempt = 0
      setStatus('open')
      return

    case 'auth_error':
      // 토큰이 유효하지 않다 — 재연결해도 같은 결과다. 재로그인으로 유도한다.
      setStatus('unauthorized')
      intentionalClose = true
      store.clearAuth()
      return

    case 'session_replaced':
      // **BR-5.5** — 재연결하지 않는다. 배너를 띄우는 것이 유일한 반응이다.
      replaced = true
      setStatus('replaced')
      store.markSessionReplaced()
      return

    case 'message': {
      const message = envelope.message
      if (typeof message !== 'object' || message === null) return
      const candidate = message as Partial<ChatMessage>
      if (typeof candidate.id !== 'number' || typeof candidate.seq !== 'number') return
      // 봉투의 `room_id`가 있으면 그것을 신뢰한다 — `services.md`가 최상위에 두었고,
      // 메시지 객체에 없을 수도 있다.
      const roomId = typeof envelope.room_id === 'number' ? envelope.room_id : candidate.room_id
      if (typeof roomId !== 'number') return
      store.receiveMessage({ ...(candidate as ChatMessage), room_id: roomId })
      return
    }

    default:
      return
  }
}

function open(authToken: string): void {
  setStatus('connecting')
  const next = new WebSocket(socketUrl())
  socket = next

  next.onopen = () => {
    // **첫 프레임이 인증이다** (FR-1.3). 서버는 5초 안에 이것을 받아야 하며,
    // 그 전에 온 다른 프레임은 처리하지 않는다 (BR-5.6).
    next.send(JSON.stringify({ type: 'auth', token: authToken }))
  }

  next.onmessage = (event: MessageEvent) => {
    if (typeof event.data === 'string') route(event.data)
  }

  next.onclose = () => {
    if (socket === next) socket = null
    // **`replaced`면 재연결하지 않는다** (BR-5.5). 이 분기가 이 파일의 핵심이다.
    scheduleReconnect()
  }

  next.onerror = () => {
    // `onerror` 뒤에는 항상 `onclose`가 온다 — 재연결 예약을 여기서 또 하면
    // 타이머가 둘이 된다. 상태만 남긴다.
    if (!replaced && !intentionalClose) setStatus('reconnecting')
  }
}

/**
 * 연결을 연다. 이미 연결되어 있으면 아무것도 하지 않는다.
 *
 * **`session_replaced`를 받은 뒤에도 명시적 호출은 통한다** — 사용자가 "이 탭에서
 * 계속하기"를 택하는 경로가 그것이다. 자동 재연결만 막는 것이 BR-5.5의 요구다.
 */
export function connect(authToken: string): void {
  if (socket !== null && token === authToken) return

  disconnect()
  token = authToken
  replaced = false
  intentionalClose = false
  attempt = 0
  open(authToken)
}

/**
 * 연결을 끊고 모듈 상태를 초기화한다. 재연결하지 않는다.
 *
 * 로그아웃과 테스트 격리가 이 함수를 쓴다. **상태를 남김없이 되돌리는 것이 계약이다** —
 * 절반만 남으면 다음 `connect()`가 앞 세션의 백오프 시도 횟수를 물려받는다.
 */
export function disconnect(): void {
  intentionalClose = true
  clearReconnectTimer()
  attempt = 0
  replaced = false
  token = null

  const current = socket
  socket = null
  if (current !== null) {
    // 핸들러를 먼저 떼어낸다 — 그러지 않으면 아래 `close()`가 `onclose`를 불러
    // 재연결이 예약된다.
    current.onopen = null
    current.onmessage = null
    current.onclose = null
    current.onerror = null
    current.close()
  }
  setStatus('idle')
}

/** 밀려난 탭인지. 화면과 테스트가 확인한다 (BR-5.5). */
export function isReplaced(): boolean {
  return replaced
}
