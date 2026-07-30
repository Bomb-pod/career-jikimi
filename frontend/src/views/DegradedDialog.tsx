import type { RefObject } from 'react'

import ConfirmDialog from './ConfirmDialog'

/**
 * 판정 실패 확인 팝업 — **세션 첫 실패에 한 번만 묻는다** (FR-8.2, BR-8.2).
 *
 * 문구는 `business-logic-model.md` § 확인 팝업 두 종이 정한 그대로다:
 * **"검증 서버에 연결할 수 없습니다. 그래도 보내시겠습니까?"**
 * 부제 **"서버가 정상화될 때까지 검증 없이 전송합니다"** 가 있는 것이 이 팝업과
 * `JudgeConfirmDialog`의 유일한 구조적 차이다 — 수락이 이번 한 건이 아니라 **이후
 * 전부**에 영향을 준다는 사실을 누르기 전에 알려야 한다 (BR-8.3).
 *
 * | 선택 | 결과 |
 * |---|---|
 * | 수락 | 그 메시지는 `failed`로 저장되고(시도했으므로), **그 뒤에** degraded로 전환 |
 * | 거절 | 전송 취소, 입력창 유지, "다시 시도" 표시. degraded로 넘어가지 **않는다** |
 *
 * **응답 전에는 전송하지 않는다** (BR-8.2) — 조용히 보내면 사용자는 검증받았다고
 * 믿은 채로 남는다. 그것이 BR-8.1이 막는 상황이다.
 */
export default function DegradedDialog({
  onAccept,
  onReject,
  returnFocusTo,
}: {
  onAccept: () => void
  onReject: () => void
  returnFocusTo?: RefObject<HTMLElement | null>
}) {
  return (
    <ConfirmDialog
      testId="degraded-dialog"
      confirmTestId="degraded-accept"
      cancelTestId="degraded-reject"
      icon="⚠"
      title="검증 서버에 연결할 수 없습니다. 그래도 보내시겠습니까?"
      subtitle="서버가 정상화될 때까지 검증 없이 전송합니다"
      confirmLabel="보내기"
      cancelLabel="취소"
      onConfirm={onAccept}
      onCancel={onReject}
      returnFocusTo={returnFocusTo}
    />
  )
}
