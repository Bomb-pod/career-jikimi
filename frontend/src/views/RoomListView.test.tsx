import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import RoomListView from './RoomListView'
import type { RoomSummary } from '../lib/apiClient'
import { useChatStore } from '../store/chatStore'

/**
 * `RoomListView` — FR-3.1·FR-3.2·FR-5.2·FR-6.1의 UI 쪽 계약.
 *
 * 여기서 확인하는 것 중 눈에 잘 띄지 않는 두 가지:
 *   - **배지는 0이면 아예 없다.** "0"이 붙어 있으면 사용자가 그것을 읽고 판단해야 한다.
 *   - **AI 토글은 진짜 체크박스다.** div로 만들면 키보드로 조작할 수 없고 스크린리더가
 *     상태를 읽지 못한다.
 */

const api = vi.hoisted(() => ({
  listRooms: vi.fn(),
  listFriends: vi.fn(),
  createRoom: vi.fn(),
  getRoom: vi.fn(),
  markRead: vi.fn(() => Promise.resolve({ ok: true, data: { last_read_seq: 0 } })),
  setAiCheck: vi.fn(),
  setAuthToken: vi.fn(),
  getAuthToken: vi.fn(() => null),
}))

vi.mock('../lib/apiClient', () => ({
  ...api,
  ApiTransportError: class ApiTransportError extends Error {},
}))

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

/** 로그인된 상태로 맞춘다. 토큰이 없으면 이 화면은 아무것도 요청하지 않는다. */
function signedIn(rooms: RoomSummary[] = [], friends: Array<Record<string, unknown>> = []) {
  useChatStore.setState({
    auth: { token: 'jwt-token', user: { id: 1, username: 'alice' } },
    rooms,
    unread: Object.fromEntries(rooms.map((item) => [item.id, item.unread_count])),
    friends: friends as never,
    currentRoomId: null,
    messages: [],
    toasts: [],
    sessionReplaced: false,
    wsStatus: 'open',
  })
  api.listRooms.mockResolvedValue({ ok: true, data: { rooms } })
  api.listFriends.mockResolvedValue({ ok: true, data: { friends } })
}

beforeEach(() => {
  vi.clearAllMocks()
  api.listRooms.mockResolvedValue({ ok: true, data: { rooms: [] } })
  api.listFriends.mockResolvedValue({ ok: true, data: { friends: [] } })
  useChatStore.setState({
    auth: { token: null, user: null },
    rooms: [],
    unread: {},
    friends: [],
    currentRoomId: null,
    messages: [],
    toasts: [],
    sessionReplaced: false,
    wsStatus: 'idle',
  })
})

afterEach(cleanup)

