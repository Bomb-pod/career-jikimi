import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import FriendsView from './FriendsView'
import { useChatStore } from '../store/chatStore'

/**
 * `FriendsView` — FR-2.1~FR-2.4의 UI 쪽 계약.
 *
 * 이 파일에서 가장 중요한 테스트는 **목록에 상대의 `display_name`이 나타나지 않는다**
 * (FR-2.4)다. `apiClient`의 `Friend` 타입에 그 필드가 없어 타입 검사가 이미 막지만,
 * 서버 응답에는 실려 올 수 있으므로 화면이 그것을 그리지 않는지 실제로 확인한다.
 */

const api = vi.hoisted(() => ({
  signup: vi.fn(),
  login: vi.fn(),
  searchUser: vi.fn(),
  listFriends: vi.fn(),
  addFriend: vi.fn(),
  updateAlias: vi.fn(),
  setAuthToken: vi.fn(),
  getAuthToken: vi.fn(() => null),
}))

vi.mock('../lib/apiClient', () => ({
  ...api,
  ApiTransportError: class ApiTransportError extends Error {},
}))

const ALIAS = '회사 김대리'

/**
 * 로그인된 상태로 스토어를 맞춘다 — 토큰이 없으면 이 화면은 목록을 요청하지 않는다.
 *
 * `listFriends`의 응답도 같은 목록으로 맞춘다. 화면이 마운트 직후 목록을 다시
 * 불러오므로, 여기서 맞추지 않으면 미리 심은 목록이 빈 응답으로 덮인다.
 */
function signedIn(friends: Array<Record<string, unknown>> = []) {
  useChatStore.setState({
    auth: { token: 'jwt-token', user: { id: 1, username: 'alice' } },
    // 서버 응답에 없는 필드가 섞여 있어도 화면이 그것을 그리지 않아야 한다.
    friends: friends as never,
  })
  api.listFriends.mockResolvedValue({ ok: true, data: { friends } })
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  api.listFriends.mockResolvedValue({ ok: true, data: { friends: [] } })
  useChatStore.setState({ auth: { token: null, user: null }, friends: [] })
})

afterEach(cleanup)

describe('FriendsView 검색', () => {
  it('정확 일치 결과 한 명을 별칭 입력칸과 함께 보여준다', async () => {
    // 별칭 입력칸이 **결과 안에** 있어야 한다 — "추가"를 누른 뒤 묻는 2단계로 만들면
    // 사용자가 별칭이 필수라는 것을 누른 다음에야 알게 된다.
    const user = userEvent.setup()
    api.searchUser.mockResolvedValue({ ok: true, data: { user: { id: 2, username: 'bob' } } })
    signedIn()
    render(<FriendsView />)

    await user.type(screen.getByTestId('friends-search-input'), 'bob')
    await user.click(screen.getByTestId('friends-search-submit'))

    expect(await screen.findByTestId('friends-search-result')).toHaveTextContent('bob')
    expect(screen.getByTestId('friends-add-alias-input')).toBeInTheDocument()
    expect(api.searchUser).toHaveBeenCalledWith('bob')
  })

  it('결과가 없으면 오류가 아니라 안내 문구를 보여준다', async () => {
    // BR-2.1 — 검색은 성공했고 결과가 비었을 뿐이다. 서버가 200 + null을 준다.
    const user = userEvent.setup()
    api.searchUser.mockResolvedValue({ ok: true, data: { user: null } })
    signedIn()
    render(<FriendsView />)

    await user.type(screen.getByTestId('friends-search-input'), 'ali')
    await user.click(screen.getByTestId('friends-search-submit'))

    expect(await screen.findByTestId('friends-search-empty')).toBeInTheDocument()
    // 오류 영역은 비어 있다 — 결과 없음을 오류로 표시하지 않는다.
    expect(screen.getByTestId('friends-error')).toBeEmptyDOMElement()
    expect(screen.queryByTestId('friends-add-alias-input')).not.toBeInTheDocument()
  })

  it('검색 결과 개수를 스크린리더에 알린다', async () => {
    // 결과가 0명일 때는 화면에 카드가 생기지 않아 변화가 announce되지 않는다.
    const user = userEvent.setup()
    api.searchUser.mockResolvedValue({ ok: true, data: { user: { id: 2, username: 'bob' } } })
    signedIn()
    render(<FriendsView />)

    expect(screen.getByTestId('friends-search-status')).toBeEmptyDOMElement()

    await user.type(screen.getByTestId('friends-search-input'), 'bob')
    await user.click(screen.getByTestId('friends-search-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('friends-search-status')).toHaveTextContent('1명 찾음')
    })
    expect(screen.getByTestId('friends-search-status')).toHaveAttribute('aria-live', 'polite')
  })
})

