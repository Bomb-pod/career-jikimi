import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CHANNEL_NAME, announceRoomViewing, isViewing, watchViewedRooms } from './viewedRooms'

/**
 * 창끼리 "어느 방을 **보고 있는지**" 알리는 채널.
 *
 * **두 창을 진짜로 만들 수는 없다.** jsdom에는 창이 하나뿐이고 `BroadcastChannel`은
 * 자기가 보낸 메시지를 자기에게 주지 않는다. 그래서 상대 창 역할을 채널 하나로
 * 대신 세운다 — 실제 배선(대화 창이 알리고, 목록 창이 듣는다)은 브라우저 두 창으로
 * 따로 확인했다.
 *
 * 여기서 지키는 것은 두 가지이며 **둘 다 깨져도 화면에는 "알림이 안 온다"로만 보인다**:
 *
 * 1. 뒤로 밀린 창은 보고 있는 것으로 세지 않는다
 * 2. 죽은 창이 배지를 영영 막지 못한다
 */

/**
 * 이 테스트가 연 것들. **`afterEach`가 반드시 닫는다.**
 *
 * 각 테스트 끝에서 손으로 닫으면 `expect`가 실패하는 순간 그 줄에 도달하지 못하고,
 * 살아남은 채널이 다음 테스트의 `ping`에 계속 응답한다 — 한 테스트의 실패가 뒤
 * 테스트를 함께 무너뜨리고 원인은 두 번째 실패 쪽에서만 보인다. 채널 이름이 오리진
 * 전역이라 격리가 자동으로 되지 않는다.
 */
const cleanups: Array<() => void> = []

/** 상대 창 역할. `announceRoomViewing`이 붙는 채널과 같은 이름이면 서로 오간다. */
function peer() {
  const channel = new BroadcastChannel(CHANNEL_NAME)
  const seen: unknown[] = []
  channel.onmessage = (event: MessageEvent) => {
    seen.push(event.data)
  }
  cleanups.push(() => channel.close())
  return { channel, seen }
}

/** 구독·알림을 열되 정리를 `afterEach`에 맡긴다. */
function track(stop: () => void): () => void {
  cleanups.push(stop)
  return stop
}

/** 포커스를 흉내 낸다. 되돌리기는 `afterEach`가 한다. */
function focused(value: boolean) {
  const spy = vi.spyOn(document, 'hasFocus').mockReturnValue(value)
  cleanups.push(() => spy.mockRestore())
  return spy
}

/**
 * `BroadcastChannel`의 비동기 전달을 흘려보낸다.
 *
 * 한 틱으로는 모자란다 — jsdom의 전달이 매크로태스크 한 번 안에 끝나지 않아,
 * `setTimeout(0)` 하나만 두면 **첫 테스트만** 간헐적으로 붉어진다.
 */
async function settle(): Promise<void> {
  for (let tick = 0; tick < 3; tick += 1) {
    await new Promise((resolve) => setTimeout(resolve, 5))
  }
}

beforeEach(() => {
  vi.useRealTimers()
})

afterEach(() => {
  while (cleanups.length > 0) cleanups.pop()?.()
  vi.useRealTimers()
})

describe('isViewing', () => {
  it('포커스가 있으면 참이다', () => {
    focused(true)
    expect(isViewing()).toBe(true)
  })

  it('**다른 창을 클릭하면 거짓이다** — 이 판정이 이 모듈의 전부다', () => {
    // 데스크톱에서 다른 창을 클릭해도 이 창은 여전히 `visible`이다. 그래서
    // `visibilityState`만 보면 뒤에 밀린 창을 "보고 있다"로 잘못 센다.
    focused(false)
    expect(isViewing()).toBe(false)
  })
})

