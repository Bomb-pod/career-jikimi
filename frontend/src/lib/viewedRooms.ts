/**
 * 어느 방을 **지금 실제로 보고 있는지**를 창끼리 알린다.
 *
 * 대화가 새 창으로 나가면서 생긴 공백을 메운다. 두 창은 별개 문서라 각자 자기
 * 상태만 본다 — 대화 창은 "이 방 보는 중"이라 배지를 올리지 않지만, 목록 창은 그
 * 사실을 알 방법이 없어 남이 보낸 메시지를 그대로 센다.
 *
 * `BroadcastChannel`은 같은 오리진의 창끼리 메시지를 주고받는 브라우저 API다.
 * **자기가 보낸 메시지는 자기에게 오지 않으므로** 대화 창이 자기 방을 "다른 창이
 * 보고 있다"로 오해하는 일이 없다.
 *
 * ## "열려 있다"가 아니라 "보고 있다"
 *
 * 처음에는 창이 열려 있기만 하면 안 세도록 만들었다. 그러면 대화 창을 한쪽 화면에
 * 띄워 두고 다른 창에서 일하는 동안 온 메시지가 **아무 데도 알려지지 않는다** —
 * 창 뒤에 가려 보이지도 않았는데 읽은 것으로 취급된다.
 *
 * 그래서 기준을 **포커스**로 좁혔다. `document.hasFocus()`가 그 판정이다:
 *
 * | 상황 | 보고 있는가 | 배지 |
 * |---|---|---|
 * | 대화 창을 클릭해 앞에 둠 | 그렇다 | 안 올라감 |
 * | 다른 창을 클릭 (대화 창은 뒤에 보임) | 아니다 | 올라감 |
 * | 최소화·다른 탭으로 이동 | 아니다 | 올라감 |
 *
 * `visibilitychange`만으로는 부족하다 — 데스크톱에서 다른 창을 클릭해도 뒤에 있는
 * 창은 여전히 `visible`이다. 반대로 포커스만 보면 최소화를 놓치는 브라우저가 있어
 * 둘을 함께 본다.
 *
 * ## 왜 ping/pong까지 두는가
 *
 * `viewing`/`away` 두 프레임만으로도 평소에는 맞는다. 두 구멍이 남는데 둘 다 시연
 * 중에 일어난다:
 *
 * | 구멍 | 증상 | 메우는 것 |
 * |---|---|---|
 * | 목록 창을 새로고침 | 이미 보고 있던 대화 창을 모른다 | 부팅 시 `ping` |
 * | 대화 창이 강제 종료 | `away`가 안 나가 배지가 **영영** 안 뜬다 | 주기적 `ping` |
 *
 * 둘째가 더 나쁘다 — 알림이 조용히 사라지고, 사용자는 그 사실을 알 방법이 없다.
 * 그래서 목록 창이 주기적으로 `ping`을 던지고 **응답으로 집합을 다시 만든다.**
 * 응답하지 않는 창은 그 주기에 자동으로 빠진다.
 */

/** 채널 이름. 오리진 안에서 유일하면 된다. */
export const CHANNEL_NAME = 'career-jikimi-viewed-rooms'

/** 목록 창이 `ping`을 던지는 주기. 강제 종료된 창이 빠지는 데 걸리는 시간의 상한이다. */
export const REFRESH_INTERVAL_MS = 5_000

/**
 * `ping` 뒤 응답을 모으는 시간.
 *
 * 같은 기기의 창끼리라 왕복이 사실상 즉시다. 짧게 잡으면 응답을 놓쳐 보고 있는 방이
 * 잠깐 빠지고, 길게 잡으면 새로고침 직후 배지가 한 번 잘못 올라간다. 300ms는
 * 사람이 알아채지 못하면서 지연에는 넉넉하다.
 */
export const REPLY_WINDOW_MS = 300

type Frame =
  | { type: 'viewing'; roomId: number }
  | { type: 'away'; roomId: number }
  | { type: 'pong'; roomId: number }
  | { type: 'ping' }

