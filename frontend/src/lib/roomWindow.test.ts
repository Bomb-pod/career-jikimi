import { afterEach, describe, expect, it, vi } from 'vitest'

import { openRoomWindow, readRoomFromUrl } from './roomWindow'

/**
 * 새 창으로 대화를 여는 장치.
 *
 * 여기서 지키는 것은 둘이다:
 *
 * 1. **탭이 아니라 창으로 연다** — `window.open()`의 세 번째 인자가 그 신호이고,
 *    빠지면 브라우저가 탭으로 열어 목록과 대화를 나란히 볼 수 없다
 * 2. **주소에서 온 값을 믿지 않는다** — 사용자가 고칠 수 있는 입력이다
 */

afterEach(() => {
  vi.restoreAllMocks()
})

describe('openRoomWindow', () => {
  it('탭이 아니라 창으로 열게 하는 인자를 넘긴다', () => {
    const focus = vi.fn()
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus } as unknown as Window)

    openRoomWindow(12)

    const [url, name, features] = open.mock.calls[0] ?? []
    expect(url).toBe('/?room=12')
    expect(name).toBe('career-jikimi-room-12')
    // 셋 중 하나라도 빠지면 브라우저에 따라 탭으로 떨어진다.
    expect(features).toContain('popup=yes')
    expect(features).toMatch(/width=\d+/)
    expect(features).toMatch(/height=\d+/)
  })

  it('창 이름이 방마다 달라 여러 방을 나란히 띄울 수 있다', () => {
    // 이름을 고정하면 방을 옮길 때마다 같은 창이 재사용되어 한 번에 한 방만 보인다.
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus: vi.fn() } as unknown as Window)

    openRoomWindow(1)
    openRoomWindow(2)

    expect(open.mock.calls[0]?.[1]).not.toBe(open.mock.calls[1]?.[1])
  })

  it('이미 열린 창을 앞으로 가져온다', () => {
    // 같은 방을 다시 눌렀는데 창이 뒤에 숨어 있으면 아무 일도 없어 보인다.
    const focus = vi.fn()
    vi.spyOn(window, 'open').mockReturnValue({ focus } as unknown as Window)

    openRoomWindow(12)

    expect(focus).toHaveBeenCalledTimes(1)
  })

  it('팝업이 차단되면 `null`을 그대로 돌려준다', () => {
    // 호출자가 대체 경로(같은 창 오버레이)를 잡을 수 있어야 한다. 여기서 삼키면
    // 차단된 것을 아무도 모른다.
    vi.spyOn(window, 'open').mockReturnValue(null)

    expect(openRoomWindow(12)).toBeNull()
  })
})

describe('readRoomFromUrl', () => {
  it('`?room=<id>`를 숫자로 읽는다', () => {
    expect(readRoomFromUrl('?room=42')).toBe(42)
  })

  it('쿼리가 없으면 `null` — 보통의 앱 창이다', () => {
    expect(readRoomFromUrl('')).toBeNull()
    expect(readRoomFromUrl('?other=1')).toBeNull()
  })

  it.each(['abc', '', '-1', '0', '1.5', ' '])(
    '`?room=%s`처럼 방 id가 아닌 값은 `null`이다',
    (raw) => {
      // 주소는 사용자가 고칠 수 있다. 그대로 `enterRoom()`에 넘기면 서버가 403이나
      // 422를 주고 화면은 빈 대화로 남아, 원인이 어디에도 보이지 않는다.
      expect(readRoomFromUrl(`?room=${raw}`)).toBeNull()
    },
  )

  it('지수 표기처럼 특이한 숫자 표기도 같은 방 id로 정규화된다', () => {
    // `1e3`은 `Number.isInteger`를 통과하는 1000이다. 막지 않는 이유 — 결과가
    // 정상적인 방 id이고, 그 방의 접근 권한은 어차피 서버가 판정한다. 여기서 걸러야
    // 하는 것은 **id가 아닌 값**이지 id를 적는 방식이 아니다.
    expect(readRoomFromUrl('?room=1e3')).toBe(1000)
  })
})
