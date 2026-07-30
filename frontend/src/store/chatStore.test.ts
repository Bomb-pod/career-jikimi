import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useChatStore } from './chatStore'
import type { ChatMessage, RoomSummary } from '../lib/apiClient'

/**
 * `chatStore` — **이 단위의 명시된 테스트 의무** (`business-logic-model.md` § 테스트 대상).
 *
 * | 대상 | 무엇을 검증 |
 * |---|---|
 * | 구독·fetch 순서와 중복 제거 (FR-3.3) | 방 입장 중(포인터 이동 후 히스토리 응답 전) 도착한 메시지가 유실되지 않는가. 히스토리와 구독 스트림에 같은 메시지가 있어도 한 번만 표시되는가 |
 *
 * 히스토리 조회 API 자체는 U5 소관이므로 이 테스트는 **클라이언트 측 병합 로직**을
 * 대상으로 한다. `enterRoom()`이 히스토리 로더를 인자로 받는 것이 그 때문이며, 여기서는
 * 응답 시점을 테스트가 직접 잡는 로더를 넣어 "그 사이"를 실제로 만들어낸다.
 */

const api = vi.hoisted(() => ({
  markRead: vi.fn(() => Promise.resolve({ ok: true as const, data: { last_read_seq: 0 } })),
  setAuthToken: vi.fn(),
  // U5가 `enterRoom()`의 기본 히스토리 로더를 이 호출로 바꿨다. 명시적 로더를 넘기지
  // 않는 테스트가 실제 fetch로 나가지 않도록 여기서도 대역을 둔다.
  listMessages: vi.fn(() => Promise.resolve({ ok: true as const, data: { messages: [] } })),
  // `hydrateSession()`이 부른다 — 새로고침 후 "내가 누구인지" 복구.
  me: vi.fn(),
}))

vi.mock('../lib/apiClient', () => api)

function message(overrides: Partial<ChatMessage> & { id: number; room_id: number }): ChatMessage {
  return {
    sender_id: 2,
    seq: overrides.id,
    body: `메시지 ${overrides.id}`,
    created_at: '2026-07-30T00:00:00Z',
    // U5가 더한 두 필드 (FR-7.1, FR-11.3). 기본값은 "검증됨 · 신고 안 됨"이다.
    verification_status: 'ok',
    misdirect_reported_at: null,
    ...overrides,
  }
}

function room(overrides: Partial<RoomSummary> & { id: number }): RoomSummary {
  return {
    name: `방 ${overrides.id}`,
    last_seq: 0,
    created_at: '2026-07-30T00:00:00Z',
    unread_count: 0,
    last_read_seq: 0,
    ai_check_enabled: true,
    members: [],
    ...overrides,
  }
}

/** 응답 시점을 테스트가 잡는 로더. `resolve()`를 부를 때까지 히스토리가 도착하지 않는다. */
function deferredLoader(history: ChatMessage[]) {
  let release: () => void = () => undefined
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  return {
    load: async () => {
      await gate
      return history
    },
    release,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  useChatStore.setState({
    auth: { token: 'jwt-token', user: { id: 1, username: 'alice' } },
    rooms: [],
    unread: {},
    currentRoomId: null,
    messages: [],
    toasts: [],
    sessionReplaced: false,
  })
})

afterEach(() => {
  useChatStore.setState({ currentRoomId: null, messages: [], toasts: [] })
})

