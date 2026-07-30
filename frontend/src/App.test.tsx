import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { CurrentUser } from './lib/apiClient'
import { useChatStore } from './store/chatStore'

/**
 * 셸 테스트 — 마운트, 세션 수명주기, 뷰 전환.
 *
 * **원래는 U1의 스모크 테스트였다.** 빌드는 통과하면서 런타임에 마운트가 깨지는
 * 경우(`#root` 누락, 플러그인 미설정, JSX 변환 실패)를 잡는 것이 목적이었다.
 * 프론트엔드를 마무리하면서 셸이 실제 책임을 갖게 되어(로그인 상태별 네비게이션,
 * 부팅 시 세션 복구, 자동 이동, 로그아웃) 그 계약까지 여기서 검사한다.
 *
 * **검사하는 것은 "어느 화면이 열리는가"다.** 뷰 내부 동작은 각 뷰의 테스트가
 * 담당한다 — 여기서 그것까지 보면 셸이 깨졌을 때 뷰 테스트도 같이 붉어져
 * 원인을 가리기 어려워진다.
 */

const api = vi.hoisted(() => ({
  me: vi.fn(),
  setAuthToken: vi.fn(),
  getAuthToken: vi.fn(() => null),
  listRooms: vi.fn(() => Promise.resolve({ ok: true as const, data: { rooms: [] } })),
  listFriends: vi.fn(() => Promise.resolve({ ok: true as const, data: { friends: [] } })),
  listMessages: vi.fn(() => Promise.resolve({ ok: true as const, data: { messages: [] } })),
  markRead: vi.fn(() => Promise.resolve({ ok: true as const, data: { last_read_seq: 0 } })),
  login: vi.fn(),
  signup: vi.fn(),
  searchUser: vi.fn(),
  addFriend: vi.fn(),
  updateAlias: vi.fn(),
  createRoom: vi.fn(),
  getRoom: vi.fn(),
  setAiCheck: vi.fn(),
  sendMessage: vi.fn(),
  judgmentAction: vi.fn(),
  reportMisdirect: vi.fn(),
}))

vi.mock('./lib/apiClient', () => api)

// WebSocket은 셸이 여는 것이 맞지만(FR-5.1) jsdom에 실물이 없다. 연결 자체는
// `wsClient.test.ts`가 검증하므로 여기서는 호출만 삼킨다.
const ws = vi.hoisted(() => ({
  connect: vi.fn(),
  disconnect: vi.fn(),
}))

vi.mock('./lib/wsClient', () => ws)

const ME: CurrentUser = { id: 1, username: 'alice' }

/** 로그인 상태로 만든다. 토큰이 있으면 셸이 비공개 화면을 그린다. */
function signedIn(user: CurrentUser | null = ME) {
  useChatStore.setState({ auth: { token: 'tok', user } })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.me.mockResolvedValue({ ok: true as const, data: ME })
  // 로그아웃 상태에서 시작한다. 각 테스트가 필요하면 `signedIn()`으로 올린다.
  useChatStore.setState({
    auth: { token: null, user: null },
    rooms: [],
    friends: [],
    unread: {},
    currentRoomId: null,
    messages: [],
    toasts: [],
    pending: [],
    notice: null,
  })
})

afterEach(cleanup)

describe('셸 마운트', () => {
  it('마운트되고 제목을 보여준다', () => {
    render(<App />)

    expect(screen.getByTestId('app-shell')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'career-jikimi' })).toBeInTheDocument()
  })
})

describe('로그아웃 상태', () => {
  it('로그인 화면을 그리고 비공개 화면의 네비게이션을 숨긴다', () => {
    render(<App />)

    expect(screen.getByTestId('view-auth')).toBeInTheDocument()
    // **네비게이션이 아예 없어야 한다.** 보이면 누를 수 있고, 누르면 401이 난다.
    for (const id of ['rooms', 'chat', 'friends']) {
      expect(screen.queryByTestId(`nav-${id}`)).not.toBeInTheDocument()
    }
  })

  it('로그아웃 버튼과 사용자 이름을 보여주지 않는다', () => {
    render(<App />)

    expect(screen.queryByTestId('sign-out')).not.toBeInTheDocument()
    expect(screen.queryByTestId('session-user')).not.toBeInTheDocument()
  })

  it('토큰이 없으면 `GET /auth/me`를 부르지 않는다', () => {
    // 부르면 보나마나 401이고, 그 401이 로그를 오염시킨다.
    render(<App />)

    expect(api.me).not.toHaveBeenCalled()
  })

  it('토큰이 없으면 WebSocket을 열지 않는다', () => {
    render(<App />)

    expect(ws.connect).not.toHaveBeenCalled()
  })
})

