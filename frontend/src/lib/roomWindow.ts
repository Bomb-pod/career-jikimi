/**
 * 대화를 **새 창**으로 여는 장치.
 *
 * 새 탭이 아니라 새 창이다. 브라우저는 `window.open()`의 세 번째 인자에 창 크기가
 * 들어 있으면 탭이 아니라 창으로 연다 — `popup=yes`와 `width`/`height`가 그 신호다.
 * 인자를 비우면 사용자 설정에 따라 탭으로 열리고, 그러면 목록과 대화를 나란히 볼 수
 * 없어 이 기능의 목적이 사라진다.
 *
 * ## 왜 URL에 방 id를 싣는가
 *
 * 새 창은 **새 문서**다. 부모 창의 React 상태를 물려받지 않으므로 "어느 방인가"를
 * 전달할 통로가 필요하고, 통로가 될 수 있는 것은 URL뿐이다. 토큰은 `localStorage`가
 * 같은 오리진에서 공유되므로 따로 넘기지 않는다 — URL에 실으면 주소창과 방문 기록에
 * 남는다.
 *
 * 라우터를 넣지 않은 결정(`App.tsx`)은 그대로다. 쿼리 하나를 부팅 시 한 번 읽을 뿐,
 * 화면 전환은 여전히 상태가 한다.
 *
 * ## 팝업 차단
 *
 * 사용자의 클릭에서 곧바로 부르므로 정상 브라우저는 막지 않는다. 그래도 막히면
 * `window.open()`이 `null`을 준다 — 호출자는 그때 같은 창 안의 팝업(오버레이)으로
 * 떨어진다. 차단된 것을 모른 채 아무 일도 일어나지 않는 화면이 가장 나쁘다.
 */

/** 쿼리 키. 이 값 하나만 부팅 시 읽는다. */
export const ROOM_PARAM = 'room'

/** 새 창의 크기 — 셸의 `--frame-width`(440px)에 창 테두리 몫을 더한 값. */
const WINDOW_WIDTH = 460
const WINDOW_HEIGHT = 900

/**
 * 그 방의 대화 창을 연다.
 *
 * Returns:
 *   열린 창. **팝업이 차단되면 `null`** — 호출자가 대체 경로를 잡아야 한다.
 *
 * **창 이름을 방마다 다르게 준다.** 같은 방을 다시 누르면 새 창이 하나 더 뜨는 대신
 * 이미 열린 창이 앞으로 나온다(`focus()`). 이름을 고정하면 반대로 방을 옮길 때마다
 * 같은 창이 재사용되어 여러 방을 나란히 볼 수 없다.
 */
export function openRoomWindow(roomId: number): Window | null {
  const url = `${window.location.pathname}?${ROOM_PARAM}=${roomId}`
  const features = [
    // 탭이 아니라 창으로 열게 하는 신호. 셋 중 하나라도 빠지면 브라우저에 따라
    // 탭으로 떨어진다.
    'popup=yes',
    `width=${WINDOW_WIDTH}`,
    `height=${WINDOW_HEIGHT}`,
  ].join(',')

  const opened = window.open(url, `career-jikimi-room-${roomId}`, features)
  // 이미 열려 있던 창을 다시 눌렀을 때 뒤에 숨어 있으면 아무 일도 없어 보인다.
  opened?.focus()
  return opened
}

/**
 * 이 창이 대화 전용 창인지 — 주소의 `?room=<id>`를 읽는다.
 *
 * Returns:
 *   방 id. 쿼리가 없거나 양의 정수가 아니면 `null`(= 보통의 앱 창이다).
 *
 * **양의 정수만 받는다.** 주소는 사용자가 고칠 수 있고, `?room=abc`나 `?room=-1`을
 * 그대로 `enterRoom()`에 넘기면 서버가 403이나 422를 주고 화면은 빈 대화로 남는다.
 * 여기서 걸러 보통의 앱 창으로 떨어지는 편이 낫다.
 */
export function readRoomFromUrl(search: string = window.location.search): number | null {
  const raw = new URLSearchParams(search).get(ROOM_PARAM)
  if (raw === null) return null

  const roomId = Number(raw)
  if (!Number.isInteger(roomId) || roomId <= 0) return null
  return roomId
}