// --------------------------------------------------------------------------
// 구독 먼저, 히스토리 나중 (FR-3.3, BR-3.5) — 이 단위의 명시된 의무
// --------------------------------------------------------------------------
describe('enterRoom 구독·fetch 순서', () => {
  it('**포인터를 히스토리보다 먼저 옮긴다** (BR-3.5)', () => {
    // 반대 순서면 히스토리를 기다리는 동안 도착한 메시지가 "보고 있지 않은 방"으로
    // 분류되어 목록에 들어가지 않는다.
    const { load } = deferredLoader([])
    useChatStore.setState({ rooms: [room({ id: 2 })] })

    void useChatStore.getState().enterRoom(2, load)

    // await 하지 않았는데도 이미 옮겨져 있다.
    expect(useChatStore.getState().currentRoomId).toBe(2)
  })

  it('**히스토리 응답 전에 도착한 메시지가 유실되지 않는다** (FR-3.3의 첫 기준)', async () => {
    // Given 방에 입장하는 중이다
    // When 구독 완료 시점과 히스토리 응답 도착 시점 사이에 새 메시지가 도착하면
    // Then 그 메시지가 화면에 나타나고 유실되지 않는다
    const { load, release } = deferredLoader([message({ id: 1, room_id: 2, seq: 1 })])
    useChatStore.setState({ rooms: [room({ id: 2 })] })

    const entering = useChatStore.getState().enterRoom(2, load)
    // ← 여기가 "그 사이"다. 히스토리는 아직 오지 않았다.
    useChatStore.getState().receiveMessage(message({ id: 9, room_id: 2, seq: 2 }))
    release()
    await entering

    expect(useChatStore.getState().messages.map((item) => item.id)).toEqual([1, 9])
  })

  it('**히스토리와 스트림에 같은 메시지가 있어도 한 번만 표시된다** (FR-3.3의 둘째 기준)', async () => {
    // Given 히스토리 응답과 구독 스트림에 같은 메시지가 모두 포함되었다
    // When 화면을 렌더링하면
    // Then 그 메시지는 한 번만 표시된다
    const overlapping = message({ id: 5, room_id: 2, seq: 5 })
    const { load, release } = deferredLoader([
      message({ id: 4, room_id: 2, seq: 4 }),
      overlapping,
    ])
    useChatStore.setState({ rooms: [room({ id: 2 })] })

    const entering = useChatStore.getState().enterRoom(2, load)
    useChatStore.getState().receiveMessage(overlapping)
    release()
    await entering

    expect(useChatStore.getState().messages.map((item) => item.id)).toEqual([4, 5])
  })

  it('메시지를 seq 순으로 정렬한다', async () => {
    // 도착 순서가 저장 순서와 다를 수 있다. 정렬 기준은 `created_at`이 아니라
    // `seq`다 (FR-4.2, NFR-4).
    const { load, release } = deferredLoader([
      message({ id: 30, room_id: 2, seq: 3 }),
      message({ id: 10, room_id: 2, seq: 1 }),
    ])
    useChatStore.setState({ rooms: [room({ id: 2 })] })

    const entering = useChatStore.getState().enterRoom(2, load)
    useChatStore.getState().receiveMessage(message({ id: 20, room_id: 2, seq: 2 }))
    release()
    await entering

    expect(useChatStore.getState().messages.map((item) => item.seq)).toEqual([1, 2, 3])
  })

  it('히스토리가 오기 전에 다른 방으로 가면 그 응답을 버린다', async () => {
    // 경계 사례 — 사용자가 방을 빠르게 오갈 때 실제로 일어난다. 버리지 않으면
    // 지금 보고 있는 방에 이전 방의 메시지가 섞인다.
    const first = deferredLoader([message({ id: 1, room_id: 2, seq: 1 })])
    useChatStore.setState({ rooms: [room({ id: 2 }), room({ id: 3 })] })

    const entering = useChatStore.getState().enterRoom(2, first.load)
    await useChatStore.getState().enterRoom(3)
    first.release()
    await entering

    expect(useChatStore.getState().currentRoomId).toBe(3)
    expect(useChatStore.getState().messages).toEqual([])
  })

  it('히스토리 조회가 실패해도 구독은 살아 있다', async () => {
    // 여기서 예외를 올리면 방 입장 자체가 실패한 것처럼 보인다. 새 메시지는
    // WebSocket으로 계속 들어온다.
    useChatStore.setState({ rooms: [room({ id: 2 })] })

    await useChatStore.getState().enterRoom(2, () => Promise.reject(new Error('서버 오류')))
    useChatStore.getState().receiveMessage(message({ id: 7, room_id: 2, seq: 1 }))

    expect(useChatStore.getState().currentRoomId).toBe(2)
    expect(useChatStore.getState().messages.map((item) => item.id)).toEqual([7])
  })
})

