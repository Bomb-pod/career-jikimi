import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ChatView from './ChatView'
import type { ChatMessage, RoomSummary, VerificationStatus } from '../lib/apiClient'
import { AI_CONTEXT_N, MESSAGE_MAX_LENGTH } from '../lib/constants'
import { useChatStore } from '../store/chatStore'

/**
 * `ChatView`와 확인 팝업 두 종.
 *
 * 여기서 보는 것은 **화면이 규칙을 지키는가**다:
 *
 * | 요구 | 왜 화면에서만 확인되는가 |
 * |---|---|
 * | 판정 대기 중 버튼 비활성화 + "확인 중..." (FR-6.5, NFR-2) | 1~3초 무반응은 앱이 멈춘 것으로 읽힌다 |
 * | 미검증 배지가 **세 상태에만** (BR-8.6) | 서버는 6값을 그대로 주고, 고르는 것은 화면이다 |
 * | 신고 버튼이 **내 메시지에만** (BR-11.1) | 남의 메시지에 버튼이 보이면 403을 받고서야 안다 |
 * | 프라이버시 고지가 **토글 꺼짐에도** (NFR-5) | 켜기 전에 알아야 결정할 수 있다 |
 * | 팝업 기본 포커스가 "취소" | Enter를 반사적으로 누르는 사용자가 강행하지 않게 |
 * | 배경 클릭으로 닫히지 않음 | 실수로 흘려보내면 안 되는 결정이다 |
 */

const api = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  listMessages: vi.fn(() => Promise.resolve({ ok: true as const, data: { messages: [] } })),
  markRead: vi.fn(() => Promise.resolve({ ok: true as const, data: { last_read_seq: 0 } })),
  setAiCheck: vi.fn(() =>
    Promise.resolve({ ok: true as const, data: { ai_check_enabled: false } }),
  ),
  reportMisdirect: vi.fn(),
  judgmentAction: vi.fn(() => Promise.resolve({ ok: true as const, data: null })),
  setAuthToken: vi.fn(),
}))

vi.mock('../lib/apiClient', () => api)

const ROOM = 3
const ME = 1
const OTHER = 2

function room(overrides: Partial<RoomSummary> = {}): RoomSummary {
  return {
    id: ROOM,
    name: '동아리',
    last_seq: 0,
    created_at: '2026-07-30T00:00:00Z',
    unread_count: 0,
    last_read_seq: 0,
    ai_check_enabled: true,
    members: [
      { user_id: ME, display_name: 'alice' },
      { user_id: OTHER, display_name: '회사 김대리' },
    ],
    ...overrides,
  }
}

function message(overrides: Partial<ChatMessage> & { id: number }): ChatMessage {
  return {
    room_id: ROOM,
    sender_id: OTHER,
    seq: overrides.id,
    body: `본문 ${overrides.id}`,
    created_at: '2026-07-30T00:00:00Z',
    verification_status: 'ok',
    misdirect_reported_at: null,
    ...overrides,
  }
}

function mount(state: Partial<ReturnType<typeof useChatStore.getState>> = {}): void {
  useChatStore.setState({
    auth: { token: 'jwt', user: { id: ME, username: 'alice' } },
    rooms: [room()],
    unread: {},
    currentRoomId: ROOM,
    messages: [],
    toasts: [],
    pending: [],
    degraded: false,
    degradedSendCount: 0,
    notice: null,
    ...state,
  })
  render(<ChatView />)
}

/** 응답 시점을 테스트가 잡는 `sendMessage` 대역 — "대기 중" 화면을 만들 수 있다. */
function deferredSend() {
  let release: (value: unknown) => void = () => undefined
  const gate = new Promise((resolve) => {
    release = resolve
  })
  api.sendMessage.mockImplementation(async () => {
    await gate
    return { kind: 'sent', message: message({ id: 90, sender_id: ME }) }
  })
  return { release }
}

beforeEach(() => {
  vi.clearAllMocks()
  api.sendMessage.mockImplementation(() =>
    Promise.resolve({ kind: 'sent', message: message({ id: 90, sender_id: ME }) }),
  )
  api.reportMisdirect.mockImplementation((_id: number, on: boolean) =>
    Promise.resolve({
      ok: true as const,
      data: { misdirect_reported_at: on ? '2026-07-30T01:02:03.000000' : null },
    }),
  )
})

afterEach(cleanup)

