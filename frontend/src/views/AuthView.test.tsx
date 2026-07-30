import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import AuthView from './AuthView'
import { useChatStore } from '../store/chatStore'

/**
 * `AuthView` — FR-1.1·FR-1.2와 BR-1.4의 UI 쪽 계약.
 *
 * `apiClient`를 모듈째 갈아끼운다. `fetch`를 흉내내는 것보다 나은 이유 — 이 테스트가
 * 확인해야 하는 것은 "어떤 인자로 무엇을 불렀고 응답을 어떻게 화면에 옮겼는가"이며,
 * HTTP 직렬화는 `apiClient` 자신의 관심사다.
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

const SERVER_401_MESSAGE = '아이디 또는 비밀번호가 올바르지 않습니다'

function resetStore() {
  useChatStore.setState({ auth: { token: null, user: null }, friends: [] })
}

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  resetStore()
})

afterEach(cleanup)

describe('AuthView 로그인', () => {
  it('입력한 자격증명으로 로그인하고 토큰을 스토어에 넣는다', async () => {
    const user = userEvent.setup()
    api.login.mockResolvedValue({
      ok: true,
      data: { token: 'jwt-token', user: { id: 1, username: 'alice' } },
    })
    render(<AuthView />)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.click(screen.getByTestId('auth-login-submit'))

    await waitFor(() => {
      expect(useChatStore.getState().auth.token).toBe('jwt-token')
    })
    expect(api.login).toHaveBeenCalledWith('alice', 'pw123456')
    expect(api.signup).not.toHaveBeenCalled()
  })

  it('401 문구를 서버 응답 그대로 보여준다', async () => {
    // **BR-1.4가 UI까지 이어지는 지점이다.** 프론트가 "아이디가 없습니다"로 바꾸면
    // 서버가 애써 숨긴 계정 존재 여부가 화면으로 새어나간다.
    const user = userEvent.setup()
    api.login.mockResolvedValue({
      ok: false,
      error: { code: 'INVALID_CREDENTIALS', message: SERVER_401_MESSAGE, status: 401 },
    })
    render(<AuthView />)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'wrong-password')
    await user.click(screen.getByTestId('auth-login-submit'))

    const errorRegion = await screen.findByTestId('auth-error')
    // 문구가 **정확히 같아야 한다.** 부분 일치로 확인하면 프론트가 앞뒤에 자기 말을
    // 덧붙이는 것을 놓친다.
    expect(errorRegion).toHaveTextContent(SERVER_401_MESSAGE)
    expect(errorRegion.textContent).toBe(SERVER_401_MESSAGE)
    expect(useChatStore.getState().auth.token).toBeNull()
  })

  it('요청이 진행되는 동안 제출 버튼을 비활성화한다', async () => {
    // 비활성화하지 않으면 사용자가 두 번 눌러 두 번의 로그인 요청이 나간다.
    const user = userEvent.setup()
    let release: (value: unknown) => void = () => {}
    api.login.mockReturnValue(
      new Promise((resolve) => {
        release = resolve
      }),
    )
    render(<AuthView />)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.click(screen.getByTestId('auth-login-submit'))

    await waitFor(() => {
      expect(screen.getByTestId('auth-login-submit')).toBeDisabled()
    })
    // 비활성화된 이유가 스크린리더에도 전달된다 (`aria-describedby`).
    const describedBy = screen.getByTestId('auth-login-submit').getAttribute('aria-describedby')
    expect(describedBy).not.toBeNull()

    // 실패로 끝내는 이유 — 성공하면 폼이 사라져(로그인 상태 화면으로 바뀜) 버튼이
    // 다시 눌릴 수 있는지 확인할 대상이 없다. 여기서 확인하려는 것은 **응답이 온 뒤
    // 잠금이 풀린다**는 것이다.
    release({
      ok: false,
      error: { code: 'INVALID_CREDENTIALS', message: SERVER_401_MESSAGE, status: 401 },
    })
    await waitFor(() => {
      expect(screen.getByTestId('auth-login-submit')).not.toBeDisabled()
    })
    expect(screen.getByTestId('auth-login-submit')).not.toHaveAttribute('aria-describedby')
  })

  it('서버에 닿지 못하면 그 문구를 보여주고 토큰을 남기지 않는다', async () => {
    // 네트워크 실패는 apiClient가 **던진다**. 잡지 않으면 사용자에게 아무 반응이 없다.
    const user = userEvent.setup()
    api.login.mockRejectedValue(new Error('서버에 연결할 수 없습니다'))
    render(<AuthView />)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.click(screen.getByTestId('auth-login-submit'))

    expect(await screen.findByTestId('auth-error')).toHaveTextContent('서버에 연결할 수 없습니다')
    expect(useChatStore.getState().auth.token).toBeNull()
    // 버튼이 다시 눌릴 수 있어야 한다 — 실패 후 잠긴 채 남으면 재시도할 방법이 없다.
    expect(screen.getByTestId('auth-login-submit')).not.toBeDisabled()
  })
})

describe('AuthView 회원가입', () => {
  async function switchToSignup(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByTestId('auth-switch-mode'))
  }

  it('짧은 비밀번호는 요청을 보내기 전에 막는다', async () => {
    // 클라이언트 검사는 **편의**다 — 서버가 진실이지만, 확실히 실패할 요청의
    // 왕복을 아낀다. 요청이 나가지 않았음을 확인하는 것이 이 테스트의 요점이다.
    const user = userEvent.setup()
    render(<AuthView />)
    await switchToSignup(user)

    await user.type(screen.getByLabelText('아이디'), 'shorty')
    await user.type(screen.getByLabelText('비밀번호'), 'pw12345')
    await user.type(screen.getByLabelText('비밀번호 확인'), 'pw12345')
    await user.click(screen.getByTestId('auth-signup-submit'))

    expect(api.signup).not.toHaveBeenCalled()
    expect(screen.getByTestId('auth-error')).toHaveTextContent('8자 이상')
  })

  it('비밀번호 확인이 다르면 요청을 보내지 않는다', async () => {
    const user = userEvent.setup()
    render(<AuthView />)
    await switchToSignup(user)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.type(screen.getByLabelText('비밀번호 확인'), 'pw123457')
    await user.click(screen.getByTestId('auth-signup-submit'))

    expect(api.signup).not.toHaveBeenCalled()
    expect(screen.getByTestId('auth-error')).toHaveTextContent('비밀번호가 서로 다릅니다')
  })

  it('가입 성공 시 응답 토큰을 그대로 저장한다 (자동 로그인)', async () => {
    // 가입 응답에 토큰이 실려 오므로 다시 로그인할 필요가 없다
    // (`code-generation-plan.md` § 이 계획이 닫는 열린 항목).
    const user = userEvent.setup()
    api.signup.mockResolvedValue({
      ok: true,
      data: { token: 'fresh-token', user: { id: 9, username: 'alice' } },
    })
    render(<AuthView />)
    await switchToSignup(user)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.type(screen.getByLabelText('비밀번호 확인'), 'pw123456')
    await user.click(screen.getByTestId('auth-signup-submit'))

    await waitFor(() => {
      expect(useChatStore.getState().auth.token).toBe('fresh-token')
    })
    expect(api.login).not.toHaveBeenCalled()
    expect(useChatStore.getState().auth.user).toEqual({ id: 9, username: 'alice' })
  })

  it('중복 아이디(409) 문구를 서버 응답 그대로 보여준다', async () => {
    // apiClient가 409를 던지지 않으므로 401·400과 같은 경로로 처리된다.
    const user = userEvent.setup()
    api.signup.mockResolvedValue({
      ok: false,
      error: { code: 'USERNAME_TAKEN', message: '이미 사용 중인 아이디입니다', status: 409 },
    })
    render(<AuthView />)
    await switchToSignup(user)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.type(screen.getByLabelText('비밀번호 확인'), 'pw123456')
    await user.click(screen.getByTestId('auth-signup-submit'))

    expect(await screen.findByTestId('auth-error')).toHaveTextContent('이미 사용 중인 아이디입니다')
    expect(useChatStore.getState().auth.token).toBeNull()
  })

  it('모드를 바꾸면 앞 모드의 오류가 남지 않는다', async () => {
    // 남으면 사용자가 방금 바꾼 화면에 대한 오류라고 오해한다.
    const user = userEvent.setup()
    api.login.mockResolvedValue({
      ok: false,
      error: { code: 'INVALID_CREDENTIALS', message: SERVER_401_MESSAGE, status: 401 },
    })
    render(<AuthView />)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.click(screen.getByTestId('auth-login-submit'))
    expect(await screen.findByTestId('auth-error')).toHaveTextContent(SERVER_401_MESSAGE)

    await user.click(screen.getByTestId('auth-switch-mode'))

    expect(screen.getByTestId('auth-error')).toBeEmptyDOMElement()
    expect(screen.getByTestId('auth-signup-submit')).toBeInTheDocument()
  })
})

describe('AuthView 접근성', () => {
  it('모든 입력에 보이는 라벨이 붙어 있다', async () => {
    // placeholder만으로 대신하지 않는다 (`business-logic-model.md` § 접근성).
    // 입력을 시작하면 placeholder는 사라져 무엇을 적던 칸인지 알 수 없게 된다.
    const user = userEvent.setup()
    render(<AuthView />)

    expect(screen.getByLabelText('아이디')).toBeVisible()
    expect(screen.getByLabelText('비밀번호')).toBeVisible()

    await user.click(screen.getByTestId('auth-switch-mode'))
    expect(screen.getByLabelText('비밀번호 확인')).toBeVisible()
  })

  it('오류는 aria-live 영역 하나에만 나온다 (필드별 표시가 아니다)', async () => {
    const user = userEvent.setup()
    api.login.mockResolvedValue({
      ok: false,
      error: { code: 'INVALID_CREDENTIALS', message: SERVER_401_MESSAGE, status: 401 },
    })
    render(<AuthView />)

    await user.type(screen.getByLabelText('아이디'), 'alice')
    await user.type(screen.getByLabelText('비밀번호'), 'pw123456')
    await user.click(screen.getByTestId('auth-login-submit'))

    const region = await screen.findByTestId('auth-error')
    expect(region).toHaveAttribute('aria-live', 'polite')
    // 같은 문구가 화면에 두 번 나오지 않는다 — 필드별 표시를 하지 않는다는 뜻이다.
    expect(screen.getAllByText(SERVER_401_MESSAGE)).toHaveLength(1)
  })
})