describe('FriendsView 등록', () => {
  async function searchForBob(user: ReturnType<typeof userEvent.setup>) {
    api.searchUser.mockResolvedValue({ ok: true, data: { user: { id: 2, username: 'bob' } } })
    await user.type(screen.getByTestId('friends-search-input'), 'bob')
    await user.click(screen.getByTestId('friends-search-submit'))
    await screen.findByTestId('friends-add-alias-input')
  }

  it('별칭이 비어 있으면 추가 버튼이 비활성화된다', async () => {
    // **오류 메시지보다 나은 오류 예방이다.** 누를 수 없으면 400을 받을 일이 없다.
    const user = userEvent.setup()
    signedIn()
    render(<FriendsView />)
    await searchForBob(user)

    expect(screen.getByTestId('friends-add-submit')).toBeDisabled()
    // 이유를 스크린리더에도 전달한다.
    expect(screen.getByTestId('friends-add-submit')).toHaveAttribute('aria-describedby')

    await user.type(screen.getByTestId('friends-add-alias-input'), ALIAS)
    expect(screen.getByTestId('friends-add-submit')).not.toBeDisabled()
  })

  it('공백만 입력해도 추가 버튼이 비활성 상태로 남는다', async () => {
    // BR-2.2의 트림 규칙이 화면에서도 같아야 한다. 여기서 눌릴 수 있으면 사용자는
    // 400을 받고 나서야 공백이 이름이 아니라는 것을 알게 된다.
    const user = userEvent.setup()
    signedIn()
    render(<FriendsView />)
    await searchForBob(user)

    await user.type(screen.getByTestId('friends-add-alias-input'), '   ')

    expect(screen.getByTestId('friends-add-submit')).toBeDisabled()
    expect(api.addFriend).not.toHaveBeenCalled()
  })

  it('추가에 성공하면 목록이 즉시 갱신되고 검색 결과가 사라진다', async () => {
    const user = userEvent.setup()
    api.addFriend.mockResolvedValue({
      ok: true,
      data: { id: 10, friend_user_id: 2, alias: ALIAS },
    })
    signedIn()
    render(<FriendsView />)
    await searchForBob(user)

    await user.type(screen.getByTestId('friends-add-alias-input'), ALIAS)
    await user.click(screen.getByTestId('friends-add-submit'))

    expect(await screen.findByTestId('friends-list-item-10')).toHaveTextContent(ALIAS)
    expect(api.addFriend).toHaveBeenCalledWith('bob', ALIAS)
    // 검색 결과가 남아 있으면 사용자가 한 번 더 눌러 409를 받는다.
    await waitFor(() => {
      expect(screen.queryByTestId('friends-add-alias-input')).not.toBeInTheDocument()
    })
  })

  it('이미 친구인 상대(409) 문구를 서버 응답 그대로 보여준다', async () => {
    const user = userEvent.setup()
    api.addFriend.mockResolvedValue({
      ok: false,
      error: { code: 'ALREADY_FRIEND', message: '이미 친구로 등록된 사용자입니다', status: 409 },
    })
    signedIn()
    render(<FriendsView />)
    await searchForBob(user)

    await user.type(screen.getByTestId('friends-add-alias-input'), ALIAS)
    await user.click(screen.getByTestId('friends-add-submit'))

    expect(await screen.findByTestId('friends-error')).toHaveTextContent(
      '이미 친구로 등록된 사용자입니다',
    )
    expect(screen.queryByTestId('friends-list')).not.toBeInTheDocument()
  })
})

