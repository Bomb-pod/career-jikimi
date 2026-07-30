/**
 * 전송 상태 기계 (`business-logic-model.md` § 전송 상태 기계).
 *
 * ```
 * [입력 중] --Enter--> [전송 중]  전송 버튼 비활성화 + "확인 중..."   (FR-6.5)
 *    +-- 201                      --> [완료] 임시 메시지를 실제 것으로 (FR-4.3)
 *    +-- 409 reason=inappropriate --> [확인 대기] JudgeConfirmDialog   (FR-6.6)
 *    +-- 409 reason=judge_failed  --> [실패 확인 대기] DegradedDialog  (FR-8.2)
 *    +-- 네트워크 오류             --> [오류] "다시 시도"
 * ```
 *
 * **틀리면 조용히 깨지는 두 가지**를 여기 먼저 적는다:
 *
 * 1. **수락 시 `enterDegraded()`가 재요청 *뒤에* 온다** (BR-8.3). 먼저 부르면 그
 *    재요청이 degraded 경로로 빠져 메시지가 `failed`가 아니라 `degraded`로 저장되고,
 *    "판정을 시도했다"는 사실이 사라진다.
 * 2. **프로브 요청은 `probe: true`를 함께 보낸다** (BR-8.5). 서버가 프로브임을
 *    모르면 실패 시 세션 첫 실패로 보고 409를 주며, 없어야 할 팝업이 다시 뜬다.
 *
 * 화면(`ChatView`)이 아니라 여기 있는 이유 — 경로가 넷이고 그중 둘이 팝업의 응답을
 * 기다린다. 렌더링과 섞으면 그 분기가 JSX 사이에 흩어진다.
 */

import { useCallback, useState } from 'react'

import * as api from '../lib/apiClient'
import type { SendOutcome } from '../lib/apiClient'
import { useChatStore } from '../store/chatStore'

/** 지금 어떤 팝업을 띄워야 하는가. `null`이면 없다. */
export interface PendingDecision {
  kind: 'inappropriate' | 'judge_failed'
  logId: number
  /** 강행 시 그대로 다시 보낼 원문. 사용자가 입력창을 고쳐도 이 값이 쓰인다. */
  text: string
  roomId: number
}

export interface SendController {
  /** 판정·저장 응답을 기다리는 중인가. 전송 버튼 비활성화의 근거다 (FR-6.5). */
  busy: boolean
  /** 응답을 요구하는 팝업. `null`이면 팝업이 없다. */
  decision: PendingDecision | null
  /** 마지막 실패 문구. `null`이면 오류 표시가 없다. */
  error: string | null
  /**
   * "다시 시도" 버튼을 보여야 하는가 (FR-8.4).
   *
   * 검증 실패 팝업을 **거절**했거나 네트워크 오류로 끝났을 때 뜬다. 누르면 같은
   * 텍스트로 검증부터 다시 시작한다 — 별도 API가 아니라 `send()`를 같은 인자로 다시
   * 부르는 것이다 (BR-8.4). 서버 측에 새 표면이 필요 없다.
   */
  retryable: boolean
  /** 전송을 시작한다. 성공하면 `true` — 화면이 입력창을 비울지 판단하는 근거다. */
  send: (roomId: number, text: string) => Promise<boolean>
  /** 팝업에서 "보내기"/"수락"을 골랐다. 저장에 성공하면 `true`. */
  confirm: () => Promise<boolean>
  /** 팝업에서 "취소"를 골랐다 (Escape 포함). */
  cancel: () => Promise<void>
}

/** `roundTrip()`의 결과 — 네트워크 실패는 응답이 아니므로 따로 표현한다. */
type RoundTrip = SendOutcome | { kind: 'transport' }

