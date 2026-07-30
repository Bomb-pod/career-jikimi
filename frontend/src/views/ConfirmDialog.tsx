import { useEffect, useRef, type ReactNode, type RefObject } from 'react'

/**
 * 확인 팝업의 공통 골격 (`business-logic-model.md` § 확인 팝업 두 종).
 *
 * `JudgeConfirmDialog`와 `DegradedDialog`가 문구만 다르고 동작이 같다. 두 벌로 두면
 * 한쪽만 고쳐지고, 접근성 요구는 정확히 그렇게 조용히 깨진다.
 *
 * | 요구 | 구현 | 왜 |
 * |---|---|---|
 * | `role="alertdialog"` | 아래 `div` | 응답을 요구하는 상황이다 |
 * | **기본 포커스 "취소"** | `cancelRef`에 `focus()` | Enter를 반사적으로 누르는 사용자가 강행 전송하지 않게 |
 * | 포커스 트랩 | Tab/Shift+Tab을 두 버튼 사이에 가둔다 | 열려 있는 동안 뒤쪽 UI로 나가면 팝업을 놓친다 |
 * | Escape = 취소 | `keydown` | 입력창 텍스트는 유지된다 (호출자가 건드리지 않는다) |
 * | **배경 클릭으로 닫히지 않음** | 배경에 `onClick`이 없다 | 실수로 흘려보내면 안 되는 결정이다 |
 * | 닫힐 때 포커스 복귀 | `returnFocusTo` | 팝업이 사라진 뒤 포커스가 `body`에 남으면 키보드 사용자가 길을 잃는다 |
 * | 색 의존 금지 | `icon` + 텍스트 | 색만으로 구분하면 색각 이상 사용자에게 정보가 없다 |
 *
 * **기본 포커스가 "취소"인 것이 이 파일에서 가장 중요한 한 줄이다.** precision 우선
 * 방침(경고를 무시하고 보내는 것을 쉽게 만들지 않는다)과 같은 방향이다.
 */
export interface ConfirmDialogProps {
  testId: string
  confirmTestId: string
  cancelTestId: string
  /** 색에 기대지 않기 위한 기호. 스크린리더에는 읽히지 않는다(`aria-hidden`). */
  icon: string
  title: string
  subtitle?: string
  confirmLabel: string
  cancelLabel: string
  onConfirm: () => void
  onCancel: () => void
  /** 닫힐 때 포커스를 돌려줄 대상. 보통 입력창이다. */
  returnFocusTo?: RefObject<HTMLElement | null>
  children?: ReactNode
}

export default function ConfirmDialog({
  testId,
  confirmTestId,
  cancelTestId,
  icon,
  title,
  subtitle,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  returnFocusTo,
  children,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const titleId = `${testId}-title`

  // **기본 포커스는 "취소"다.** 마운트 직후 한 번만 옮긴다.
  useEffect(() => {
    cancelRef.current?.focus()
  }, [])

  // 닫힐 때 포커스를 입력창으로 돌려준다. 언마운트 시점에 한 번.
  useEffect(() => {
    const target = returnFocusTo
    return () => {
      target?.current?.focus()
    }
  }, [returnFocusTo])

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') {
      // 취소와 동일하다. 입력창 텍스트는 호출자가 유지한다.
      event.preventDefault()
      onCancel()
      return
    }
    if (event.key !== 'Tab') return

    // 포커스 트랩 — 이 팝업의 포커스 대상은 두 버튼뿐이다. 목록을 동적으로
    // 조회하지 않는 이유는, 조회하면 `children`에 링크가 들어왔을 때 조용히
    // 동작이 달라지기 때문이다. 두 버튼으로 고정해 두면 규칙이 눈에 보인다.
    const first = cancelRef.current
    const last = confirmRef.current
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
    // **배경에 `onClick`이 없다.** 클릭으로 닫히면 안 되는 결정이다 — 실수로 흘려
    // 보내면 사용자는 자기가 무엇을 골랐는지 모른 채 다음으로 넘어간다.
    <div className="dialog-backdrop">
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        data-testid={testId}
        onKeyDown={handleKeyDown}
      >
        {/* `h2`인 이유 — `aria-labelledby`가 가리키는 요소가 제목 시맨틱이어야
            스크린리더가 팝업을 "제목이 있는 대화상자"로 읽는다. */}
        <h2 id={titleId}>
          {/* 색만으로 표시하지 않는다 — 기호와 문구를 함께 둔다. */}
          <span aria-hidden="true">{icon}</span> {title}
        </h2>
        {subtitle !== undefined && <p>{subtitle}</p>}
        {children}
        <div className="dialog-actions">
          {/* DOM 순서에서 "취소"가 먼저다 — Tab 순서와 기본 포커스가 어긋나지 않게. */}
          <button
            type="button"
            className="dialog-cancel"
            data-testid={cancelTestId}
            ref={cancelRef}
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className="dialog-confirm"
            data-testid={confirmTestId}
            ref={confirmRef}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
