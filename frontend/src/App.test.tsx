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
  // 구현을 여기서 고정하지 않는다 — 빈 배열이 `never[]`로 굳어 방을 담아 돌려주는
  // 테스트가 타입에서 막힌다. 기본값은 아래 `beforeEach`가 매번 다시 준다.
  listRooms: vi.fn(),
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
  // **매번 다시 준다.** `clearAllMocks()`는 호출 기록만 지우고 구현은 남기므로,
  // 방을 담아 돌려주도록 바꾼 테스트가 뒤 테스트까지 오염시킨다.
  api.listRooms.mockResolvedValue({ ok: true as const, data: { rooms: [] } })
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
    for (const id of ['rooms', 'friends']) {
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
  it('두 화면의 네비게이션을 보여주고 현재 화면만 표시한다', async () => {
    signedIn()
    render(<App />)

    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())

    for (const id of ['rooms', 'friends']) {
      expect(screen.getByTestId(`nav-${id}`)).toBeInTheDocument()
    }
    expect(screen.getByTestId('nav-rooms')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByTestId('nav-friends')).not.toHaveAttribute('aria-current')
  })

  it('"대화" 탭이 없다 — 대화는 목록 위에 팝업으로 열린다', async () => {
    // 탭으로 두면 아무 방도 안 열린 빈 대화 화면이 존재하게 되고, 그 화면은
    // 사용자가 도달할 이유가 없는 상태다.
    signedIn()
    render(<App />)

    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())
    expect(screen.queryByTestId('nav-chat')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-overlay')).not.toBeInTheDocument()
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

})

describe('대화 팝업', () => {
  const ROOM = {
    id: 7,
    name: '개발 3팀',
    last_seq: 0,
    created_at: '2026-07-31T09:00:00Z',
    unread_count: 0,
    last_read_seq: 0,
    ai_check_enabled: true,
    members: [
      { user_id: 1, display_name: 'alice' },
      { user_id: 2, display_name: '서연 팀장님' },
    ],
  }

  /** 방 하나에 입장한 상태. 팝업을 여는 신호는 `currentRoomId` 하나다.
   *
   * **`listRooms`도 함께 돌려준다.** 목록 화면이 마운트되며 방 목록을 다시 불러와
   * `setRooms()`로 덮으므로, 기본 목(빈 배열)이면 심어둔 방이 지워지고 팝업이
   * "방을 선택하세요"로 떨어진다.
   */
  function inRoom() {
    signedIn()
    api.listRooms.mockResolvedValue({ ok: true as const, data: { rooms: [ROOM] } })
    useChatStore.setState({ rooms: [ROOM], currentRoomId: 7 })
  }

  it('방에 입장하면 목록 위에 팝업으로 열린다', async () => {
    inRoom()
    render(<App />)

    expect(await screen.findByTestId('chat-overlay')).toBeInTheDocument()
    expect(screen.getByTestId('chat-room-name')).toHaveTextContent('개발 3팀')
    // **목록은 그대로 있다.** 뷰를 바꾸는 것이 아니라 덮는 것이므로, 닫으면
    // 스크롤 위치까지 그대로인 목록으로 돌아온다.
    expect(screen.getByTestId('view-rooms')).toBeInTheDocument()
  })

  it('닫으면 포인터가 비워지고 팝업이 사라진다', async () => {
    const user = userEvent.setup()
    inRoom()
    render(<App />)
    await screen.findByTestId('chat-overlay')

    await user.click(screen.getByTestId('chat-close'))

    expect(useChatStore.getState().currentRoomId).toBeNull()
    expect(screen.queryByTestId('chat-overlay')).not.toBeInTheDocument()
    expect(screen.getByTestId('view-rooms')).toBeInTheDocument()
  })

  it('평소에는 뜨지 않는다 — 방을 누르면 새 창이 열린다', async () => {
    // 오버레이는 팝업이 차단됐을 때의 대체 경로다. 평소에도 뜨면 새 창과 같은 창에
    // 대화가 둘 열린다.
    signedIn()
    render(<App />)

    await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())
    expect(screen.queryByTestId('chat-overlay')).not.toBeInTheDocument()
  })

  it('로그아웃하면 방이 열려 있어도 팝업이 남지 않는다', async () => {
    // 남으면 다음 사용자의 화면에 앞 사용자의 대화가 그대로 보인다.
    const user = userEvent.setup()
    inRoom()
    render(<App />)
    await screen.findByTestId('chat-overlay')

    await user.click(screen.getByTestId('sign-out'))

    expect(screen.queryByTestId('chat-overlay')).not.toBeInTheDocument()
    expect(screen.getByTestId('view-auth')).toBeInTheDocument()
  })
})

