import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ChatView from './ChatView'
import type { ChatMessage, RoomSummary, SendOutcome, VerificationStatus } from '../lib/apiClient'
import { DEGRADED_RECOVERED_MESSAGE, PROBE_EVERY } from '../lib/constants'
import { useChatStore } from '../store/chatStore'

/**
 * degraded 상태 기계 — **NFR-7이 이 단위에 지운 두 테스트 의무 중 나머지 하나**
 * (FR-8.3, FR-8.5).
 *
 * `business-logic-model.md` § 테스트 대상이 이것을 지목한 이유:
 * **경로가 많아 손 테스트가 샌다.** 첫 실패 → 팝업 → 수락 → `failed` → *그 다음*
 * degraded → 5번째 프로브 → 성공 시 복귀. 일곱 단계 중 하나만 어긋나도 화면은
 * 멀쩡해 보이고 데이터만 틀린다.
 *
 * **검증하는 것은 순서다.** 엔드포인트가 불렸는지가 아니라 **불린 시점의 상태**가
 * 무엇이었는지를 본다 — `enterDegraded()`를 재요청보다 먼저 부르는 버그는 호출
 * 횟수로는 잡히지 않는다.
 */

const api = vi.hoisted(() => ({
  sendMessage: vi.fn(),
  listMessages: vi.fn(() => Promise.resolve({ ok: true as const, data: { messages: [] } })),
  markRead: vi.fn(() => Promise.resolve({ ok: true as const, data: { last_read_seq: 0 } })),
  setAiCheck: vi.fn(() =>
    Promise.resolve({ ok: true as const, data: { ai_check_enabled: true } }),
  ),
  reportMisdirect: vi.fn(() =>
    Promise.resolve({ ok: true as const, data: { misdirect_reported_at: null } }),
  ),
  judgmentAction: vi.fn(() => Promise.resolve({ ok: true as const, data: null })),
  setAuthToken: vi.fn(),
}))

vi.mock('../lib/apiClient', () => api)

const ROOM_A = 7
const ROOM_B = 8

function room(id: number): RoomSummary {
  return {
    id,
    name: `방 ${id}`,
    last_seq: 0,
    created_at: '2026-07-30T00:00:00Z',
    unread_count: 0,
    last_read_seq: 0,
    ai_check_enabled: true,
    members: [{ user_id: 1, display_name: 'alice' }],
  }
}

let nextId = 100

function stored(status: VerificationStatus, roomId = ROOM_A): ChatMessage {
  nextId += 1
  return {
    id: nextId,
    room_id: roomId,
    sender_id: 1,
    seq: nextId,
    body: `본문 ${nextId}`,
    created_at: '2026-07-30T00:00:00Z',
    verification_status: status,
    misdirect_reported_at: null,
  }
}

/** `sendMessage()` 호출 하나의 기록 — 인자와 **그 시점의 degraded 값**. */
interface Call {
  roomId: number
  text: string
  opts: { forceLogId?: number; degraded?: boolean; probe?: boolean }
  degradedAtCallTime: boolean
}

const calls: Call[] = []

/**
 * `sendMessage()` 대역을 세운다. 응답은 호출 순서대로 꺼내 쓴다.
 *
 * **호출 시점의 `degraded`를 함께 기록하는 것이 이 헬퍼의 존재 이유다.** 순서
 * 버그(먼저 `enterDegraded()`를 부르는 것)는 호출 횟수나 최종 상태로는 잡히지
 * 않는다 — 요청이 나가던 그 순간의 상태를 봐야 한다.
 */
function respondWith(...outcomes: SendOutcome[]): void {
  let index = 0
  api.sendMessage.mockImplementation(
    (roomId: number, text: string, opts: Call['opts'] = {}) => {
      calls.push({
        roomId,
        text,
        opts,
        degradedAtCallTime: useChatStore.getState().degraded,
      })
      const outcome = outcomes[Math.min(index, outcomes.length - 1)]
      index += 1
      return Promise.resolve(outcome)
    },
  )
}

function reset(): void {
  useChatStore.setState({
    auth: { token: 'jwt', user: { id: 1, username: 'alice' } },
    rooms: [room(ROOM_A), room(ROOM_B)],
    unread: {},
    currentRoomId: ROOM_A,
    messages: [],
    toasts: [],
    pending: [],
    degraded: false,
    degradedSendCount: 0,
    notice: null,
  })
}

async function type(user: ReturnType<typeof userEvent.setup>, text: string): Promise<void> {
  await user.clear(screen.getByTestId('chat-message-input'))
  await user.type(screen.getByTestId('chat-message-input'), text)
}

