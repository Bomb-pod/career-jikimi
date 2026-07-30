import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { connect, disconnect, isReplaced } from './wsClient'
import { useChatStore } from '../store/chatStore'

/**
 * `wsClient` — FR-1.3(첫 프레임 인증)과 BR-5.5(밀려난 탭은 재연결하지 않는다).
 *
 * **이 파일에서 가장 중요한 테스트는 `session_replaced` 후 재연결하지 않는다**이다.
 * 그것이 없으면 밀려난 탭이 다시 붙어 원래 탭을 밀어내고, 두 탭이 서로를 밀어내는
 * 순환이 생긴다. 서버 쪽 절반(프레임을 보낸 뒤 닫기)은 `test_ws_registry.py`가 본다.
 *
 * jsdom의 `WebSocket`을 쓰지 않고 가짜로 갈아끼우는 이유 — 실제 구현은 네트워크에
 * 나가려 하고, 무엇보다 **서버가 끊는 상황을 우리가 만들 수 없다.**
 */

/** 생성된 소켓을 기록하는 가짜 `WebSocket`. 열림·닫힘·수신을 테스트가 조종한다. */
class FakeWebSocket {
  static instances: FakeWebSocket[] = []

  readonly url: string
  readonly sent: string[] = []
  closed = false
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(): void {
    this.closed = true
  }

  /** 서버가 연결을 받아들였다. */
  simulateOpen(): void {
    this.onopen?.()
  }

  /** 서버가 프레임을 보냈다. */
  simulateFrame(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent)
  }

  /** 연결이 끊겼다 — 서버가 닫았든 네트워크가 끊겼든 클라이언트에게는 같다. */
  simulateClose(): void {
    this.onclose?.()
  }
}

const TOKEN = 'jwt-token'

beforeEach(() => {
  vi.useFakeTimers()
  FakeWebSocket.instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  useChatStore.setState({
    auth: { token: TOKEN, user: { id: 1, username: 'alice' } },
    sessionReplaced: false,
    wsStatus: 'idle',
  })
})