// --------------------------------------------------------------------------
// 판정 대기 (FR-6.5, NFR-2)
// --------------------------------------------------------------------------
describe('판정 대기 표시', () => {
  it('응답을 기다리는 동안 버튼이 비활성화되고 "확인 중..."이 보인다', async () => {
    // NFR-2 — 1~3초 무반응은 앱이 멈춘 것으로 읽힌다. 표시가 없으면 사용자가
    // 버튼을 연타하고, 그것이 중복 전송 시도가 된다.
    const { release } = deferredSend()
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByTestId('chat-message-input'), '판정 대기')
    await user.click(screen.getByTestId('chat-send-button'))

    expect(screen.getByTestId('chat-send-button')).toBeDisabled()
    expect(screen.getByTestId('chat-send-button')).toHaveTextContent('확인 중...')

    await act(async () => {
      release(undefined)
    })
    await waitFor(() =>
      expect(screen.getByTestId('chat-send-button')).toHaveTextContent('보내기'),
    )
  })

  it('전송에 성공하면 입력창을 비운다', async () => {
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByTestId('chat-message-input'), '보낼 문장')
    await user.click(screen.getByTestId('chat-send-button'))

    await waitFor(() => expect(screen.getByTestId('chat-message-input')).toHaveValue(''))
  })

  it('본문 길이 상한을 입력칸이 먼저 막는다', () => {
    // 서버가 400 `MESSAGE_TOO_LONG`으로 막지만, 2000자를 다 쓴 뒤에 거절당하는
    // 것보다 애초에 넘겨 입력할 수 없는 편이 낫다.
    mount()

    expect(screen.getByTestId('chat-message-input')).toHaveAttribute(
      'maxlength',
      String(MESSAGE_MAX_LENGTH),
    )
  })
})

// --------------------------------------------------------------------------
// 낙관적 렌더링 (FR-4.3)
// --------------------------------------------------------------------------
describe('낙관적 렌더링', () => {
  it('응답 전에는 임시 메시지가 보이고, 201에서 실제 메시지로 교체된다', async () => {
    const { release } = deferredSend()
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByTestId('chat-message-input'), '임시로 먼저')
    await user.click(screen.getByTestId('chat-send-button'))

    const tempId = useChatStore.getState().pending[0]?.tempId
    expect(useChatStore.getState().pending).toHaveLength(1)
    // 입력창에도 같은 문자열이 남아 있으므로 텍스트가 아니라 훅으로 집는다.
    expect(screen.getByTestId(`chat-pending-${tempId}`)).toHaveTextContent('임시로 먼저')

    await act(async () => {
      release(undefined)
    })

    await waitFor(() => expect(useChatStore.getState().pending).toHaveLength(0))
    expect(screen.getByTestId('chat-message-90')).toBeInTheDocument()
  })

  it('실패하면 임시 메시지를 제거하고 입력창의 텍스트를 남긴다', async () => {
    // 실패한 말풍선을 남기면 보낸 것처럼 보이는데 실제로는 DB에 없다 — NFR-3이
    // 막으려는 착시와 같은 종류다.
    api.sendMessage.mockImplementation(() => Promise.reject(new Error('서버에 연결할 수 없습니다')))
    const user = userEvent.setup()
    mount()

    await user.type(screen.getByTestId('chat-message-input'), '남아 있어야 한다')
    await user.click(screen.getByTestId('chat-send-button'))

    await waitFor(() => expect(screen.getByTestId('chat-retry-button')).toBeInTheDocument())
    expect(useChatStore.getState().pending).toEqual([])
    expect(screen.getByTestId('chat-message-input')).toHaveValue('남아 있어야 한다')
    expect(screen.getByTestId('chat-error')).toHaveTextContent('서버에 연결할 수 없습니다')
  })
})

