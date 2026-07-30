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

  it('AI 토글은 보이는 라벨이 붙은 진짜 체크박스다 (FR-6.1)', async () => {
    const user = userEvent.setup()
    signedIn([room({ id: 9, ai_check_enabled: true })])
    api.setAiCheck.mockResolvedValue({ ok: true, data: { ai_check_enabled: false } })
    render(<RoomListView />)

    // 방에 입장해야 그 방의 개인 설정이 보인다. 항목 안의 버튼을 누른다 —
    // 각 항목이 링크 또는 버튼이어야 한다는 접근성 요구가 여기서도 확인된다.
    await user.click(within(await screen.findByTestId('room-list-item-9')).getByRole('button'))

    const toggle = await screen.findByTestId('room-ai-toggle')
    // div로 만들면 키보드로 조작할 수 없고 스크린리더가 상태를 읽지 못한다.
    expect(toggle).toHaveAttribute('type', 'checkbox')
    expect(toggle).toBeChecked()
    expect(screen.getByLabelText('이 방에서 AI 검증 사용')).toBe(toggle)

    await user.click(toggle)

    await waitFor(() => {
      expect(api.setAiCheck).toHaveBeenCalledWith(9, false)
    })
    expect(await screen.findByTestId('room-ai-toggle')).not.toBeChecked()
  })

  it('토글 변경이 실패하면 원래 상태로 되돌린다', async () => {
    // 낙관적으로 바꾼 뒤 실패를 무시하면 화면과 서버가 어긋난 채로 남는다.
    const user = userEvent.setup()
    signedIn([room({ id: 9, ai_check_enabled: true })])
    api.setAiCheck.mockResolvedValue({
      ok: false,
      error: { code: 'FORBIDDEN', message: '이 방에 접근할 권한이 없습니다', status: 403 },
    })
    render(<RoomListView />)

    await user.click(within(await screen.findByTestId('room-list-item-9')).getByRole('button'))
    await user.click(await screen.findByTestId('room-ai-toggle'))

    expect(await screen.findByTestId('rooms-error')).toHaveTextContent(
      '이 방에 접근할 권한이 없습니다',
    )
    expect(screen.getByTestId('room-ai-toggle')).toBeChecked()
  })

  it('방에 입장하면 배지가 사라진다 (FR-5.2의 둘째 기준)', async () => {
    const user = userEvent.setup()
    signedIn([room({ id: 9, unread_count: 2, last_seq: 2 })])
    render(<RoomListView />)

    expect(await screen.findByTestId('room-unread-badge-9')).toBeInTheDocument()
    await user.click(within(screen.getByTestId('room-list-item-9')).getByRole('button'))

    await waitFor(() => {
      expect(screen.queryByTestId('room-unread-badge-9')).not.toBeInTheDocument()
    })
    // 서버의 읽음 위치도 함께 전진시킨다 — 그러지 않으면 목록을 다시 부를 때 되살아난다.
    expect(api.markRead).toHaveBeenCalledWith(9, 2)
  })
})

describe('방 진입과 화면 전환', () => {
  it('방을 누르면 `onOpenRoom`을 그 방 id로 부른다', async () => {
    // **이것이 없으면 방을 눌러도 목록에 머문다.** 사용자가 "대화" 탭을 따로 눌러야
    // 하고, 방을 여는 것이 이 앱의 주 동작이다.
    const user = userEvent.setup()
    const onOpenRoom = vi.fn()
    signedIn([room({ id: 12 })])
    render(<RoomListView onOpenRoom={onOpenRoom} />)

    await user.click(within(await screen.findByTestId('room-list-item-12')).getByRole('button'))

    expect(onOpenRoom).toHaveBeenCalledWith(12)
  })

  it('입장 처리가 실패해도 화면은 열린다', async () => {
    // 히스토리 조회는 U5 소관이고 실패할 수 있다. 그때 화면이 안 열리면 사용자는
    // 목록에 갇힌 채 아무 설명도 못 받는다 — 대화 화면이 자기 오류 상태를 그리는
    // 편이 낫다. 구현에서 `void enterRoom()`과 `onOpenRoom()`이 나란히 있는 이유다.
    const user = userEvent.setup()
    const onOpenRoom = vi.fn()
    const enterRoom = vi.fn(() => Promise.reject(new Error('히스토리 조회 실패')))
    // 스토어의 액션을 바꿔치우므로 **반드시 되돌린다.** `beforeEach`는 데이터 키만
    // 초기화하고 액션은 손대지 않아, 남겨두면 뒤 테스트가 이 목을 쓴다.
    const realEnterRoom = useChatStore.getState().enterRoom
    signedIn([room({ id: 13 })])
    useChatStore.setState({ enterRoom })
    try {
      render(<RoomListView onOpenRoom={onOpenRoom} />)

      await user.click(within(await screen.findByTestId('room-list-item-13')).getByRole('button'))

      expect(enterRoom).toHaveBeenCalledWith(13)
      expect(onOpenRoom).toHaveBeenCalledWith(13)
    } finally {
      useChatStore.setState({ enterRoom: realEnterRoom })
    }
  })

  it('콜백을 주지 않아도 입장 자체는 동작한다', async () => {
    // 옵셔널 프로퍼티다 — 없을 때 터지면 이 뷰를 다른 자리에 재사용할 수 없다.
    const user = userEvent.setup()
    signedIn([room({ id: 14 })])
    render(<RoomListView />)

    await user.click(within(await screen.findByTestId('room-list-item-14')).getByRole('button'))

    await waitFor(() => expect(useChatStore.getState().currentRoomId).toBe(14))
  })
})