async function sendOnce(
  user: ReturnType<typeof userEvent.setup>,
  text: string,
): Promise<void> {
  await type(user, text)
  await user.click(screen.getByTestId('chat-send-button'))
}

beforeEach(() => {
  vi.clearAllMocks()
  calls.length = 0
  window.localStorage.clear()
  window.sessionStorage.clear()
  reset()
})

afterEach(cleanup)

// --------------------------------------------------------------------------
// 첫 실패 → 팝업 (FR-8.2, BR-8.2)
// --------------------------------------------------------------------------
describe('세션 첫 판정 실패', () => {
  it('DegradedDialog를 띄우고 **응답 전에는 전송하지 않는다**', async () => {
    // BR-8.2 — 조용히 보내면 사용자는 검증받았다고 믿은 채로 남는다 (BR-8.1).
    respondWith({ kind: 'blocked', reason: 'judge_failed', logId: 55 })
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '오늘 회식 어떠세요')

    expect(screen.getByTestId('degraded-dialog')).toBeInTheDocument()
    // 요청은 딱 한 번 — 팝업이 뜬 상태에서 몰래 두 번째가 나가지 않았다.
    expect(calls).toHaveLength(1)
    expect(calls[0]?.opts.forceLogId).toBeUndefined()
    // 저장된 것이 없으므로 목록도 비어 있다.
    expect(useChatStore.getState().messages).toEqual([])
    // 아직 degraded가 아니다 — 사용자가 답하기 전이다.
    expect(useChatStore.getState().degraded).toBe(false)
  })

  it('부제로 "이후 전부"에 영향을 준다는 사실을 알린다', async () => {
    // 수락은 이번 한 건이 아니라 이후 모든 전송을 바꾼다 (BR-8.3). 누르기 전에
    // 알아야 하므로 부제가 이 팝업의 필수 요소다 — `JudgeConfirmDialog`와의
    // 유일한 구조적 차이가 그것이다.
    respondWith({ kind: 'blocked', reason: 'judge_failed', logId: 55 })
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '한 건이 아니다')

    const dialog = screen.getByTestId('degraded-dialog')
    expect(dialog).toHaveTextContent('검증 서버에 연결할 수 없습니다. 그래도 보내시겠습니까?')
    expect(dialog).toHaveTextContent('서버가 정상화될 때까지 검증 없이 전송합니다')
  })
})

// --------------------------------------------------------------------------
// 수락 — **순서가 전부다** (FR-8.3, BR-8.3)
// --------------------------------------------------------------------------
describe('수락', () => {
  it('force_log_id로 재요청하고, 그 메시지는 `failed`이며, **그 다음** degraded로 간다', async () => {
    // 이것이 functional-design 리뷰어가 잡은 blocking finding의 회귀 테스트다.
    // `enterDegraded()`를 먼저 부르면 재요청이 `degraded: true`로 나가 BR-6.1의
    // 2번 규칙에 걸리고, 그 메시지가 `failed`가 아니라 `degraded`로 저장된다 —
    // "판정을 시도했다"는 사실이 사라진다.
    respondWith(
      { kind: 'blocked', reason: 'judge_failed', logId: 55 },
      { kind: 'sent', message: stored('failed') },
    )
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '오늘 회식 어떠세요')
    await user.click(screen.getByTestId('degraded-accept'))

    await waitFor(() => expect(calls).toHaveLength(2))
    const retry = calls[1]
    expect(retry?.opts.forceLogId).toBe(55)
    expect(retry?.text).toBe('오늘 회식 어떠세요')
    // **순서 검증** — 재요청이 나가던 순간에는 아직 degraded가 아니었다.
    expect(retry?.degradedAtCallTime).toBe(false)
    expect(retry?.opts.degraded).toBeFalsy()
    // 그 결과 그 메시지는 `failed`다 (FR-8.3).
    expect(useChatStore.getState().messages[0]?.verification_status).toBe('failed')
    // **그리고 나서야** degraded다.
    await waitFor(() => expect(useChatStore.getState().degraded).toBe(true))
    expect(useChatStore.getState().degradedSendCount).toBe(0)
  })

  it('수락한 뒤 입력창이 비고 팝업이 사라진다', async () => {
    respondWith(
      { kind: 'blocked', reason: 'judge_failed', logId: 55 },
      { kind: 'sent', message: stored('failed') },
    )
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '보낼 문장')
    await user.click(screen.getByTestId('degraded-accept'))

    await waitFor(() =>
      expect(screen.queryByTestId('degraded-dialog')).not.toBeInTheDocument(),
    )
    expect(screen.getByTestId('chat-message-input')).toHaveValue('')
  })
})