afterEach(() => {
  // `disconnect()`가 모듈 상태를 남김없이 되돌린다 — 그러지 않으면 다음 테스트가
  // 앞 테스트의 백오프 시도 횟수를 물려받는다.
  disconnect()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function latest(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1)
  if (socket === undefined) throw new Error('연결이 만들어지지 않았다')
  return socket
}

describe('wsClient 인증', () => {
  it('연결되자마자 첫 프레임으로 auth를 보낸다', () => {
    // FR-1.3 — 서버는 5초 안에 이 프레임을 받아야 하고, 그 전의 다른 프레임은
    // 처리하지 않는다 (BR-5.6).
    connect(TOKEN)
    latest().simulateOpen()

    expect(latest().sent).toEqual([JSON.stringify({ type: 'auth', token: TOKEN })])
  })

  it('auth_ok를 받으면 연결 확립으로 표시한다', () => {
    connect(TOKEN)
    latest().simulateOpen()
    latest().simulateFrame({ type: 'auth_ok' })

    expect(useChatStore.getState().wsStatus).toBe('open')
  })

  it('auth_error를 받으면 재로그인으로 유도하고 재연결하지 않는다', () => {
    // 토큰이 유효하지 않다 — 다시 붙어도 같은 결과다. 무한 재연결은 서버만 때린다.
    connect(TOKEN)
    latest().simulateOpen()
    latest().simulateFrame({ type: 'auth_error', reason: 'invalid_token' })
    const afterError = FakeWebSocket.instances.length

    latest().simulateClose()
    vi.advanceTimersByTime(60_000)

    expect(useChatStore.getState().auth.token).toBeNull()
    expect(FakeWebSocket.instances).toHaveLength(afterError)
  })
})

describe('wsClient 재연결', () => {
  it('session_replaced를 받으면 **재연결하지 않는다** (BR-5.5)', () => {
    // 이 테스트가 이 파일의 이유다. 재연결하면 밀려난 탭이 원래 탭을 밀어내고,
    // 두 탭이 서로를 밀어내는 순환이 생긴다.
    connect(TOKEN)
    latest().simulateOpen()
    latest().simulateFrame({ type: 'auth_ok' })

    latest().simulateFrame({ type: 'session_replaced' })
    latest().simulateClose()
    vi.advanceTimersByTime(60_000)

    expect(isReplaced()).toBe(true)
    expect(useChatStore.getState().sessionReplaced).toBe(true)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('그 외의 단절에는 다시 연결한다', () => {
    // 네트워크가 끊긴 것은 밀려난 것과 다르다. 여기서 포기하면 앱이 조용히 죽는다.
    connect(TOKEN)
    latest().simulateOpen()
    latest().simulateFrame({ type: 'auth_ok' })

    latest().simulateClose()
    expect(useChatStore.getState().wsStatus).toBe('reconnecting')
    vi.advanceTimersByTime(1_000)

    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('재연결 간격이 1→2→4초로 늘어난다', () => {
    // 상한 없이 즉시 재시도하면 서버가 내려간 동안 초당 수십 번을 때린다.
    connect(TOKEN)
    latest().simulateOpen()

    latest().simulateClose()
    vi.advanceTimersByTime(999)
    expect(FakeWebSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(2)

    latest().simulateClose()
    vi.advanceTimersByTime(1_999)
    expect(FakeWebSocket.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(3)

    latest().simulateClose()
    vi.advanceTimersByTime(3_999)
    expect(FakeWebSocket.instances).toHaveLength(3)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(4)
  })

  it('간격이 16초를 넘지 않는다', () => {
    // 상한이 없으면 오래 끊긴 뒤의 대기가 분 단위로 늘어나 복구가 체감되지 않는다.
    connect(TOKEN)
    for (let round = 0; round < 8; round += 1) {
      latest().simulateOpen()
      latest().simulateClose()
      vi.advanceTimersByTime(16_000)
    }
    const beforeLast = FakeWebSocket.instances.length

    latest().simulateClose()
    vi.advanceTimersByTime(16_000)

    expect(FakeWebSocket.instances.length).toBe(beforeLast + 1)
  })

  it('재연결에 성공해 auth_ok를 받으면 백오프가 처음으로 돌아간다', () => {
    // 리셋하지 않으면 한 번 끊겼던 세션이 이후 내내 16초를 기다린다.
    connect(TOKEN)
    latest().simulateOpen()
    latest().simulateClose()
    vi.advanceTimersByTime(1_000)
    latest().simulateOpen()
    latest().simulateFrame({ type: 'auth_ok' })

    latest().simulateClose()
    vi.advanceTimersByTime(1_000)

    expect(FakeWebSocket.instances).toHaveLength(3)
  })

  it('disconnect() 후에는 다시 연결하지 않는다', () => {
    // 로그아웃 경로다. 여기서 재연결하면 앞 사용자의 연결로 새 세션이 붙는다.
    connect(TOKEN)
    latest().simulateOpen()
    const socket = latest()

    disconnect()
    socket.simulateClose()
    vi.advanceTimersByTime(60_000)

    expect(socket.closed).toBe(true)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})

describe('wsClient 프레임 분배', () => {
  it('message 프레임을 스토어로 넘긴다', () => {
    useChatStore.setState({ currentRoomId: 7, messages: [] })
    connect(TOKEN)
    latest().simulateOpen()

    latest().simulateFrame({
      type: 'message',
      room_id: 7,
      message: {
        id: 11,
        room_id: 7,
        sender_id: 2,
        seq: 3,
        body: '안녕',
        created_at: '2026-07-30T00:00:00Z',
      },
    })

    expect(useChatStore.getState().messages.map((item) => item.id)).toEqual([11])
  })

  it('봉투의 room_id를 메시지에 채워 넣는다', () => {
    // `services.md`의 봉투는 `room_id`를 최상위에 둔다. 메시지 객체에 없을 수 있으므로
    // 최상위 값을 신뢰한다 — 없으면 그 메시지가 어느 방 것인지 알 수 없어 사라진다.
    useChatStore.setState({ currentRoomId: null, rooms: [], unread: {}, toasts: [] })
    connect(TOKEN)
    latest().simulateOpen()

    latest().simulateFrame({
      type: 'message',
      room_id: 9,
      message: { id: 1, sender_id: 2, seq: 1, body: '안녕', created_at: '2026-07-30T00:00:00Z' },
    })

    expect(useChatStore.getState().unread[9]).toBe(1)
  })

  it('알 수 없는 프레임과 깨진 JSON을 조용히 버린다', () => {
    // 서버가 프레임을 하나 추가했을 때 구버전 클라이언트가 예외로 죽으면,
    // 아는 프레임까지 함께 처리되지 않는다.
    connect(TOKEN)
    latest().simulateOpen()

    latest().simulateFrame({ type: 'something_new' })
    latest().onmessage?.({ data: '이건 JSON이 아니다' } as MessageEvent)

    latest().simulateFrame({ type: 'auth_ok' })
    expect(useChatStore.getState().wsStatus).toBe('open')
  })
})