describe('대화 전용 창 (?room=<id>)', () => {
  const ROOM = {
    id: 7,
    name: '개발 3팀',
    last_seq: 0,
    created_at: '2026-07-31T09:00:00Z',
    unread_count: 0,
    last_read_seq: 0,
    ai_check_enabled: true,
    members: [
      { user_id: 1, display_name: 'alice' },
      { user_id: 2, display_name: '서연 팀장님' },
    ],
  }

  /** 주소를 갈아끼운다. **반드시 되돌린다** — 남기면 뒤 테스트가 전부 대화 창이 된다. */
  function atRoomUrl(search: string) {
    const before = window.location.href
    window.history.replaceState({}, '', search)
    return () => window.history.replaceState({}, '', before)
  }

  it('대화 하나만 그린다 — 탭바도 상단 바도 없다', async () => {
    // 방 하나를 보는 창이라는 것이 이 창의 전부다. 탭바를 남기면 여기서 친구
    // 목록으로 갈 수 있게 되고 창의 목적이 흐려진다.
    const restore = atRoomUrl('/?room=7')
    try {
      signedIn()
      api.getRoom.mockResolvedValue({ ok: true as const, data: ROOM })
      render(<App />)

      expect(await screen.findByTestId('chat-window')).toBeInTheDocument()
      expect(screen.queryByTestId('nav-rooms')).not.toBeInTheDocument()
      expect(screen.queryByTestId('nav-friends')).not.toBeInTheDocument()
      expect(screen.queryByTestId('sign-out')).not.toBeInTheDocument()
    } finally {
      restore()
    }
  })

  it('방을 직접 불러온다 — 이 창에는 목록이 없다', async () => {
    // `enterRoom()`은 포인터와 히스토리만 다룬다. 방 자체(이름·참여자·내 토글)는
    // 목록 화면이 채우던 값이라, 이 조회가 없으면 `ChatView`가 방을 찾지 못해
    // 대화 창인데 대화가 없는 화면이 된다.
    const restore = atRoomUrl('/?room=7')
    try {
      signedIn()
      api.getRoom.mockResolvedValue({ ok: true as const, data: ROOM })
      render(<App />)

      await waitFor(() => expect(useChatStore.getState().currentRoomId).toBe(7))
      expect(api.getRoom).toHaveBeenCalledWith(7)
      expect(screen.getByTestId('chat-room-name')).toHaveTextContent('개발 3팀')
      // 방 서른 개인 사용자의 창 하나를 여는 데 서른 개를 받아올 이유가 없다.
      expect(api.listRooms).not.toHaveBeenCalled()
    } finally {
      restore()
    }
  })

  it('참여자가 아니면 이유를 보여준다 — 빈 대화로 두지 않는다', async () => {
    // 없는 방이거나 남의 방이면 403이다 (BR-3.3). 주소를 손으로 고친 경우가
    // 그렇고, 빈 대화로 두면 원인이 화면 어디에도 없다.
    const restore = atRoomUrl('/?room=7')
    try {
      signedIn()
      api.getRoom.mockResolvedValue({
        ok: false as const,
        error: { code: 'FORBIDDEN', message: '이 방에 접근할 권한이 없습니다', status: 403 },
      })
      render(<App />)

      expect(await screen.findByTestId('room-window-error')).toHaveTextContent(
        '이 방에 접근할 권한이 없습니다',
      )
      expect(screen.queryByTestId('chat-window')).not.toBeInTheDocument()
    } finally {
      restore()
    }
  })

  it('방 id가 아닌 값이면 보통의 앱 창으로 떨어진다', async () => {
    // 주소는 사용자가 고칠 수 있다. 그대로 믿으면 빈 대화 창에 갇힌다.
    const restore = atRoomUrl('/?room=abc')
    try {
      signedIn()
      render(<App />)

      await waitFor(() => expect(screen.getByTestId('view-rooms')).toBeInTheDocument())
      expect(screen.queryByTestId('chat-window')).not.toBeInTheDocument()
      expect(screen.getByTestId('nav-rooms')).toBeInTheDocument()
    } finally {
      restore()
    }
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
