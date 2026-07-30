import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup } from '@testing-library/react'

import App from './App'

/**
 * 셸 스모크 테스트.
 *
 * U1은 화면 로직을 만들지 않으므로 여기서 검증하는 것은 **셸이 실제로 마운트되고
 * 뷰 전환이 동작하는가**뿐이다. 뷰 내용에 대한 테스트는 U3~U5가 자기 뷰와 함께 쓴다.
 *
 * 이 테스트가 있는 이유 — 빌드는 통과하면서 런타임에 마운트가 깨지는 경우가 있다
 * (`#root` 누락, 플러그인 미설정, JSX 변환 실패). 그것을 여기서 잡는다.
 */

afterEach(cleanup)

describe('App 셸', () => {
  it('마운트되고 제목과 네 개의 전환 버튼을 보여준다', () => {
    render(<App />)

    expect(screen.getByTestId('app-shell')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'career-jikimi' })).toBeInTheDocument()

    for (const id of ['auth', 'friends', 'rooms', 'chat']) {
      expect(screen.getByTestId(`nav-${id}`)).toBeInTheDocument()
    }
  })

  it('기본 화면은 로그인이고, 그 버튼만 현재 화면으로 표시된다', () => {
    render(<App />)

    expect(screen.getByTestId('view-auth')).toBeInTheDocument()
    expect(screen.getByTestId('nav-auth')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByTestId('nav-chat')).not.toHaveAttribute('aria-current')
  })

  it('버튼을 누르면 그 화면으로 바뀐다', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByTestId('nav-rooms'))

    expect(screen.getByTestId('view-rooms')).toBeInTheDocument()
    expect(screen.queryByTestId('view-auth')).not.toBeInTheDocument()
    expect(screen.getByTestId('nav-rooms')).toHaveAttribute('aria-current', 'page')
  })

  it('이미 열린 화면의 버튼을 다시 눌러도 그 화면에 머문다', async () => {
    // 경계 사례 — 같은 값으로 setState를 부르는 경로다. 여기서 깨지면
    // 사용자가 현재 탭을 다시 눌렀을 때 화면이 사라진다.
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByTestId('nav-auth'))
    await user.click(screen.getByTestId('nav-auth'))

    expect(screen.getByTestId('view-auth')).toBeInTheDocument()
    expect(screen.getByTestId('nav-auth')).toHaveAttribute('aria-current', 'page')
  })

  it('한 번에 하나의 화면만 열린다', async () => {
    // 경계 사례 — 전환을 연달아 해도 이전 화면이 남지 않아야 한다.
    // 남으면 U3~U5의 뷰가 겹쳐 렌더되고, WebSocket 구독이 둘로 늘어난다.
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByTestId('nav-friends'))
    await user.click(screen.getByTestId('nav-chat'))

    expect(screen.getByTestId('view-chat')).toBeInTheDocument()
    expect(screen.queryByTestId('view-friends')).not.toBeInTheDocument()
    expect(
      screen.getAllByRole('button').filter((button) => button.getAttribute('aria-current')),
    ).toHaveLength(1)
  })

  it('대화 화면은 방을 고르지 않았을 때 그 사실을 알려준다', async () => {
    // U5가 이 자리를 채우면서 안내 문구가 바뀌었다. 빈 상태를 방치하면
    // "왜 아무것도 안 나오지"가 된다 — 어디서 방을 고르는지 알려줘야 한다.
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByTestId('nav-chat'))

    expect(screen.getByTestId('chat-no-room')).toHaveTextContent('채팅방 목록에서 방을 선택')
  })
})