describe('announceRoomViewing', () => {
  it('포커스가 있으면 "보는 중"으로 알린다', async () => {
    focused(true)
    const other = peer()
    track(announceRoomViewing(7))
    await settle()

    expect(other.seen).toContainEqual({ type: 'viewing', roomId: 7 })
  })

  it('포커스가 없으면 처음부터 "떠남"으로 알린다', async () => {
    // 창을 열자마자 사용자가 다른 창으로 간 경우다. "보는 중"으로 알렸다가
    // 곧바로 정정하면 그 사이에 온 메시지가 배지를 놓친다.
    focused(false)
    const other = peer()
    track(announceRoomViewing(7))
    await settle()

    expect(other.seen).toContainEqual({ type: 'away', roomId: 7 })
  })

  it('포커스를 잃으면 "떠남"을, 되찾으면 "보는 중"을 알린다', async () => {
    const focus = focused(true)
    const other = peer()
    track(announceRoomViewing(7))
    await settle()
    other.seen.length = 0

    focus.mockReturnValue(false)
    window.dispatchEvent(new Event('blur'))
    await settle()
    expect(other.seen).toContainEqual({ type: 'away', roomId: 7 })

    other.seen.length = 0
    focus.mockReturnValue(true)
    window.dispatchEvent(new Event('focus'))
    await settle()
    expect(other.seen).toContainEqual({ type: 'viewing', roomId: 7 })
  })

  it('되찾을 때 `onResume`을 부른다 — 밀린 읽음 처리를 하는 자리', async () => {
    // 창이 뒤에 있는 동안 도착한 메시지는 읽음 처리를 미뤄 두었다. 여기서 밀지
    // 않으면 서버의 `last_read_seq`가 뒤처진 채 남는다.
    const focus = focused(true)
    const resumed = vi.fn()
    track(announceRoomViewing(7, resumed))
    await settle()

    focus.mockReturnValue(false)
    window.dispatchEvent(new Event('blur'))
    await settle()
    expect(resumed).not.toHaveBeenCalled()

    focus.mockReturnValue(true)
    window.dispatchEvent(new Event('focus'))
    await settle()
    expect(resumed).toHaveBeenCalledTimes(1)
  })

  it('상태가 그대로면 다시 알리지 않는다', async () => {
    // `focus`와 `visibilitychange`가 한 동작에 함께 튀는 브라우저가 있다. 매번
    // 보내면 목록 창이 그때마다 상태를 갱신해 불필요한 렌더가 인다.
    focused(true)
    const other = peer()
    track(announceRoomViewing(7))
    await settle()
    other.seen.length = 0

    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()

    expect(other.seen).toEqual([])
  })

  it('보고 있을 때만 `ping`에 답한다', async () => {
    // 뒤에 밀려 있는 창이 대답하면 그 방의 배지가 영영 뜨지 않는다.
    const focus = focused(true)
    const other = peer()
    track(announceRoomViewing(7))
    await settle()

    other.seen.length = 0
    other.channel.postMessage({ type: 'ping' })
    await settle()
    expect(other.seen).toContainEqual({ type: 'pong', roomId: 7 })

    focus.mockReturnValue(false)
    other.seen.length = 0
    other.channel.postMessage({ type: 'ping' })
    await settle()
    expect(other.seen).toEqual([])
  })

  it('탭을 닫아도(`pagehide`) 알린다', async () => {
    // React의 정리 함수는 탭을 닫을 때 돌지 않는다. 그 경로가 사실상 가장 흔한
    // 종료 방식이라, 이것이 없으면 창을 닫아도 목록 창은 계속 "보고 있다"고 믿는다.
    focused(true)
    const other = peer()
    track(announceRoomViewing(7))
    await settle()
    other.seen.length = 0

    window.dispatchEvent(new Event('pagehide'))
    await settle()

    expect(other.seen).toContainEqual({ type: 'away', roomId: 7 })
  })

  it('정리 함수가 "떠남"을 알린다', async () => {
    focused(true)
    const other = peer()
    const stop = track(announceRoomViewing(7))
    await settle()
    other.seen.length = 0

    stop()
    await settle()

    expect(other.seen).toContainEqual({ type: 'away', roomId: 7 })
  })
})

describe('watchViewedRooms', () => {
  it('보기 시작한 방을 알아차린다', async () => {
    const changes: number[][] = []
    track(watchViewedRooms((ids) => changes.push(ids)))
    const other = peer()

    other.channel.postMessage({ type: 'viewing', roomId: 3 })
    await settle()

    expect(changes.at(-1)).toEqual([3])
  })

  it('떠난 방을 즉시 뺀다', async () => {
    const changes: number[][] = []
    track(watchViewedRooms((ids) => changes.push(ids)))
    const other = peer()

    other.channel.postMessage({ type: 'viewing', roomId: 3 })
    await settle()
    other.channel.postMessage({ type: 'away', roomId: 3 })
    await settle()

    expect(changes.at(-1)).toEqual([])
  })

  it('부팅 시 `ping`을 던져 이미 보고 있던 창을 알아본다', async () => {
    // 목록 창을 새로고침하면 그전에 받은 `viewing`이 사라진다. 물어보지 않으면
    // 이미 열려 있는 대화 창을 영영 모른다.
    const other = peer()
    track(watchViewedRooms(() => undefined))
    await settle()

    expect(other.seen).toContainEqual({ type: 'ping' })
  })

  it('**응답하지 않는 창은 다음 주기에 빠진다** — 강제 종료된 대화 창', async () => {
    // 가장 중요한 성질이다. `away`를 못 보내고 죽은 창이 목록에 남으면 그 방의
    // 배지가 영영 뜨지 않고, 사용자는 알림이 없는 것과 올 것이 없는 것을 구분할 수
    // 없다. `pong`을 `live`에 바로 넣으면 이 테스트가 붉어진다.
    //
    // 주기를 좁혀 부른다 — 기본값(5초)으로는 이 한 항목에 5초를 쓰게 되고, 느린
    // 테스트는 결국 지워진다.
    const changes: number[][] = []
    track(watchViewedRooms((ids) => changes.push(ids), { intervalMs: 60, replyWindowMs: 20 }))
    const other = peer()

    other.channel.postMessage({ type: 'viewing', roomId: 3 })
    await settle()
    expect(changes.at(-1)).toEqual([3])

    await new Promise((resolve) => setTimeout(resolve, 300))

    expect(changes.at(-1)).toEqual([])
  })

  it('응답하는 창은 주기가 지나도 남는다 — 위 규칙이 살아 있는 창까지 지우지 않는다', async () => {
    // 만료만 있고 갱신이 없으면 배지가 5초마다 되살아난다.
    const changes: number[][] = []
    track(watchViewedRooms((ids) => changes.push(ids), { intervalMs: 60, replyWindowMs: 20 }))
    const other = peer()
    other.channel.onmessage = (event: MessageEvent) => {
      if ((event.data as { type?: string })?.type === 'ping') {
        other.channel.postMessage({ type: 'pong', roomId: 3 })
      }
    }

    await new Promise((resolve) => setTimeout(resolve, 300))

    expect(changes.at(-1)).toEqual([3])
  })

  it('정리하면 더 이상 알리지 않는다', async () => {
    const changes: number[][] = []
    const stop = track(watchViewedRooms((ids) => changes.push(ids)))
    const other = peer()
    stop()

    other.channel.postMessage({ type: 'viewing', roomId: 3 })
    await settle()

    expect(changes.some((ids) => ids.includes(3))).toBe(false)
  })
})