describe('FriendsView 목록', () => {
  it('**상대의 display_name을 절대 표시하지 않는다** (FR-2.4)', () => {
    // FR-2.4의 수용 기준 그대로:
    //   Given B의 계정 표시명이 "bob"이고 A가 B에게 붙인 별칭이 "회사 김대리"다
    //   When A가 친구 목록을 조회하면
    //   Then "회사 김대리"가 표시되고 "bob"은 어디에도 표시되지 않는다
    //
    // 응답에 `display_name`·`username`이 섞여 있어도 화면에 새지 않아야 한다.
    signedIn([{ id: 10, friend_user_id: 2, alias: ALIAS, display_name: 'bob', username: 'bob' }])
    render(<FriendsView />)

    const list = screen.getByTestId('friends-list')

    expect(list).toHaveTextContent(ALIAS)
    expect(list.textContent).not.toContain('bob')
  })

  it('친구가 없으면 무엇을 해야 하는지 알려준다', () => {
    // 빈 상태를 방치하면 "왜 아무것도 안 나오지"가 된다.
    signedIn()
    render(<FriendsView />)

    // 두 문장을 각각 확인한다 — 재디자인이 `<br>`로 줄을 나눠 정확 일치가 깨졌다.
    // 문구 자체는 그대로이며, 여기서 지키는 것은 "무엇을 해야 하는지 알려주는가"다.
    const empty = screen.getByTestId('friends-empty')
    expect(empty).toHaveTextContent('아직 친구가 없습니다')
    expect(empty).toHaveTextContent('아이디로 검색해 추가하세요')
    expect(screen.queryByTestId('friends-list')).not.toBeInTheDocument()
  })

  it('별칭을 수정하면 목록에 새 이름이 표시된다', async () => {
    // FR-2.3의 첫 기준.
    const user = userEvent.setup()
    api.updateAlias.mockResolvedValue({
      ok: true,
      data: { id: 10, friend_user_id: 2, alias: '김철수 팀장' },
    })
    signedIn([{ id: 10, friend_user_id: 2, alias: ALIAS }])
    render(<FriendsView />)

    await user.click(screen.getByTestId('friends-alias-edit-10'))
    const input = screen.getByTestId('friends-alias-input-10')
    // 기존 값이 채워져 있다 — 수정은 대개 일부만 바꾸는 일이다.
    expect(input).toHaveValue(ALIAS)

    await user.clear(input)
    await user.type(input, '김철수 팀장')
    await user.click(screen.getByTestId('friends-alias-save-10'))

    await waitFor(() => {
      expect(screen.getByTestId('friends-list-item-10')).toHaveTextContent('김철수 팀장')
    })
    expect(api.updateAlias).toHaveBeenCalledWith(10, '김철수 팀장')
  })

  it('수정 중 값을 비우면 저장 버튼이 비활성화된다', async () => {
    // FR-2.3 — 빈 값은 허용하지 않는다. 서버도 400을 주지만 여기서 먼저 막는다.
    const user = userEvent.setup()
    signedIn([{ id: 10, friend_user_id: 2, alias: ALIAS }])
    render(<FriendsView />)

    await user.click(screen.getByTestId('friends-alias-edit-10'))
    await user.clear(screen.getByTestId('friends-alias-input-10'))

    expect(screen.getByTestId('friends-alias-save-10')).toBeDisabled()
    expect(api.updateAlias).not.toHaveBeenCalled()
  })

  it('입장 시 친구 목록을 불러온다', async () => {
    // 스토어는 비어 있고 응답에만 항목이 있다 — 화면이 실제로 fetch해 반영하는지를 본다.
    signedIn()
    api.listFriends.mockResolvedValue({
      ok: true,
      data: { friends: [{ id: 11, friend_user_id: 3, alias: '동생' }] },
    })
    render(<FriendsView />)

    expect(await screen.findByTestId('friends-list-item-11')).toHaveTextContent('동생')
  })

  it('로그인하지 않았으면 목록을 요청하지 않는다', () => {
    // 401을 받아 오류 문구를 띄우는 것보다, 애초에 묻지 않는 편이 낫다.
    render(<FriendsView />)

    expect(api.listFriends).not.toHaveBeenCalled()
    expect(screen.queryByTestId('friends-search-input')).not.toBeInTheDocument()
  })
})