describe('RoomListView 목록', () => {
  it('입장 시 방 목록을 불러와 리스트 시맨틱으로 렌더한다', async () => {
    // 스토어는 비어 있고 응답에만 항목이 있다 — 화면이 실제로 fetch해 반영하는지를 본다.
    signedIn()
    api.listRooms.mockResolvedValue({
      ok: true,
      data: { rooms: [room({ id: 4, name: '점심 약속' })] },
    })
    render(<RoomListView />)

    expect(await screen.findByTestId('room-list-item-4')).toHaveTextContent('점심 약속')
    // `<ul>`/`<li>` — 스크린리더가 "목록, 항목 n개"를 읽는다.
    expect(screen.getByTestId('room-list').tagName).toBe('UL')
    expect(screen.getByTestId('room-list-item-4').tagName).toBe('LI')
  })

  it('이름이 없는 방은 참여자 표시명으로 조립하고 본인을 뺀다', async () => {
    // 3명까지 나열하고 넘으면 `외 N명`. 본인을 넣으면 모든 방 이름이 내 이름으로
    // 시작해 구별에 기여하지 않는다.
    signedIn([
      room({
        id: 5,
        name: null,
        members: [
          { user_id: 1, display_name: 'alice' },
          { user_id: 2, display_name: '회사 김대리' },
          { user_id: 3, display_name: '동아리 후배' },
          { user_id: 4, display_name: '동생' },
          { user_id: 5, display_name: '사촌' },
        ],
      }),
    ])
    render(<RoomListView />)

    const item = await screen.findByTestId('room-list-item-5')
    expect(item).toHaveTextContent('회사 김대리, 동아리 후배, 동생 외 1명')
    expect(item.textContent).not.toContain('alice')
  })

  it('배지는 0이면 표시하지 않고, 있으면 무엇의 개수인지 알린다', async () => {
    signedIn([room({ id: 6, unread_count: 3 }), room({ id: 7, unread_count: 0 })])
    render(<RoomListView />)

    const badge = await screen.findByTestId('room-unread-badge-6')
    expect(badge).toHaveTextContent('3')
    // 숫자만 두면 스크린리더가 "3"만 읽어 무엇의 3인지 알 수 없다.
    expect(badge).toHaveAttribute('aria-label', '안 읽은 메시지 3개')
    expect(screen.queryByTestId('room-unread-badge-7')).not.toBeInTheDocument()
  })

  it('방이 없으면 무엇을 해야 하는지 알려준다', async () => {
    // 빈 상태를 방치하면 "왜 아무것도 안 나오지"가 된다.
    signedIn()
    render(<RoomListView />)

    // 두 문장을 각각 확인한다 — 재디자인이 `<br>`로 줄을 나눠 정확 일치가 깨졌다.
    // 문구 자체는 그대로이며, 여기서 지키는 것은 "무엇을 해야 하는지 알려주는가"다.
    const empty = await screen.findByTestId('rooms-empty')
    expect(empty).toHaveTextContent('채팅방이 없습니다')
    expect(empty).toHaveTextContent('친구를 초대해 만들어보세요')
    expect(screen.queryByTestId('room-list')).not.toBeInTheDocument()
  })

  it('로그인하지 않았으면 목록을 요청하지 않는다', () => {
    render(<RoomListView />)

    expect(api.listRooms).not.toHaveBeenCalled()
    expect(screen.queryByTestId('room-create-open')).not.toBeInTheDocument()
  })
})

describe('RoomListView 생성', () => {
  const FRIENDS = [
    { id: 10, friend_user_id: 2, alias: '회사 김대리' },
    { id: 11, friend_user_id: 3, alias: '동아리 후배' },
  ]

  it('친구를 여러 명 골라 방을 만든다 (FR-3.1)', async () => {
    const user = userEvent.setup()
    signedIn([], FRIENDS)
    api.createRoom.mockResolvedValue({
      ok: true,
      data: {
        id: 8,
        name: '스터디',
        last_seq: 0,
        created_at: '2026-07-30T00:00:00Z',
        members: [],
        ai_check_enabled: true,
        last_read_seq: 0,
      },
    })
    render(<RoomListView />)

    await user.click(await screen.findByTestId('room-create-open'))
    await user.click(screen.getByTestId('room-create-friend-2'))
    await user.click(screen.getByTestId('room-create-friend-3'))
    await user.type(screen.getByTestId('room-create-name'), '스터디')
    await user.click(screen.getByTestId('room-create-submit'))

    await waitFor(() => {
      expect(api.createRoom).toHaveBeenCalledWith([2, 3], '스터디')
    })
    // 생성 응답이 그 방의 최신 상태를 준다 — 목록을 다시 부르지 않고 반영한다.
    expect(await screen.findByTestId('room-list-item-8')).toHaveTextContent('스터디')
  })

  it('아무도 고르지 않으면 만들기 버튼이 비활성 상태다 (BR-3.1)', async () => {
    // **오류 메시지보다 나은 오류 예방** — 누를 수 없으면 400을 받을 일이 없다.
    const user = userEvent.setup()
    signedIn([], FRIENDS)
    render(<RoomListView />)

    await user.click(await screen.findByTestId('room-create-open'))

    expect(screen.getByTestId('room-create-submit')).toBeDisabled()
    await user.click(screen.getByTestId('room-create-friend-2'))
    expect(screen.getByTestId('room-create-submit')).not.toBeDisabled()
  })

  it('방 이름을 비우면 null로 보낸다', async () => {
    // 빈 문자열을 보내면 이름이 있는 방이 되어 화면이 참여자 이름으로 조립하지 않는다.
    const user = userEvent.setup()
    signedIn([], FRIENDS)
    api.createRoom.mockResolvedValue({ ok: false, error: { code: 'X', message: 'x', status: 400 } })
    render(<RoomListView />)

    await user.click(await screen.findByTestId('room-create-open'))
    await user.click(screen.getByTestId('room-create-friend-2'))
    await user.click(screen.getByTestId('room-create-submit'))

    await waitFor(() => {
      expect(api.createRoom).toHaveBeenCalledWith([2], null)
    })
  })

  it('서버 오류 문구를 그대로 보여준다', async () => {
    const user = userEvent.setup()
    signedIn([], FRIENDS)
    api.createRoom.mockResolvedValue({
      ok: false,
      error: {
        code: 'NOT_A_FRIEND',
        message: '친구로 등록한 사용자만 초대할 수 있습니다',
        status: 400,
      },
    })
    render(<RoomListView />)

    await user.click(await screen.findByTestId('room-create-open'))
    await user.click(screen.getByTestId('room-create-friend-2'))
    await user.click(screen.getByTestId('room-create-submit'))

    expect(await screen.findByTestId('rooms-error')).toHaveTextContent(
      '친구로 등록한 사용자만 초대할 수 있습니다',
    )
  })

  it('친구가 없으면 먼저 등록하라고 안내한다', async () => {
    // BR-3.2 — 친구가 아닌 사용자는 초대할 수 없다. 빈 선택 목록만 보여주면
    // 사용자는 왜 아무도 없는지 알 수 없다.
    const user = userEvent.setup()
    signedIn()
    render(<RoomListView />)

    await user.click(await screen.findByTestId('room-create-open'))

    expect(screen.getByTestId('room-create-no-friends')).toBeInTheDocument()
    expect(screen.getByTestId('room-create-submit')).toBeDisabled()
  })
})

