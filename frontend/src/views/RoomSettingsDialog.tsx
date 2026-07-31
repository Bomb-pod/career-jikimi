import { useEffect, useId, useRef, type RefObject } from 'react'

import { AI_CONTEXT_N } from '../lib/constants'

/**
 * 방 설정 팝업 — **AI 검증 토글의 유일한 자리** (FR-6.1).
 *
 * 토글은 한때 방 목록 화면과 대화 헤더 두 곳에 있었다. 개인 설정이 두 곳에 있으면
 * 사용자는 어느 쪽이 진짜인지 확인하려 들고, 한쪽만 고쳐지는 날 두 화면이 서로 다른
 * 상태를 보여준다. 설정은 그 설정이 적용되는 화면 안에 하나만 둔다.
 *
 * **`ConfirmDialog`를 재사용하지 않는다.** 그쪽은 `role="alertdialog"`에 배경 클릭이
 * 막혀 있고 기본 포커스가 "취소"다 — 답을 요구하는 결정용 골격이다. 이 팝업은 반대로
 * **언제든 그냥 닫아도 되는** 설정 화면이므로 배경 클릭과 Escape로 닫힌다. 두 성격을
 * 한 컴포넌트에 담으면 "배경 클릭으로 닫히지 않는다"는 그쪽의 보장이 옵션 하나로
 * 약해진다.
 *
 * **프라이버시 고지가 접혀 있지 않다** (NFR-5). 이전 화면에서는 링크를 눌러야 펼쳐졌는데,
 * 여기서는 토글 바로 아래에 늘 펼쳐 둔다 — 결정을 내리는 자리와 고지가 같은 화면에
 * 있어야 고지의 목적이 산다. 대화 화면에는 검증이 **켜져 있을 때만** 한 줄 요약이
 * 남아, 전송이 실제로 일어나는 동안에는 화면에서 그 사실이 사라지지 않는다.
 */
export interface RoomSettingsDialogProps {
  roomName: string
  aiCheckEnabled: boolean
  onChangeAiCheck: (enabled: boolean) => void
  onClose: () => void
  /** 닫힐 때 포커스를 돌려줄 대상. 보통 이 팝업을 연 설정 버튼이다. */
  returnFocusTo?: RefObject<HTMLElement | null>
}

export default function RoomSettingsDialog({
  roomName,
  aiCheckEnabled,
  onChangeAiCheck,
  onClose,
  returnFocusTo,
}: RoomSettingsDialogProps) {
  const toggleRef = useRef<HTMLInputElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const hintId = useId()

  // 열리면 토글로 포커스를 옮긴다 — 이 팝업을 여는 이유가 사실상 그것 하나다.
  useEffect(() => {
    toggleRef.current?.focus()
  }, [])

  // 닫힐 때 포커스를 설정 버튼으로 돌려준다. 안 돌려주면 키보드 사용자의 포커스가
  // `body`에 떨어져 대화 화면 맨 처음부터 다시 Tab 해야 한다.
  useEffect(() => {
    const target = returnFocusTo
    return () => {
      target?.current?.focus()
    }
  }, [returnFocusTo])

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab') return

    // 포커스 트랩 — 대상은 토글과 닫기 둘뿐이다. `ConfirmDialog`와 같은 이유로
    // 목록을 동적으로 조회하지 않는다: 조회하면 내용이 늘 때 동작이 조용히 달라진다.
    const first = toggleRef.current
    const last = closeRef.current
    if (first === null || last === null) return

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    // **배경 클릭으로 닫힌다.** 결정 팝업 두 종과 반대다 — 흘려보내면 안 되는 답이
    // 아니라 그냥 설정이며, 실수로 열었을 때 빠져나갈 길이 있어야 한다.
    <div className="dialog-backdrop" onClick={onClose} data-testid="room-settings-backdrop">
      <div
        className="dialog dialog-left"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid="room-settings"
        onKeyDown={handleKeyDown}
        // 팝업 안의 클릭이 배경까지 올라가면 설정을 만지자마자 닫힌다.
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id={titleId}>채팅방 설정</h2>
        <p className="dialog-subject" data-testid="room-settings-name">
          {roomName}
        </p>

        {/* 진짜 체크박스 + 보이는 라벨. div로 만들면 키보드로 조작할 수 없고
            스크린리더가 상태를 읽지 못한다. */}
        <label className="toggle-row">
          <input
            ref={toggleRef}
            type="checkbox"
            data-testid="room-settings-ai-toggle"
            checked={aiCheckEnabled}
            aria-describedby={hintId}
            onChange={(event) => onChangeAiCheck(event.target.checked)}
          />
          이 방에서 AI 검증 사용
        </label>
        <p className="field-hint" id={hintId}>
          내 메시지에만 적용됩니다. 다른 참여자의 설정과 무관합니다.
        </p>

        {/* **NFR-5 — 꺼져 있어도 보인다.** 켜기 전에 무슨 일이 일어나는지 알아야
            결정할 수 있다. 켠 뒤에만 보여주면 고지의 목적이 사라진다. */}
        <p className="field-hint" data-testid="room-settings-privacy">
          검증을 켜면 이 방의 최근 {AI_CONTEXT_N}개 메시지 <strong>본문만</strong> 외부 AI
          서비스로 전송됩니다. 참여자의 아이디·이름·별칭은 포함되지 않습니다.
        </p>

        <div className="dialog-actions">
          <button
            type="button"
            className="dialog-cancel"
            data-testid="room-settings-close"
            ref={closeRef}
            onClick={onClose}
          >
            닫기
          </button>
        </div>
      </div>
    </div>
  )
}
