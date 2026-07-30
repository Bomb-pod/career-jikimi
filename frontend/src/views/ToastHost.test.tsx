import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ToastHost from './ToastHost'
import { useChatStore } from '../store/chatStore'

/**
 * `ToastHost` — FR-5.3과 BR-5.9의 화면 쪽 계약.
 *
 * 토스트가 뜨는 **조건**은 `chatStore.test.ts`가 본다. 여기서 보는 것은 그 결과가
 * 화면에 어떻게 나타나는가다 — `aria-live`, 클릭 시 이동, 4초 뒤 자동 소멸.
 *
 * `dismissToast`가 아니라 실제 타이머를 돌리는 이유 — 자동 소멸은 이 컴포넌트가
 * 소유한 동작이고, 그것이 동작하지 않으면 토스트가 화면에 영원히 남는다.
 */

const api = vi.hoisted(() => ({
  markRead: vi.fn(() => Promise.resolve({ ok: true as const, data: { last_read_seq: 0 } })),
  setAuthToken: vi.fn(),
}))

vi.mock('../lib/apiClient', () => api)

beforeEach(() => {
  vi.clearAllMocks()
  useChatStore.setState({
    rooms: [],
    unread: {},
    currentRoomId: null,
    messages: [],
    toasts: [{ id: 3, roomId: 3, roomName: '가족', body: '저녁 뭐 먹지' }],
  })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('ToastHost', () => {
  it('토스트를 aria-live 영역에 방 이름과 함께 보여준다', () => {
    // FR-5.3의 첫 기준 — 토스트 안에 어느 방인지가 보여야 한다.
    // `polite`인 이유는 자동으로 사라지는 알림이 focus를 빼앗으면 안 되기 때문이다.
    render(<ToastHost />)

    expect(screen.getByTestId('toast-host')).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByTestId('toast-3')).toHaveTextContent('가족')
    expect(screen.getByTestId('toast-3')).toHaveTextContent('저녁 뭐 먹지')
  })

  it('클릭하면 그 방으로 이동하고 토스트가 사라진다 (BR-5.9)', async () => {
    // FR-5.3의 둘째 기준 — 이동 + 배지 소멸. `enterRoom()`이 둘 다 한다.
    const user = (await import('@testing-library/user-event')).default.setup()
    useChatStore.setState({ unread: { 3: 2 } })
    const opened: number[] = []
    render(<ToastHost onOpenRoom={(roomId) => opened.push(roomId)} />)

    await user.click(screen.getByTestId('toast-3'))

    expect(useChatStore.getState().currentRoomId).toBe(3)
    expect(useChatStore.getState().unread[3]).toBe(0)
    expect(opened).toEqual([3])
    expect(screen.queryByTestId('toast-3')).not.toBeInTheDocument()
  })

  it('4초 뒤에 스스로 사라진다', () => {
    // 남아 있으면 화면을 가린다. 4초는 읽고 클릭할 시간이다.
    vi.useFakeTimers()
    render(<ToastHost />)

    act(() => {
      vi.advanceTimersByTime(3_999)
    })
    expect(screen.getByTestId('toast-3')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(screen.queryByTestId('toast-3')).not.toBeInTheDocument()
  })

  it('토스트가 없으면 아무것도 그리지 않는다', () => {
    // 빈 컨테이너는 남는다 — `aria-live` 영역은 내용이 바뀌기 **전에** 존재해야
    // 스크린리더가 변화를 알아챈다.
    useChatStore.setState({ toasts: [] })
    render(<ToastHost />)

    expect(screen.getByTestId('toast-host')).toBeEmptyDOMElement()
  })
})