// --------------------------------------------------------------------------
// 거절 (FR-8.4, BR-8.4)
// --------------------------------------------------------------------------
describe('거절', () => {
  it('전송을 취소하고 입력을 유지하며 "다시 시도"를 띄운다 — degraded로 가지 않는다', async () => {
    respondWith({ kind: 'blocked', reason: 'judge_failed', logId: 55 })
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '유지되어야 하는 문장')
    await user.click(screen.getByTestId('degraded-reject'))

    expect(screen.queryByTestId('degraded-dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('chat-message-input')).toHaveValue('유지되어야 하는 문장')
    expect(screen.getByTestId('chat-retry-button')).toBeInTheDocument()
    // **거절은 degraded로 넘어가지 않는다.** 수락과의 차이가 이것이다.
    expect(useChatStore.getState().degraded).toBe(false)
    // 저장도 하지 않았다.
    expect(calls).toHaveLength(1)
    expect(useChatStore.getState().messages).toEqual([])
  })

  it('"다시 시도"는 같은 텍스트로 **검증부터** 다시 시작한다', async () => {
    // BR-8.4 — 별도 메서드가 아니라 `send()`를 같은 인자로 다시 부르는 것이다.
    // 서버 측에 새 표면이 필요 없다. `forceLogId`가 실리면 그것은 강행이지 재검증이
    // 아니다.
    respondWith(
      { kind: 'blocked', reason: 'judge_failed', logId: 55 },
      { kind: 'sent', message: stored('ok') },
    )
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '다시 검증받을 문장')
    await user.click(screen.getByTestId('degraded-reject'))
    await user.click(screen.getByTestId('chat-retry-button'))

    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1]?.text).toBe('다시 검증받을 문장')
    expect(calls[1]?.opts.forceLogId).toBeUndefined()
    expect(calls[1]?.opts.probe).toBe(false)
  })
})

// --------------------------------------------------------------------------
// 프로브 (FR-8.5, BR-8.5)
// --------------------------------------------------------------------------
describe('프로브', () => {
  it(`degraded 중 ${PROBE_EVERY - 1}번 보낸 뒤 ${PROBE_EVERY}번째가 프로브다`, async () => {
    // 앞 네 건은 판정을 건너뛰고(`degraded: true, probe: false`), 다섯 번째만
    // `probe: true`로 나간다. degraded 진입 직후를 프로브로 삼지 않는 이유는
    // 방금 실패한 API를 곧바로 다시 부르는 것이 의미가 적어서다.
    //
    // 앞 네 건은 서버가 `degraded`로, 프로브는 실패해 `failed`로 저장한다 —
    // 실제 서버가 돌려줄 수 있는 조합이다. 프로브가 성공하면 degraded가 풀려
    // 다음 주기 자체가 사라지므로, 여기서는 실패 쪽을 본다.
    respondWith(
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('failed') },
    )
    useChatStore.setState({ degraded: true, degradedSendCount: 0 })
    const user = userEvent.setup()
    render(<ChatView />)

    for (let index = 0; index < PROBE_EVERY; index += 1) {
      await sendOnce(user, `degraded 중 ${index}`)
    }

    expect(calls).toHaveLength(PROBE_EVERY)
    for (let index = 0; index < PROBE_EVERY - 1; index += 1) {
      expect(calls[index]?.opts).toMatchObject({ degraded: true, probe: false })
    }
    // **다섯 번째가 프로브다.** `degraded`도 함께 실려야 서버가 실패 시 팝업 없이
    // 201 `failed`로 끝낼 수 있다 (BR-8.5).
    expect(calls[PROBE_EVERY - 1]?.opts).toMatchObject({ degraded: true, probe: true })
  })

  it('프로브가 성공하면 degraded를 풀고 복귀를 알린다', async () => {
    respondWith({ kind: 'sent', message: stored('ok') })
    useChatStore.setState({ degraded: true, degradedSendCount: PROBE_EVERY - 1 })
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '프로브')

    await waitFor(() => expect(useChatStore.getState().degraded).toBe(false))
    expect(useChatStore.getState().degradedSendCount).toBe(0)
    expect(screen.getByTestId('chat-notice')).toHaveTextContent(DEGRADED_RECOVERED_MESSAGE)
  })

  it('프로브가 실패하면 **팝업 없이** degraded를 유지하고 그 메시지는 `failed`다', async () => {
    // BR-8.5 — 사용자는 이미 degraded를 수락해 두었으므로 다시 묻지 않는다.
    // 서버가 201 `failed`를 주는 것이 그 장치이며, 여기서 409가 오면 degraded 구간
    // 내내 5번째마다 팝업이 뜬다.
    respondWith({ kind: 'sent', message: stored('failed') })
    useChatStore.setState({ degraded: true, degradedSendCount: PROBE_EVERY - 1 })
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '프로브 실패')

    expect(screen.queryByTestId('degraded-dialog')).not.toBeInTheDocument()
    expect(useChatStore.getState().degraded).toBe(true)
    expect(useChatStore.getState().messages[0]?.verification_status).toBe('failed')
    // 복귀 안내도 뜨지 않는다 — 회복하지 않았다.
    expect(screen.queryByTestId('chat-notice')).not.toBeInTheDocument()
  })

  it('프로브 실패 뒤에도 카운터가 이어져 다음 주기에 다시 프로브한다', async () => {
    // 실패했다고 카운터를 멈추면 회복을 영영 감지하지 못한다.
    respondWith({ kind: 'sent', message: stored('failed') })
    useChatStore.setState({ degraded: true, degradedSendCount: PROBE_EVERY - 1 })
    const user = userEvent.setup()
    render(<ChatView />)

    for (let index = 0; index < PROBE_EVERY + 1; index += 1) {
      await sendOnce(user, `사이클 ${index}`)
    }

    const probes = calls.filter((call) => call.opts.probe === true)
    expect(probes).toHaveLength(2)
  })
})

