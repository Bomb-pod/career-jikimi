import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from './apiClient'
import { ApiTransportError } from './apiClient'
import { REQUEST_TIMEOUT_MS } from './constants'

/**
 * `apiClient`의 **규약** 테스트.
 *
 * 뷰 테스트는 `apiClient`를 모듈째 갈아끼우므로, 그쪽에서는 "4xx는 값으로 오고
 * 5xx는 던진다"가 내가 만든 모의 객체의 성질일 뿐이다. 그 규약이 실제 구현에서도
 * 성립하는지는 여기서만 확인된다 (`components.md` § apiClient의 경계).
 *
 * `fetch`를 갈아끼운다 — 실제 서버는 백엔드의 pytest가 검증한다.
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  // 모듈 수준 토큰은 테스트끼리 남는다 — 매번 비운다.
  api.setAuthToken(null)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('apiClient 성공 경로', () => {
  it('본문이 있는 요청에 JSON 헤더를 붙이고 응답을 그대로 돌려준다', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(201, { token: 't', user: { id: 1, username: 'alice' } }),
    )

    const result = await api.signup('alice', 'pw123456')

    expect(result).toEqual({ ok: true, data: { token: 't', user: { id: 1, username: 'alice' } } })
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/auth/signup')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ username: 'alice', password: 'pw123456' }))
  })

  it('토큰이 설정되면 Authorization 헤더를 붙인다', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { friends: [] }))
    api.setAuthToken('jwt-token')

    await api.listFriends()

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer jwt-token')
  })

  it('토큰이 없으면 Authorization 헤더를 붙이지 않는다', async () => {
    // 빈 헤더를 보내면 서버가 401을 주지만, `Bearer null` 같은 값을 보내는 것보다
    // 아예 없는 편이 로그에서 원인을 읽기 쉽다.
    fetchMock.mockResolvedValue(jsonResponse(200, { friends: [] }))

    await api.listFriends()

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('검색은 아이디를 쿼리 문자열로 인코딩한다', async () => {
    // 한글·공백이 들어간 아이디가 경로를 깨뜨리지 않아야 한다.
    fetchMock.mockResolvedValue(jsonResponse(200, { user: null }))

    await api.searchUser('김 대리')

    const [path] = fetchMock.mock.calls[0] as [string]
    expect(path).toBe(`/users/search?${new URLSearchParams({ username: '김 대리' }).toString()}`)
    expect(path).not.toContain(' ')
  })

  it('결과 없는 검색(200 + null)은 성공이다', async () => {
    // BR-2.1 — 검색은 성공했고 결과가 비었을 뿐이다. 오류로 만들면 화면이 붉어진다.
    fetchMock.mockResolvedValue(jsonResponse(200, { user: null }))

    const result = await api.searchUser('ali')

    expect(result).toEqual({ ok: true, data: { user: null } })
  })
})

describe('apiClient 오류 규약', () => {
  it('**409를 던지지 않고 값으로 돌려준다**', async () => {
    // `components.md` § apiClient — 409는 정상 흐름의 갈래다. U5의 부적절 판정이
    // 같은 규약을 쓰므로, 여기서 던지면 엔드포인트마다 호출부 모양이 갈라진다.
    fetchMock.mockResolvedValue(
      jsonResponse(409, { error: { code: 'ALREADY_FRIEND', message: '이미 친구입니다' } }),
    )

    const result = await api.addFriend('bob', '김대리')

    expect(result).toEqual({
      ok: false,
      error: { code: 'ALREADY_FRIEND', message: '이미 친구입니다', status: 409 },
    })
  })

  it('400·401·403·404도 값으로 돌려준다', async () => {
    for (const status of [400, 401, 403, 404]) {
      fetchMock.mockResolvedValue(
        jsonResponse(status, { error: { code: 'SOME_CODE', message: '문구' } }),
      )

      const result = await api.updateAlias(1, 'x')

      expect(result.ok).toBe(false)
      if (!result.ok) expect(result.error.status).toBe(status)
    }
  })

  it('422는 pydantic 문구 대신 우리 문구로 정규화한다', async () => {
    // pydantic의 `detail` 배열은 사용자가 읽을 문구가 아니다.
    fetchMock.mockResolvedValue(
      jsonResponse(422, { detail: [{ loc: ['body', 'username'], msg: 'too long' }] }),
    )

    const result = await api.signup('x'.repeat(80), 'pw123456')

    expect(result).toEqual({
      ok: false,
      error: { code: 'VALIDATION_FAILED', message: '입력값을 확인하세요', status: 422 },
    })
  })

  it('JSON이 아닌 오류 본문에도 문구를 만들어 준다', async () => {
    // 프록시가 낀 HTML 오류 페이지가 오는 경우다. 파싱 실패가 예외로 나가면
    // 사용자는 아무 문구도 못 보고 콘솔에만 오류가 남는다.
    fetchMock.mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 404 }))

    const result = await api.listFriends()

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.error.code).toBe('UNKNOWN')
      expect(result.error.message.length).toBeGreaterThan(0)
    }
  })

  it('**5xx는 던진다**', async () => {
    // 사용자가 고칠 수 없는 실패다. 폼 오류로 표시하면 "무엇을 고쳐야 하나"가 된다.
    fetchMock.mockResolvedValue(jsonResponse(500, { detail: 'boom' }))

    await expect(api.listFriends()).rejects.toBeInstanceOf(ApiTransportError)
  })

  it('네트워크 실패는 던진다', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(api.listFriends()).rejects.toBeInstanceOf(ApiTransportError)
  })

  it('응답이 오지 않으면 타임아웃으로 끊고 던진다', async () => {
    // 끊지 않으면 제출 버튼이 계속 비활성 상태로 남아 사용자가 아무것도 할 수 없다.
    vi.useFakeTimers()
    fetchMock.mockImplementation(
      (_path: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')))
        }),
    )

    const pending = api.login('alice', 'pw123456')
    // 던진 예외를 잡을 핸들러를 먼저 붙인다 — unhandled rejection을 만들지 않는다.
    const assertion = expect(pending).rejects.toBeInstanceOf(ApiTransportError)
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 1)
    await assertion
  })
})