// --------------------------------------------------------------------------
// 수신 분기 (BR-5.9)
// --------------------------------------------------------------------------
describe('receiveMessage', () => {
  it('보고 있는 방의 메시지는 목록에 넣고 읽음 처리를 보낸다', async () => {
    useChatStore.setState({ rooms: [room({ id: 2 })] })
    await useChatStore.getState().enterRoom(2)
    api.markRead.mockClear()

    useChatStore.getState().receiveMessage(message({ id: 8, room_id: 2, seq: 12 }))

    expect(useChatStore.getState().messages.map((item) => item.id)).toEqual([8])
    expect(api.markRead).toHaveBeenCalledWith(2, 12)
  })

  it('보고 있는 방에는 토스트를 띄우지 않는다 (BR-5.9)', async () => {
    // FR-5.3의 셋째 기준 — 이미 보고 있는 방이다.
    useChatStore.setState({ rooms: [room({ id: 2 })] })
    await useChatStore.getState().enterRoom(2)

    useChatStore.getState().receiveMessage(message({ id: 8, room_id: 2, seq: 1 }))

    expect(useChatStore.getState().toasts).toEqual([])
    expect(useChatStore.getState().unread[2]).toBe(0)
  })

  it('다른 방의 메시지는 배지를 올리고 토스트를 띄운다', () => {
    // FR-5.2의 첫 기준 + FR-5.3의 첫 기준. 토스트에 **방 이름이 보여야 한다.**
    useChatStore.setState({
      rooms: [room({ id: 2, name: '동아리' }), room({ id: 3, name: '가족' })],
      currentRoomId: 2,
    })

    useChatStore.getState().receiveMessage(message({ id: 11, room_id: 3, seq: 11 }))
    useChatStore.getState().receiveMessage(message({ id: 12, room_id: 3, seq: 12 }))

    expect(useChatStore.getState().unread[3]).toBe(2)
    const toasts = useChatStore.getState().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0]?.roomName).toBe('가족')
  })

  it('이름 없는 방의 토스트에도 참여자 이름이 보인다', () => {
    // FR-5.3의 수용 기준이 "토스트 안에 방 이름이 보인다"이므로, 이름이 없는 방도
    // 목록과 **같은 규칙으로** 조립한다. 두 곳이 다르면 사용자가 두 방으로 인식한다.
    useChatStore.setState({
      rooms: [
        room({
          id: 3,
          name: null,
          members: [
            { user_id: 1, display_name: 'alice' },
            { user_id: 2, display_name: '회사 김대리' },
          ],
        }),
      ],
      currentRoomId: null,
    })

    useChatStore.getState().receiveMessage(message({ id: 1, room_id: 3, seq: 1 }))

    // 본인(alice)은 빠진다 — 넣으면 모든 방 이름이 내 이름으로 시작한다.
    expect(useChatStore.getState().toasts[0]?.roomName).toBe('회사 김대리')
  })

  it('같은 방의 연속 메시지는 토스트 하나로 접힌다', () => {
    // 쌓이면 화면을 가리고, `data-testid`가 `toast-{roomId}`라 같은 방의 토스트가
    // 여럿이면 그 훅이 특정 요소를 가리키지 못한다.
    useChatStore.setState({ rooms: [room({ id: 3 })], currentRoomId: null })

    useChatStore.getState().receiveMessage(message({ id: 1, room_id: 3, seq: 1, body: '첫' }))
    useChatStore.getState().receiveMessage(message({ id: 2, room_id: 3, seq: 2, body: '둘' }))

    const toasts = useChatStore.getState().toasts
    expect(toasts).toHaveLength(1)
    expect(toasts[0]?.body).toBe('둘')
  })

  it('토스트는 최대 3개이고 오래된 것부터 사라진다', () => {
    // 4초·3개는 `code-generation-plan.md`가 정한 값이다. 넘치면 화면을 가린다.
    useChatStore.setState({
      rooms: [room({ id: 1 }), room({ id: 2 }), room({ id: 3 }), room({ id: 4 })],
      currentRoomId: null,
    })

    for (const roomId of [1, 2, 3, 4]) {
      useChatStore.getState().receiveMessage(message({ id: roomId, room_id: roomId, seq: 1 }))
    }

    expect(useChatStore.getState().toasts.map((toast) => toast.roomId)).toEqual([2, 3, 4])
  })

  it('같은 메시지가 두 번 와도 목록에 한 번만 들어간다 (BR-5.8)', async () => {
    // 내가 보낸 메시지는 HTTP 응답과 WebSocket 푸시 양쪽으로 온다.
    useChatStore.setState({ rooms: [room({ id: 2 })] })
    await useChatStore.getState().enterRoom(2)
    const mine = message({ id: 42, room_id: 2, seq: 7, sender_id: 1 })

    useChatStore.getState().receiveMessage(mine)
    useChatStore.getState().receiveMessage(mine)

    expect(useChatStore.getState().messages).toHaveLength(1)
  })
})