describe('RoomListView 배너와 토글', () => {
  it('session_replaced 배너를 status로 알린다 (BR-5.5)', async () => {
    // 밀려난 탭은 재연결하지 않으므로 이 문구가 유일한 안내다. 전송은 HTTP라
    // 여전히 동작한다 — 그래서 "죽었다"가 아니라 "새로고침하라"다.
    signedIn()
    useChatStore.setState({ sessionReplaced: true })
    render(<RoomListView />)

    const banner = await screen.findByTestId('session-replaced-banner')
    expect(banner).toHaveTextContent(
      '다른 탭에서 접속했습니다 — 이 탭에서 계속하려면 새로고침하세요',
    )
    expect(banner).toHaveAttribute('role', 'status')
  })

  it('재연결 중임을 화면에 표시한다', async () => {
    // 조용히 끊긴 채로 두면 사용자는 새 메시지가 오지 않는 이유를 알 수 없다.
    signedIn()
    useChatStore.setState({ wsStatus: 'reconnecting' })
    render(<RoomListView />)

    expect(await screen.findByTestId('ws-reconnecting-banner')).toBeInTheDocument()
  })

  it('AI 검증 토글을 그리지 않는다 (설정 팝업이 유일한 자리다)', async () => {
    // 같은 개인 설정이 목록과 대화 두 곳에 있으면 사용자가 어느 쪽이 진짜인지
    // 확인하려 들고, 한쪽만 고쳐지는 날 두 화면이 서로 다른 상태를 보여준다.
    // 토글은 `RoomSettingsDialog` 안에만 있다 — 그쪽 테스트가 동작을 지킨다.
    const user = userEvent.setup()
    signedIn([room({ id: 9, ai_check_enabled: true })])
    render(<RoomListView />)

    await user.click(within(await screen.findByTestId('room-list-item-9')).getByRole('button'))

    expect(screen.queryByTestId('room-ai-toggle')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('이 방에서 AI 검증 사용')).not.toBeInTheDocument()
    expect(api.setAiCheck).not.toHaveBeenCalled()
  })

  it('방을 열면 이 창의 배지가 사라진다 (FR-5.2의 둘째 기준)', async () => {
    // 읽는 것은 새 창이고 서버의 `last_read_seq`도 그쪽이 전진시키지만, 목록 창의
    // 배지는 자기 상태라 아무도 지워주지 않는다 — 남겨두면 방을 열어놓고도 안 읽은
    // 것으로 보인다.
    const user = userEvent.setup()
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() } as unknown as Window)
    signedIn([room({ id: 9, unread_count: 2, last_seq: 2 })])
    render(<RoomListView />)

    expect(await screen.findByTestId('room-unread-badge-9')).toBeInTheDocument()
    await user.click(within(screen.getByTestId('room-list-item-9')).getByRole('button'))

    await waitFor(() => {
      expect(screen.queryByTestId('room-unread-badge-9')).not.toBeInTheDocument()
    })
    // **이 창은 방에 들어가지 않는다.** 목록과 대화를 나란히 보는 것이 새 창의 목적이다.
    expect(useChatStore.getState().currentRoomId).toBeNull()

    open.mockRestore()
  })
})