// --------------------------------------------------------------------------
// 미검증 배지 (BR-8.6, FR-8.6)
// --------------------------------------------------------------------------
describe('미검증 배지', () => {
  const badged: VerificationStatus[] = ['failed', 'degraded', 'skipped_no_context']
  const plain: VerificationStatus[] = ['ok', 'flagged_sent', 'disabled']

  it.each(badged)('`%s`에는 배지가 붙는다', (status) => {
    mount({ messages: [message({ id: 11, verification_status: status })] })

    expect(screen.getByTestId('chat-unverified-badge-11')).toHaveTextContent('검증 안 됨')
  })

  it.each(plain)('`%s`에는 배지가 없다', (status) => {
    // `disabled`를 빼는 이유 — 사용자가 스스로 껐으므로 이미 알고 있다.
    // `flagged_sent`도 빼는데, 검증을 받았고 경고까지 봤기 때문이다.
    mount({ messages: [message({ id: 12, verification_status: status })] })

    expect(screen.queryByTestId('chat-unverified-badge-12')).not.toBeInTheDocument()
  })

  it('스크롤해서 다시 봐도 남는다 — 메시지에 붙은 속성이다', () => {
    // FR-8.6. 목록을 다시 그려도(여기서는 재렌더로 대신한다) 배지가 유지된다.
    // 일시적 알림으로 만들면 사용자가 그 사실을 다시 확인할 방법이 없다.
    mount({ messages: [message({ id: 13, verification_status: 'failed' })] })

    act(() => {
      useChatStore.setState({
        messages: [
          message({ id: 13, verification_status: 'failed' }),
          message({ id: 14, verification_status: 'ok' }),
        ],
      })
    })

    expect(screen.getByTestId('chat-unverified-badge-13')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-unverified-badge-14')).not.toBeInTheDocument()
  })
})

// --------------------------------------------------------------------------
// 신고 (FR-11.1, BR-11.1, BR-11.2)
// --------------------------------------------------------------------------
describe('오발송 신고', () => {
  it('내 메시지에만 신고 버튼이 있다', () => {
    // 남의 메시지를 오발송으로 신고할 수 없다 — 이것은 자기 신고다.
    mount({
      messages: [
        message({ id: 21, sender_id: ME }),
        message({ id: 22, sender_id: OTHER }),
      ],
    })

    expect(screen.getByTestId('chat-report-21')).toBeInTheDocument()
    expect(screen.queryByTestId('chat-report-22')).not.toBeInTheDocument()
  })

  it('누르면 신고되고 다시 누르면 취소된다', async () => {
    const user = userEvent.setup()
    mount({ messages: [message({ id: 21, sender_id: ME })] })

    await user.click(screen.getByTestId('chat-report-21'))
    await waitFor(() =>
      expect(screen.getByTestId('chat-report-21')).toHaveTextContent('신고 취소'),
    )
    expect(api.reportMisdirect).toHaveBeenLastCalledWith(21, true)

    await user.click(screen.getByTestId('chat-report-21'))
    await waitFor(() =>
      expect(screen.getByTestId('chat-report-21')).toHaveTextContent('잘못 보냈어요'),
    )
    expect(api.reportMisdirect).toHaveBeenLastCalledWith(21, false)
  })

  it('검증 상태와 무관하게 신고할 수 있다 (BR-11.2)', () => {
    // `flagged_sent`를 제외한 다섯 상태가 사용자 판단에 대한 신호를 남기지 않는
    // 사각지대다. 상태로 버튼을 감추면 이 기능의 존재 이유가 사라진다.
    mount({
      messages: [
        message({ id: 31, sender_id: ME, verification_status: 'ok' }),
        message({ id: 32, sender_id: ME, verification_status: 'disabled' }),
        message({ id: 33, sender_id: ME, verification_status: 'flagged_sent' }),
      ],
    })

    for (const id of [31, 32, 33]) {
      expect(screen.getByTestId(`chat-report-${id}`)).toBeInTheDocument()
    }
  })
})

// --------------------------------------------------------------------------
// 프라이버시 고지 (NFR-5)와 콜드스타트 안내 (FR-6.4)
// --------------------------------------------------------------------------
describe('고지와 안내', () => {
  it('프라이버시 고지는 **토글이 꺼져 있어도** 보인다', () => {
    // 켜기 전에 무슨 일이 일어나는지 알아야 결정할 수 있다. 켠 뒤에만 보여주면
    // 고지의 목적이 사라진다.
    mount({ rooms: [room({ ai_check_enabled: false })] })

    expect(screen.getByTestId('chat-privacy-notice')).toHaveTextContent(
      '검증 시 최근 대화가 외부 AI로 전송됩니다',
    )
  })

  it('고지를 누르면 무엇이 전송되고 무엇이 전송되지 않는지 펼친다', async () => {
    const user = userEvent.setup()
    mount()

    await user.click(screen.getByTestId('chat-privacy-notice'))

    const detail = screen.getByTestId('chat-privacy-detail')
    expect(detail).toHaveTextContent(`최근 ${AI_CONTEXT_N}개`)
    expect(detail).toHaveTextContent('본문만')
    expect(detail).toHaveTextContent('포함되지 않습니다')
  })

  it('메시지가 N개 미만이면 콜드스타트 안내를 보여준다', () => {
    // BR-6.2로 판정이 돌지 않는데, 그걸 모르면 "AI 검증이 켜져 있는데 왜 아무 일도
    // 안 일어나지"가 된다.
    mount({ messages: [message({ id: 41 })] })

    expect(screen.getByTestId('chat-cold-start')).toHaveTextContent(`${AI_CONTEXT_N}개 미만`)
  })

  it('메시지가 충분히 쌓이면 콜드스타트 안내가 사라진다', () => {
    const many = Array.from({ length: AI_CONTEXT_N }, (_value, index) =>
      message({ id: 50 + index }),
    )
    mount({ messages: many })

    expect(screen.queryByTestId('chat-cold-start')).not.toBeInTheDocument()
  })

  it('빈 방에는 "첫 메시지를 보내보세요."가 보인다', () => {
    mount()

    expect(screen.getByTestId('chat-empty')).toHaveTextContent('첫 메시지를 보내보세요.')
  })
})

// --------------------------------------------------------------------------
// 확인 팝업 (FR-6.6) — 접근성 요구
// --------------------------------------------------------------------------
describe('JudgeConfirmDialog', () => {
  async function openDialog(): Promise<ReturnType<typeof userEvent.setup>> {
    api.sendMessage.mockImplementation(() =>
      Promise.resolve({ kind: 'blocked', reason: 'inappropriate', logId: 77, score: 0.9 }),
    )
    const user = userEvent.setup()
    mount()
    await user.type(screen.getByTestId('chat-message-input'), '이 방에 안 맞는 말')
    await user.click(screen.getByTestId('chat-send-button'))
    return user
  }

  it('409 inappropriate에 팝업이 뜨고 문구가 요구사항 그대로다', async () => {
    await openDialog()

    const dialog = screen.getByTestId('judge-confirm-dialog')
    expect(dialog).toHaveAttribute('role', 'alertdialog')
    expect(dialog).toHaveTextContent('이 방에 맞지 않는 것 같습니다. 그래도 보낼까요?')
  })

  it('**기본 포커스가 "취소"다**', async () => {
    // Enter를 반사적으로 누르는 사용자가 경고를 넘겨 강행 전송하지 않게 한다.
    // precision 우선 방침과 같은 방향이다.
    await openDialog()

    await waitFor(() =>
      expect(screen.getByTestId('judge-confirm-cancel')).toHaveFocus(),
    )
  })

  it('Escape는 취소와 같고 입력창 텍스트가 유지된다', async () => {
    const user = await openDialog()

    await user.keyboard('{Escape}')

    expect(screen.queryByTestId('judge-confirm-dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-message-input')).toHaveValue('이 방에 안 맞는 말')
    // 취소는 판정 로그에 `cancelled`만 남긴다 (BR-6.5, FR-7.2).
    await waitFor(() => expect(api.judgmentAction).toHaveBeenCalledWith(77, 'cancelled'))
  })

  it('**배경을 클릭해도 닫히지 않는다**', async () => {
    // 실수로 흘려보내면 안 되는 결정이다. 닫히면 사용자는 자기가 무엇을 골랐는지
    // 모른 채 다음으로 넘어간다.
    const user = await openDialog()

    const backdrop = screen.getByTestId('judge-confirm-dialog').parentElement
    expect(backdrop).not.toBeNull()
    await user.click(backdrop as HTMLElement)

    expect(screen.getByTestId('judge-confirm-dialog')).toBeInTheDocument()
  })

  it('Tab이 팝업 밖으로 나가지 않는다 (포커스 트랩)', async () => {
    const user = await openDialog()
    await waitFor(() => expect(screen.getByTestId('judge-confirm-cancel')).toHaveFocus())

    await user.tab()
    expect(screen.getByTestId('judge-confirm-send')).toHaveFocus()

    await user.tab()
    expect(screen.getByTestId('judge-confirm-cancel')).toHaveFocus()

    await user.tab({ shift: true })
    expect(screen.getByTestId('judge-confirm-send')).toHaveFocus()
  })

  it('닫히면 포커스가 입력창으로 돌아온다', async () => {
    const user = await openDialog()

    await user.click(screen.getByTestId('judge-confirm-cancel'))

    await waitFor(() => expect(screen.getByTestId('chat-message-input')).toHaveFocus())
  })

  it('"보내기"는 받은 log_id를 force_log_id로 실어 재요청한다', async () => {
    const user = await openDialog()
    api.sendMessage.mockImplementation(() =>
      Promise.resolve({ kind: 'sent', message: message({ id: 91, sender_id: ME }) }),
    )

    await user.click(screen.getByTestId('judge-confirm-send'))

    await waitFor(() =>
      expect(api.sendMessage).toHaveBeenLastCalledWith(ROOM, '이 방에 안 맞는 말', {
        forceLogId: 77,
      }),
    )
    // 강행 전송은 degraded로 넘어가지 않는다 — 판정은 성공했다.
    expect(useChatStore.getState().degraded).toBe(false)
  })
})