// --------------------------------------------------------------------------
// 배지와 토스트의 소멸
// --------------------------------------------------------------------------
describe('배지와 토스트', () => {
  it('방에 입장하면 그 방의 배지와 토스트가 사라진다 (BR-5.9)', async () => {
    // FR-5.2의 둘째 기준 + FR-5.3의 둘째 기준.
    useChatStore.setState({ rooms: [room({ id: 3, last_seq: 12 })], currentRoomId: null })
    useChatStore.getState().receiveMessage(message({ id: 12, room_id: 3, seq: 12 }))
    expect(useChatStore.getState().unread[3]).toBe(1)

    await useChatStore.getState().enterRoom(3)

    expect(useChatStore.getState().unread[3]).toBe(0)
    expect(useChatStore.getState().toasts).toEqual([])
    // 서버의 읽음 위치도 함께 전진시킨다 — 그러지 않으면 목록을 다시 부를 때
    // 배지가 되살아난다.
    expect(api.markRead).toHaveBeenCalledWith(3, 12)
  })

  it('setRooms가 서버의 배지 값을 그대로 받아온다', () => {
    // 새로고침 직후의 출처는 서버다. 여기서 옮겨 담지 않으면 배지가 항상 0으로
    // 시작해 "안 읽은 메시지가 없다"고 거짓말한다.
    useChatStore.getState().setRooms([room({ id: 2, unread_count: 5 })])

    expect(useChatStore.getState().unread[2]).toBe(5)
  })

  it('보고 있는 방은 목록을 다시 받아도 0으로 남는다', () => {
    // 경계 사례 — 응답이 만들어진 뒤 그 방을 열었을 수 있다. 서버 값을 그대로 쓰면
    // 보고 있는 방에 배지가 붙는다.
    useChatStore.setState({ currentRoomId: 2 })

    useChatStore.getState().setRooms([room({ id: 2, unread_count: 5 })])

    expect(useChatStore.getState().unread[2]).toBe(0)
  })

  it('로그아웃하면 방·메시지·배지·토스트가 함께 비워진다', () => {
    // 방 이름은 참여자 표시명(별칭 포함)으로 조립된다 — 남아 있으면 다음 사용자에게
    // 앞 사용자의 별칭이 보인다 (FR-2.4).
    useChatStore.setState({
      rooms: [room({ id: 2 })],
      unread: { 2: 3 },
      currentRoomId: 2,
      messages: [message({ id: 1, room_id: 2 })],
    })

    useChatStore.getState().clearAuth()

    const state = useChatStore.getState()
    expect(state.rooms).toEqual([])
    expect(state.unread).toEqual({})
    expect(state.messages).toEqual([])
    expect(state.currentRoomId).toBeNull()
  })
})

describe('hydrateSession — 새로고침 후 세션 복구', () => {
  it('토큰이 없으면 아무 일도 하지 않고 false를 준다', async () => {
    // 부르면 보나마나 401이고, 그 401이 로그를 오염시킨다.
    useChatStore.setState({ auth: { token: null, user: null } })

    const alive = await useChatStore.getState().hydrateSession()

    expect(alive).toBe(false)
    expect(api.me).not.toHaveBeenCalled()
  })

  it('성공하면 `auth.user`를 채우고 토큰은 그대로 둔다', async () => {
    useChatStore.setState({ auth: { token: 'jwt-token', user: null } })
    api.me.mockResolvedValue({ ok: true as const, data: { id: 7, username: 'bob' } })

    const alive = await useChatStore.getState().hydrateSession()

    expect(alive).toBe(true)
    expect(useChatStore.getState().auth).toEqual({
      token: 'jwt-token',
      user: { id: 7, username: 'bob' },
    })
  })

  it('401이면 토큰을 지운다', async () => {
    // 낡은 토큰을 들고 있으면 이후 모든 요청이 401이 되고 사용자는 로그인했다고 믿는다.
    useChatStore.setState({ auth: { token: 'stale', user: null } })
    api.me.mockResolvedValue({
      ok: false as const,
      error: { code: 'INVALID_TOKEN', message: '유효하지 않은 토큰입니다', status: 401 },
    })

    const alive = await useChatStore.getState().hydrateSession()

    expect(alive).toBe(false)
    expect(useChatStore.getState().auth.token).toBeNull()
  })

  it('네트워크 오류에는 토큰을 지키고 true를 준다', async () => {
    // 서버가 잠깐 죽은 것과 토큰이 죽은 것은 다르다. 전자에서 로그아웃시키면
    // 서버가 돌아와도 다시 로그인해야 한다.
    useChatStore.setState({ auth: { token: 'jwt-token', user: null } })
    api.me.mockResolvedValue({
      ok: false as const,
      error: { code: 'NETWORK', message: '연결할 수 없습니다', status: 0 },
    })

    const alive = await useChatStore.getState().hydrateSession()

    expect(alive).toBe(true)
    expect(useChatStore.getState().auth.token).toBe('jwt-token')
    expect(useChatStore.getState().auth.user).toBeNull()
  })

  it('5xx에도 토큰을 지키지 않고 로그아웃시키지 않는다', async () => {
    useChatStore.setState({ auth: { token: 'jwt-token', user: null } })
    api.me.mockResolvedValue({
      ok: false as const,
      error: { code: 'SERVER', message: '서버 오류', status: 503 },
    })

    const alive = await useChatStore.getState().hydrateSession()

    expect(alive).toBe(true)
    expect(useChatStore.getState().auth.token).toBe('jwt-token')
  })
})