export function useSendMessage(): SendController {
  const [busy, setBusy] = useState(false)
  const [decision, setDecision] = useState<PendingDecision | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [retryable, setRetryable] = useState(false)

  /**
   * 한 번의 요청 왕복 — 낙관적 렌더링과 그 정리까지 여기서 끝낸다.
   *
   * **임시 메시지는 어떤 경로로 끝나든 제거된다** (`finally`). 남겨 두면 보낸 것처럼
   * 보이는데 DB에는 없다 — NFR-3이 막으려는 착시와 같은 종류다. 성공했을 때만 실제
   * 메시지로 교체된다 (FR-4.3).
   */
  const roundTrip = useCallback(
    async (
      roomId: number,
      text: string,
      opts: { forceLogId?: number; degraded?: boolean; probe?: boolean },
    ): Promise<RoundTrip> => {
      const tempId = useChatStore.getState().addPending(roomId, text)
      try {
        return await api.sendMessage(roomId, text, opts)
      } catch (caught) {
        // 네트워크 실패·타임아웃·5xx만 여기로 온다 (`apiClient`의 예외 규약).
        setError(caught instanceof Error ? caught.message : '메시지를 보낼 수 없습니다')
        return { kind: 'transport' }
      } finally {
        useChatStore.getState().removePending(tempId)
      }
    },
    [],
  )

  const send = useCallback(
    async (roomId: number, text: string): Promise<boolean> => {
      if (busy || text.trim() === '') return false
      setBusy(true)
      setError(null)
      setRetryable(false)

      const before = useChatStore.getState()
      const degraded = before.degraded
      const probe = before.shouldProbe()

      try {
        const outcome = await roundTrip(roomId, text, { degraded, probe })

        // degraded 중에는 프로브 여부와 무관하게 센다 — 카운터가 "degraded 진입 후
        // 몇 번째인가"를 세는 값이기 때문이다. **응답 뒤에** 올리는 이유는 요청이
        // 네트워크에서 죽은 건까지 세면 프로브 주기가 앞당겨져서다.
        if (degraded) useChatStore.getState().noteDegradedSend()

        if (outcome.kind === 'transport') {
          setRetryable(true)
          return false
        }

        if (outcome.kind === 'error') {
          setError(outcome.error.message)
          setRetryable(true)
          return false
        }

        if (outcome.kind === 'sent') {
          useChatStore.getState().applySentMessage(outcome.message)
          // 프로브가 **성공**했다면 판정이 실제로 돈 것이므로 degraded를 푼다.
          // `failed`로 왔다면 그것은 프로브 실패이며 degraded를 유지한다 (BR-8.5).
          if (probe && outcome.message.verification_status !== 'failed') {
            useChatStore.getState().exitDegraded()
          }
          return true
        }

        // 409 두 종 — **응답 전에는 전송하지 않는다** (BR-8.2). 팝업이 뜬다.
        //
        // 프로브 중 `inappropriate`가 왔다면 그것도 판정이 성공한 것이다. API가
        // 살아 있음이 증명됐으므로 degraded를 푼다 — 유지하면 다음 네 건이 검증
        // 없이 나간다.
        if (probe && outcome.reason === 'inappropriate') {
          useChatStore.getState().exitDegraded()
        }
        setDecision({ kind: outcome.reason, logId: outcome.logId, text, roomId })
        return false
      } finally {
        setBusy(false)
      }
    },
    [busy, roundTrip],
  )

  /**
   * 강행 전송 — 받은 `logId`를 `forceLogId`로 실어 재요청한다 (BR-6.4).
   *
   * 부적절 판정의 "보내기"와 판정 실패의 "수락"이 **같은 경로**를 쓴다. 서버가 그
   * 로그의 `verdict`로 상태를 정한다: `inappropriate` → `flagged_sent`,
   * NULL → `failed`.
   */
  const confirm = useCallback(async (): Promise<boolean> => {
    const current = decision
    if (current === null || busy) return false
    setBusy(true)
    setError(null)
    setDecision(null)
    try {
      // **`degraded`를 싣지 않는다.** `forceLogId`가 있으면 서버가 BR-6.1의 상태
      // 결정을 아예 건너뛰므로 값이 무의미하고, 실으면 의도가 흐려진다.
      const outcome = await roundTrip(current.roomId, current.text, {
        forceLogId: current.logId,
      })

      if (outcome.kind === 'transport') {
        setRetryable(true)
        return false
      }
      if (outcome.kind === 'error') {
        setError(outcome.error.message)
        setRetryable(true)
        return false
      }
      if (outcome.kind === 'blocked') {
        // 강행 재요청에 다시 409가 오는 정상 경로는 없다(서버가 `force_log_id`를
        // 받으면 판정하지 않는다). 여기 오면 그 토큰이 이미 소진된 것이므로
        // 팝업을 다시 띄우지 않고 "다시 시도"로 안내한다.
        setRetryable(true)
        return false
      }

      useChatStore.getState().applySentMessage(outcome.message)

      // ---- 여기서부터가 순서의 핵심이다 (BR-8.3) ----
      // 재요청이 **끝난 뒤**에 degraded로 전환한다. 먼저 부르면 위 `roundTrip`이
      // degraded 경로로 빠져 그 메시지가 `failed`가 아니라 `degraded`로 저장된다.
      if (current.kind === 'judge_failed') {
        useChatStore.getState().enterDegraded()
      }
      return true
    } finally {
      setBusy(false)
    }
  }, [busy, decision, roundTrip])

  /**
   * 취소 (BR-6.5, BR-8.4).
   *
   * **입력창 텍스트는 화면이 유지한다.** 이 훅은 입력창을 건드리지 않는다 —
   * `send()`가 `true`를 돌려줬을 때만 화면이 비운다.
   *
   * | 팝업 | 하는 일 | 안 하는 일 |
   * |---|---|---|
   * | 부적절 판정 | 판정 로그에 `cancelled` 기록 (FR-7.2) | "다시 시도" 표시 |
   * | 판정 실패 | "다시 시도" 표시 (FR-8.4) | 라벨 기록, degraded 전환 |
   *
   * **판정 실패 쪽에 `cancelled`를 쓰지 않는 이유** — `verdict`가 NULL이라 그 로그는
   * 어떤 집계에도 들어가지 않고(BR-7.2), 라벨을 쓰면 토큰이 소진되어 사용자가
   * "다시 시도" 대신 마음을 바꿔도 같은 판정으로 보낼 수 없게 된다.
   *
   * **거절은 degraded로 넘어가지 않는다** (BR-8.4). 수락과 거절의 차이가 그것이다.
   */
  const cancel = useCallback(async (): Promise<void> => {
    const current = decision
    if (current === null) return
    setDecision(null)

    if (current.kind === 'judge_failed') {
      setRetryable(true)
      return
    }

    try {
      await api.judgmentAction(current.logId, 'cancelled')
    } catch {
      // 라벨 기록 실패를 사용자에게 알리지 않는다 — 사용자가 요청한 동작(취소)은
      // 이미 이뤄졌고 실패한 것은 집계용 기록이다. 여기서 오류를 띄우면 "취소를
      // 눌렀는데 실패했다"로 읽혀 사용자가 다시 보내려 한다.
    }
  }, [decision])

  return { busy, decision, error, retryable, send, confirm, cancel }
}