describe('방 진입', () => {
  it('방을 누르면 새 **창**으로 연다 — 탭이 아니다', async () => {
    // 목록과 대화를 나란히 보는 것이 이 기능의 목적이다. 창 크기를 주지 않으면
    // 브라우저가 탭으로 열고, 그러면 목록이 가려져 목적이 사라진다.
    const user = userEvent.setup()
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() } as unknown as Window)
    signedIn([room({ id: 12 })])
    render(<RoomListView />)

    await user.click(within(await screen.findByTestId('room-list-item-12')).getByRole('button'))

    expect(open).toHaveBeenCalledTimes(1)
    const [url, name, features] = open.mock.calls[0] ?? []
    expect(url).toBe('/?room=12')
    // 방마다 이름이 달라야 여러 방을 나란히 띄울 수 있다.
    expect(name).toBe('career-jikimi-room-12')
    expect(features).toContain('popup=yes')
    expect(features).toMatch(/width=\d+/)
    expect(features).toMatch(/height=\d+/)
    // 이 창은 목록으로 남는다.
    expect(useChatStore.getState().currentRoomId).toBeNull()

    open.mockRestore()
  })

  it('팝업이 차단되면 같은 창에서 연다', async () => {
    // `window.open()`이 `null`을 주는 유일한 경우다. 차단된 것을 모른 채 아무 일도
    // 일어나지 않는 화면이 가장 나쁘다 — 그때는 셸이 목록 위에 대화를 덮는다.
    const user = userEvent.setup()
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    signedIn([room({ id: 12 })])
    render(<RoomListView />)

    await user.click(within(await screen.findByTestId('room-list-item-12')).getByRole('button'))

    await waitFor(() => expect(useChatStore.getState().currentRoomId).toBe(12))

    open.mockRestore()
  })

  it('팝업 차단 시 히스토리 조회가 실패해도 포인터는 옮겨간다', async () => {
    // 히스토리 조회는 U5 소관이고 실패할 수 있다. 그때 포인터가 안 움직이면
    // 대화가 열리지 않아 사용자는 목록에 갇힌 채 아무 설명도 못 받는다 — 대화
    // 화면이 자기 오류 상태를 그리는 편이 낫다. 구현이 `void enterRoom()`으로
    // 결과를 기다리지 않는 이유다.
    const user = userEvent.setup()
    const open = vi.spyOn(window, 'open').mockReturnValue(null)
    const enterRoom = vi.fn(() => Promise.reject(new Error('히스토리 조회 실패')))
    // 스토어의 액션을 바꿔치우므로 **반드시 되돌린다.** `beforeEach`는 데이터 키만
    // 초기화하고 액션은 손대지 않아, 남겨두면 뒤 테스트가 이 목을 쓴다.
    const realEnterRoom = useChatStore.getState().enterRoom
    signedIn([room({ id: 13 })])
    useChatStore.setState({ enterRoom })
    try {
      render(<RoomListView />)

      await user.click(within(await screen.findByTestId('room-list-item-13')).getByRole('button'))

      expect(enterRoom).toHaveBeenCalledWith(13)
    } finally {
      useChatStore.setState({ enterRoom: realEnterRoom })
      open.mockRestore()
    }
  })
})
