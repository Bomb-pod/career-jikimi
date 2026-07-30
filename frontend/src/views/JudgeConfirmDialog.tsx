import type { RefObject } from 'react'

import ConfirmDialog from './ConfirmDialog'

/**
 * 부적절 판정 확인 팝업 (FR-6.6, BR-6.3).
 *
 * 문구는 `business-logic-model.md` § 확인 팝업 두 종이 정한 그대로다:
 * **"이 방에 맞지 않는 것 같습니다. 그래도 보낼까요?"**
 *
 * **기본 포커스는 "취소"다** — Enter를 반사적으로 누르는 사용자가 경고를 넘겨
 * 강행 전송하지 않게 한다.
 *
 * "보내기"는 받은 `log_id`를 `force_log_id`로 실어 재요청하고(BR-6.4), "취소"는
 * 판정 로그에 `cancelled`만 남긴다(BR-6.5). 어느 쪽이든 입력창 텍스트는 유지된다.
 */
export default function JudgeConfirmDialog({
  onConfirm,
  onCancel,
  returnFocusTo,
}: {
  onConfirm: () => void
  onCancel: () => void
  returnFocusTo?: RefObject<HTMLElement | null>
}) {
  return (
    <ConfirmDialog
      testId="judge-confirm-dialog"
      confirmTestId="judge-confirm-send"
      cancelTestId="judge-confirm-cancel"
      icon="⚠"
      title="이 방에 맞지 않는 것 같습니다. 그래도 보낼까요?"
      confirmLabel="보내기"
      cancelLabel="취소"
      onConfirm={onConfirm}
      onCancel={onCancel}
      returnFocusTo={returnFocusTo}
    />
  )
}