// --------------------------------------------------------------------------
// 카운터의 범위 (BR-8.5) — **사용자 전역이다**
// --------------------------------------------------------------------------
describe('프로브 카운터의 범위', () => {
  it('방을 옮겨도 이어서 센다', async () => {
    // 방 단위로 세면 방을 옮길 때마다 리셋되어 프로브가 거의 돌지 않는다.
    // degraded 자체가 모든 방에 적용되므로(BR-8.3) 카운터도 같은 범위여야 한다.
    //
    // 다섯 번째(프로브)를 실패로 두는 이유 — 성공하면 degraded가 풀려 카운터가
    // 0으로 초기화되고, 그러면 "이어서 셌는가"를 마지막에 확인할 수 없다.
    respondWith(
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('degraded') },
      { kind: 'sent', message: stored('failed', ROOM_B) },
    )
    useChatStore.setState({ degraded: true, degradedSendCount: 0 })
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '방 A에서 1')
    await sendOnce(user, '방 A에서 2')

    // 방을 옮긴다. `act`로 감싸는 이유는 렌더 밖에서 스토어를 건드리기 때문이다.
    act(() => {
      useChatStore.setState({ currentRoomId: ROOM_B, messages: [] })
    })

    await sendOnce(user, '방 B에서 3')
    await sendOnce(user, '방 B에서 4')
    await sendOnce(user, '방 B에서 5')

    // 리셋됐다면 방 B의 세 건 중 프로브가 없다. 이어졌다면 다섯 번째가 프로브다.
    expect(calls).toHaveLength(PROBE_EVERY)
    expect(calls[PROBE_EVERY - 1]?.roomId).toBe(ROOM_B)
    expect(calls[PROBE_EVERY - 1]?.opts.probe).toBe(true)
    expect(useChatStore.getState().degradedSendCount).toBe(PROBE_EVERY)
  })
})

// --------------------------------------------------------------------------
// 메모리 전용 (FR-8.3)
// --------------------------------------------------------------------------
describe('degraded의 저장 위치', () => {
  it('`localStorage`·`sessionStorage`에 쓰지 않는다', async () => {
    // FR-8.3이 "새로고침하거나 새 탭을 열면 초기화되어 정상 검증을 다시 시도한다"를
    // 요구하므로, 저장하는 순간 요구사항 위반이다.
    const local = vi.spyOn(Storage.prototype, 'setItem')
    respondWith(
      { kind: 'blocked', reason: 'judge_failed', logId: 55 },
      { kind: 'sent', message: stored('failed') },
    )
    const user = userEvent.setup()
    render(<ChatView />)

    await sendOnce(user, '저장되면 안 된다')
    await user.click(screen.getByTestId('degraded-accept'))
    await waitFor(() => expect(useChatStore.getState().degraded).toBe(true))

    expect(local).not.toHaveBeenCalled()
    expect(window.localStorage.length).toBe(0)
    expect(window.sessionStorage.length).toBe(0)
    local.mockRestore()
  })

  it('스토어를 다시 만들면(새로고침 시뮬레이션) degraded가 초기화된다', async () => {
    // 모듈을 새로 평가하는 것이 새 탭·새로고침과 같다. 어딘가에 저장하고 있으면
    // 새 인스턴스가 그 값을 다시 읽어 여기서 `true`가 나온다.
    useChatStore.setState({ degraded: true, degradedSendCount: 3 })

    vi.resetModules()
    const fresh = await import('../store/chatStore')

    expect(fresh.useChatStore.getState().degraded).toBe(false)
    expect(fresh.useChatStore.getState().degradedSendCount).toBe(0)
  })
})
