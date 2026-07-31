import { useEffect } from 'react'

import { TOAST_TIMEOUT_MS } from '../lib/constants'
import { openRoomWindow } from '../lib/roomWindow'
import { useChatStore } from '../store/chatStore'

/**
 * 앱 내 토스트 알림 (`business-logic-model.md` § ToastHost, FR-5.3).
 *
 * 보고 있지 않은 방에 메시지가 도착하면 뜨고, 누르면 그 방으로 이동하며 배지가
 * 사라진다 (BR-5.9). **앱이 브라우저 탭에 열려 있는 동안만 동작한다** (BR-5.10) —
 * Service Worker + Web Push는 FR-5.4가 범위 밖으로 정했다.
 *
 * `aria-live="polite"`인 이유 — 스크린리더가 새 메시지 도착을 읽어야 하되, 자동으로
 * 사라지는 알림이 사용자의 focus를 빼앗으면 안 된다. `assertive`는 하던 일을 끊는다.
 *
 * **자동 소멸 타이머가 스토어가 아니라 여기 있는 이유** — 타이머는 화면의 관심사다.
 * 스토어에 두면 테스트가 스토어를 건드릴 때마다 타이머가 살아나고, 화면이 없는데도
 * 시간이 흐른다. 동시 표시 상한(3개)은 반대로 스토어의 몫이다 — 화면이 없어도
 * 큐가 무한히 자라면 안 된다.
 */
export default function ToastHost() {
  const toasts = useChatStore((state) => state.toasts)
  const dismissToast = useChatStore((state) => state.dismissToast)
  const enterRoom = useChatStore((state) => state.enterRoom)
  const clearUnread = useChatStore((state) => state.clearUnread)

  useEffect(() => {
    if (toasts.length === 0) return

    // 토스트마다 타이머를 건다. 하나로 묶으면 나중에 뜬 것이 앞의 것과 함께 사라져
    // 표시 시간이 4초보다 짧아진다.
    const timers = toasts.map((toast) =>
      setTimeout(() => dismissToast(toast.id), TOAST_TIMEOUT_MS),
    )
    return () => {
      for (const timer of timers) clearTimeout(timer)
    }
  }, [toasts, dismissToast])

  return (
    <div className="toast-host" aria-live="polite" data-testid="toast-host">
      {toasts.map((toast) => (
        <button
          key={toast.id}
          type="button"
          className="toast"
          data-testid={`toast-${toast.roomId}`}
          onClick={() => {
            // 클릭하면 그 방이 **새 창으로** 열리고 배지가 사라진다 (BR-5.9).
            // 목록에서 방을 누르는 것과 같은 동작이어야 한다 — 토스트만 같은 창에서
            // 열리면 어디를 눌렀느냐에 따라 결과가 달라진다.
            if (openRoomWindow(toast.roomId) === null) {
              // 팝업 차단 시의 대체 경로. `enterRoom()`이 그 방의 토스트도 지운다.
              void enterRoom(toast.roomId)
            } else {
              clearUnread(toast.roomId)
            }
            dismissToast(toast.id)
          }}
        >
          <span className="toast-room">{toast.roomName}</span>
          <span className="toast-body">{toast.body}</span>
        </button>
      ))}
    </div>
  )
}