/**
 * 이 창이 지금 사용자가 보고 있는 창인가.
 *
 * **`hasFocus()`가 주 판정이다.** 다른 창을 클릭하면 즉시 거짓이 된다 — 사용자가
 * 말한 "내가 클릭하여 보고 있는 창"이 그대로 이 값이다. `visibilityState`를 함께
 * 보는 것은 최소화나 탭 전환을 포커스로 잡지 못하는 경우의 보강이다.
 *
 * 서버 렌더링이나 문서가 없는 환경에서는 **참**으로 둔다 — 판단할 근거가 없을 때
 * "보고 있다"로 치면 배지가 덜 뜨는 쪽으로 틀리고, 그 반대는 이미 읽은 말을 안 읽음
 * 으로 쌓는다. 둘 중 덜 나쁜 쪽이다.
 */
export function isViewing(): boolean {
  if (typeof document === 'undefined') return true
  if (document.visibilityState === 'hidden') return false
  return document.hasFocus()
}

/**
 * 채널을 연다. **`BroadcastChannel`이 없으면 `null`.**
 *
 * 없는 환경(오래된 브라우저, 일부 테스트 러너)에서 던지지 않는 것이 중요하다 —
 * 이 기능은 배지를 더 정확하게 만드는 보조이지 앱이 도는 조건이 아니다. 없으면
 * 예전처럼 배지가 올라갈 뿐이다.
 */
function openChannel(): BroadcastChannel | null {
  if (typeof BroadcastChannel === 'undefined') return null
  try {
    return new BroadcastChannel(CHANNEL_NAME)
  } catch {
    return null
  }
}

function frameOf(data: unknown): Frame | null {
  if (typeof data !== 'object' || data === null) return null
  const { type } = data as { type?: unknown }
  if (type === 'ping') return { type: 'ping' }
  if (type !== 'viewing' && type !== 'away' && type !== 'pong') return null
  const { roomId } = data as { roomId?: unknown }
  if (typeof roomId !== 'number') return null
  return { type, roomId }
}

/**
 * 이 창이 그 방을 보고 있음을 알린다 — **대화 창이 부른다.**
 *
 * Args:
 *   roomId: 이 창이 띄운 방.
 *   onResume: 창이 다시 포커스를 얻은 순간 부른다. 그동안 쌓인 메시지를 읽음으로
 *     처리하는 자리다 — 그러지 않으면 서버의 `last_read_seq`가 뒤처진 채 남는다.
 *
 * Returns:
 *   정리 함수. 부르면 "떠났다"를 알리고 채널을 닫는다.
 *
 * **`pagehide`에도 알린다.** React의 정리 함수는 탭을 닫을 때 돌지 않는다 — 그
 * 경로가 사실상 가장 흔한 종료 방식이라, 이것이 없으면 창을 닫아도 목록 창은
 * 계속 "보고 있다"고 믿는다. `beforeunload`가 아니라 `pagehide`인 이유는
 * 뒤로가기 캐시(bfcache)로 들어가는 경우까지 잡기 때문이다.
 */