describe('부팅 시 세션 복구', () => {
  it('저장된 토큰이 유효하면 사용자를 채우고 방 목록으로 보낸다', async () => {
    // **이것이 없으면 새로고침이 로그인 폼을 보여준다** — 토큰은 살아 있는데 뷰가
    // `auth`로 리셋되기 때문이다. 사용자는 방금 로그인했는데 튕겼다고 느낀다.
    signedIn(null)
    render(<App />)

    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())
    expect(api.me).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('session-user')).toHaveTextContent('alice')
  })

  it('토큰이 만료되었으면(401) 토큰을 지우고 로그인 화면에 머문다', async () => {
    signedIn(null)
    api.me.mockResolvedValue({
      ok: false as const,
      error: { code: 'INVALID_TOKEN', message: '유효하지 않은 토큰입니다', status: 401 },
    })

    render(<App />)

    await waitFor(() => expect(useChatStore.getState().auth.token).toBeNull())
    expect(screen.getByTestId('view-auth')).toBeInTheDocument()
  })

  it('네트워크 오류에는 토큰을 지우지 않는다', async () => {
    // 서버가 잠깐 죽은 것과 토큰이 죽은 것은 다르다. 전자에서 로그아웃시키면
    // 서버가 돌아와도 다시 로그인해야 한다.
    signedIn(null)
    api.me.mockResolvedValue({
      ok: false as const,
      error: { code: 'NETWORK', message: '연결할 수 없습니다', status: 0 },
    })

    render(<App />)

    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())
    expect(useChatStore.getState().auth.token).toBe('tok')
    // 이름은 비어 있지만 나머지는 동작한다 — "불러오는 중"을 영원히 띄우지 않는다.
    expect(screen.queryByTestId('session-user')).not.toBeInTheDocument()
  })

  it('토큰이 있으면 WebSocket을 연다', async () => {
    signedIn()
    render(<App />)

    await waitFor(() => expect(ws.connect).toHaveBeenCalledWith('tok'))
  })
})

describe('로그인 상태의 뷰 전환', () => {
  it('세 화면의 네비게이션을 보여주고 현재 화면만 표시한다', async () => {
    signedIn()
    render(<App />)

    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())

    for (const id of ['rooms', 'chat', 'friends']) {
      expect(screen.getByTestId(`nav-${id}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('nav-rooms')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByTestId('nav-chat')).not.toHaveAttribute('aria-current')
  })

  it('버튼을 누르면 그 화면으로 바뀌고 이전 화면은 사라진다', async () => {
    // 남으면 뷰가 겹쳐 렌더되고 WebSocket 구독이 둘로 늘어난다.
    const user = userEvent.setup()
    signedIn()
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())

    await user.click(screen.getByTestId('nav-friends'))

    expect(screen.getByTestId('view-friends')).toBeInTheDocument()
    expect(screen.queryByTestId('view-rooms')).not.toBeInTheDocument()
    expect(
      screen.getAllByRole('button').filter((button) => button.getAttribute('aria-current')),
    ).toHaveLength(1)
  })

  it('이미 열린 화면의 버튼을 다시 눌러도 그 화면에 머문다', async () => {
    // 경계 사례 — 같은 값으로 setState를 부르는 경로다. 깨지면 사용자가 현재 탭을
    // 다시 눌렀을 때 화면이 사라진다.
    const user = userEvent.setup()
    signedIn()
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())

    await user.click(screen.getByTestId('nav-rooms'))
    await user.click(screen.getByTestId('nav-rooms'))

    expect(screen.getByTestId('view-rooms')).toBeInTheDocument()
    expect(screen.getByTestId('nav-rooms')).toHaveAttribute('aria-current', 'page')
  })

  it('대화 화면은 방을 고르지 않았을 때 어디서 고르는지 알려준다', async () => {
    const user = userEvent.setup()
    signedIn()
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())

    await user.click(screen.getByTestId('nav-chat'))

    expect(screen.getByTestId('chat-no-room')).toHaveTextContent('채팅방 목록에서 방을 선택')
  })
})

describe('로그아웃', () => {
  it('토큰을 지우고 로그인 화면으로 돌아간다', async () => {
    const user = userEvent.setup()
    signedIn()
    render(<App />)
    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())

    await user.click(screen.getByTestId('sign-out'))

    expect(useChatStore.getState().auth.token).toBeNull()
    expect(screen.getByTestId('view-auth')).toBeInTheDocument()
    expect(screen.queryByTestId('nav-rooms')).not.toBeInTheDocument()
  })

  it('WebSocket을 끊는다', async () => {
    // 남겨두면 앞 사용자의 연결로 새 사용자의 메시지가 들어온다.
    const user = userEvent.setup()
    signedIn()
    render(<App />)
    await waitFor(() => expect(ws.connect).toHaveBeenCalled())

    await user.click(screen.getByTestId('sign-out'))

    await waitFor(() => expect(ws.disconnect).toHaveBeenCalled())
  })
})