export function announceRoomViewing(roomId: number, onResume?: () => void): () => void {
  const channel = openChannel()
  if (channel === null) return () => undefined

  const post = (frame: Frame) => {
    try {
      channel.postMessage(frame)
    } catch {
      // 이미 닫힌 채널이다. 알릴 대상이 없을 뿐이므로 조용히 넘어간다.
    }
  }

  let viewing = isViewing()
  post({ type: viewing ? 'viewing' : 'away', roomId })

  /**
   * 포커스가 바뀌었는지 보고, **바뀐 경우에만** 알린다.
   *
   * 매번 보내지 않는 이유 — `focus`와 `visibilitychange`가 한 동작에 함께 튀는
   * 브라우저가 있어 같은 프레임이 두 번 나가고, 목록 창이 그때마다 상태를 갱신해
   * 불필요한 렌더가 인다.
   */
  const sync = () => {
    const next = isViewing()
    if (next === viewing) return
    viewing = next
    post({ type: next ? 'viewing' : 'away', roomId })
    // 돌아온 순간에만 부른다. 떠날 때는 할 일이 없다.
    if (next) onResume?.()
  }

  window.addEventListener('focus', sync)
  window.addEventListener('blur', sync)
  document.addEventListener('visibilitychange', sync)

  const leave = () => post({ type: 'away', roomId })
  window.addEventListener('pagehide', leave)

  channel.onmessage = (event: MessageEvent) => {
    // 목록 창이 보고 있는 창을 세는 중이다. **보고 있을 때만 대답한다** —
    // 뒤에 밀려 있는 창이 대답하면 그 방의 배지가 영영 뜨지 않는다.
    if (frameOf(event.data)?.type === 'ping' && isViewing()) post({ type: 'pong', roomId })
  }

  return () => {
    window.removeEventListener('focus', sync)
    window.removeEventListener('blur', sync)
    document.removeEventListener('visibilitychange', sync)
    window.removeEventListener('pagehide', leave)
    leave()
    channel.close()
  }
}

/**
 * 다른 창이 보고 있는 방 목록을 구독한다 — **목록 창이 부른다.**
 *
 * Args:
 *   onChange: 목록이 바뀔 때마다 방 id 배열로 부른다. 같은 내용이어도 다시 부를 수
 *     있으므로 호출자는 그것을 견뎌야 한다(스토어에 그대로 넣으면 된다).
 *
 * Returns:
 *   정리 함수.
 */
export function watchViewedRooms(
  onChange: (roomIds: number[]) => void,
  // 주기를 인자로 뺀 이유는 **테스트 때문이다.** 이 모듈에서 가장 중요한 성질은
  // "응답하지 않는 창이 한 주기 안에 빠진다"인데, 기본값 그대로면 그것을 확인하는
  // 데 5초를 기다려야 한다. 느린 테스트는 결국 지워지고, 지워지면 죽은 창이
  // 배지를 영영 막는 회귀가 조용히 통과한다.
  { intervalMs = REFRESH_INTERVAL_MS, replyWindowMs = REPLY_WINDOW_MS } = {},
): () => void {
  const channel = openChannel()
  if (channel === null) return () => undefined

  let stopped = false
  /** 지금 보고 있다고 믿는 방들. */
  let live = new Set<number>()
  /** `ping`을 던진 뒤 응답을 모으는 중이면 그 집합. 아니면 `null`. */
  let collecting: Set<number> | null = null

  const emit = () => onChange([...live])

  channel.onmessage = (event: MessageEvent) => {
    const frame = frameOf(event.data)
    if (frame === null) return

    if (frame.type === 'viewing') {
      live.add(frame.roomId)
      collecting?.add(frame.roomId)
      emit()
    } else if (frame.type === 'away') {
      live.delete(frame.roomId)
      collecting?.delete(frame.roomId)
      emit()
    } else if (frame.type === 'pong') {
      // 응답은 **집합을 다시 만드는 재료일 뿐** 즉시 반영하지 않는다. 여기서
      // `live`에 바로 넣으면 죽은 창이 남긴 항목이 영영 지워지지 않는다.
      collecting?.add(frame.roomId)
    }
  }

  const refresh = () => {
    if (stopped) return
    const round = new Set<number>()
    collecting = round
    try {
      channel.postMessage({ type: 'ping' } satisfies Frame)
    } catch {
      return
    }
    setTimeout(() => {
      // 그 사이 새 주기가 시작됐거나 구독이 끝났으면 이 결과는 버린다.
      if (stopped || collecting !== round) return
      collecting = null
      live = round
      emit()
    }, replyWindowMs)
  }

  // 부팅 즉시 한 번 — 목록 창을 새로고침해도 이미 보고 있는 대화 창을 알아본다.
  refresh()
  const timer = setInterval(refresh, intervalMs)

  return () => {
    stopped = true
    clearInterval(timer)
    channel.close()
  }
}
