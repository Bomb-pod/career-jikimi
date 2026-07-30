import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

import * as api from '../lib/apiClient'
import type { ChatMessage, VerificationStatus } from '../lib/apiClient'
import {
  AI_CONTEXT_N,
  MESSAGE_MAX_LENGTH,
  TOAST_TIMEOUT_MS,
} from '../lib/constants'
import { roomDisplayName } from '../lib/roomName'
import { useChatStore } from '../store/chatStore'
import DegradedDialog from './DegradedDialog'
import JudgeConfirmDialog from './JudgeConfirmDialog'
import { useSendMessage } from './useSendMessage'

/**
 * 대화 화면 (`business-logic-model.md` § ChatView).
 *
 * | 영역 | 내용 |
 * |---|---|
 * | 헤더 | 방 이름 + **AI 검증 토글** + **프라이버시 고지** (NFR-5) |
 * | 목록 | 메시지 + 발신자 표시명 + **미검증 배지** + 신고 |
 * | 입력 | textarea + 전송 버튼 (+ "다시 시도" 조건부) |
 * | 비어 있음 | "첫 메시지를 보내보세요." + **콜드스타트 안내** |
 *
 * **프라이버시 고지는 토글이 꺼져 있어도 보인다** (NFR-5) — 켜기 전에 무슨 일이
 * 일어나는지 알아야 결정할 수 있다. 켠 뒤에만 보여주면 고지의 목적이 사라진다.
 *
 * **콜드스타트 안내가 중요하다** — 방에 메시지가 `N`개 미만이면 판정이 돌지 않는데
 * (BR-6.2), 그걸 모르면 "AI 검증이 켜져 있는데 왜 아무 일도 안 일어나지"가 된다.
 *
 * **미검증 배지는 스크롤해서 다시 봐도 남는다** (FR-8.6) — 메시지에 붙은 속성이지
 * 일시적 알림이 아니다. 히스토리 응답의 `verification_status`가 그 근거다.
 */

/** "검증 안 됨" 배지가 붙는 세 상태 (BR-8.6). */
const UNVERIFIED: ReadonlySet<VerificationStatus> = new Set<VerificationStatus>([
  'failed',
  'degraded',
  'skipped_no_context',
])

/**
 * `ok`·`flagged_sent`·`disabled`에는 배지가 없다.
 *
 * `disabled`를 빼는 이유 — 사용자가 스스로 껐으므로 이미 알고 있다. 배지는
 * "검증받았다고 믿었는데 아니었다"를 알리는 장치다. `flagged_sent`도 빼는데,
 * 검증을 받았고 경고까지 봤기 때문이다.
 */
function isUnverified(status: VerificationStatus): boolean {
  return UNVERIFIED.has(status)
}

export default function ChatView() {
  const myUserId = useChatStore((state) => state.auth.user?.id ?? null)
  const rooms = useChatStore((state) => state.rooms)
  const currentRoomId = useChatStore((state) => state.currentRoomId)
  const messages = useChatStore((state) => state.messages)
  const pending = useChatStore((state) => state.pending)
  const degraded = useChatStore((state) => state.degraded)
  const notice = useChatStore((state) => state.notice)
  const setAiCheck = useChatStore((state) => state.setAiCheck)
  const setReported = useChatStore((state) => state.setReported)
  const dismissNotice = useChatStore((state) => state.dismissNotice)

  const [text, setText] = useState('')
  const [privacyOpen, setPrivacyOpen] = useState(false)
  const [roomError, setRoomError] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const inputId = useId()
  const privacyDetailId = useId()

  const send = useSendMessage()
  const room = rooms.find((item) => item.id === currentRoomId) ?? null

  // 복귀 안내는 잠깐만 보인다 — 방 이름이 없는 시스템 안내라 `toasts` 큐에 넣을 수
  // 없고(그 큐는 방 단위다), 영원히 남으면 화면을 차지한다.
  useEffect(() => {
    if (notice === null) return
    const timer = setTimeout(() => dismissNotice(), TOAST_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [notice, dismissNotice])

  if (currentRoomId === null || room === null) {
    return (
      <section className="panel">
        <p className="muted" data-testid="chat-no-room">
          채팅방 목록에서 방을 선택하면 대화가 열립니다.
        </p>
      </section>
    )
  }

  const names = new Map(room.members.map((member) => [member.user_id, member.display_name]))
  const roomPending = pending.filter((item) => item.roomId === currentRoomId)
  const coldStart = messages.length < AI_CONTEXT_N

  function nameOf(message: ChatMessage): string {
    // 방 참여자 목록이 우선이다 — 서버가 **호출자 기준으로** 해석한 표시명이며
    // (FR-2.4), 목록·토스트·대화가 같은 방의 사람을 같게 부르게 된다.
    // 히스토리 응답의 `sender_display_name`은 참여자가 빠진 경우의 보조다.
    return names.get(message.sender_id) ?? message.sender_display_name ?? `사용자 ${message.sender_id}`
  }

  async function handleSend(): Promise<void> {
    const body = text
    const ok = await send.send(currentRoomId as number, body)
    // **성공했을 때만 입력창을 비운다** (FR-6.6, FR-8.4). 409든 네트워크 오류든
    // 텍스트가 남아 있어야 사용자가 다시 쓰지 않는다.
    if (ok) setText('')
  }

  async function handleConfirm(): Promise<void> {
    // **저장에 성공했을 때만 비운다.** 강행 재요청이 네트워크에서 죽었는데 입력창을
    // 비우면 사용자가 쓴 문장이 아무 데도 남지 않는다.
    if (await send.confirm()) setText('')
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    // Shift+Enter는 줄바꿈이다. Enter만 전송 — 채팅의 관용구다.
    if (event.key !== 'Enter' || event.shiftKey) return
    event.preventDefault()
    void handleSend()
  }

  async function handleAiCheck(enabled: boolean): Promise<void> {
    if (room === null) return
    setRoomError(null)
    // 낙관적으로 먼저 바꾼다 — 체크박스가 응답을 기다리며 멈춰 있으면 고장으로 보인다.
    setAiCheck(room.id, enabled)
    try {
      const result = await api.setAiCheck(room.id, enabled)
      if (!result.ok) {
        setAiCheck(room.id, !enabled)
        setRoomError(result.error.message)
      }
    } catch (caught) {
      setAiCheck(room.id, !enabled)
      setRoomError(caught instanceof Error ? caught.message : '설정을 바꿀 수 없습니다')
    }
  }

  async function handleReport(message: ChatMessage): Promise<void> {
    setRoomError(null)
    const turningOn = message.misdirect_reported_at === null
    try {
      const result = await api.reportMisdirect(message.id, turningOn)
      if (!result.ok) {
        setRoomError(result.error.message)
        return
      }
      setReported(message.id, result.data.misdirect_reported_at)
    } catch (caught) {
      setRoomError(caught instanceof Error ? caught.message : '신고를 처리할 수 없습니다')
    }
  }

  return (
    <section className="panel">
      {/* ---------------- 헤더 ---------------- */}
      <div className="chat-header">
        <h3 data-testid="chat-room-name">{roomDisplayName(room, myUserId)}</h3>

        <label>
          <input
            type="checkbox"
            data-testid="chat-ai-toggle"
            checked={room.ai_check_enabled}
            onChange={(event) => void handleAiCheck(event.target.checked)}
          />
          이 방에서 AI 검증 사용
        </label>

        {/* **NFR-5 — 토글이 꺼져 있어도 보인다.** 켜기 전에 무슨 일이 일어나는지
            알아야 결정할 수 있다. `details`가 아니라 버튼인 이유는 열림 상태를
            테스트가 확인할 수 있게 하기 위해서다. */}
        <button
          type="button"
          className="link"
          data-testid="chat-privacy-notice"
          aria-expanded={privacyOpen}
          aria-controls={privacyDetailId}
          onClick={() => setPrivacyOpen((open) => !open)}
        >
          검증 시 최근 대화가 외부 AI로 전송됩니다
        </button>
        {privacyOpen && (
          <p className="field-hint" id={privacyDetailId} data-testid="chat-privacy-detail">
            검증을 켜면 이 방의 최근 {AI_CONTEXT_N}개 메시지 <strong>본문만</strong> 외부 AI
            서비스로 전송됩니다. 참여자의 아이디·이름·별칭은 포함되지 않습니다.
          </p>
        )}
      </div>

      {degraded && (
        <p className="banner banner-muted" role="status" data-testid="chat-degraded-banner">
          검증 서버에 연결할 수 없어 검증 없이 전송하고 있습니다
        </p>
      )}

      {notice !== null && (
        <p className="banner" role="status" data-testid="chat-notice">
          {notice}
        </p>
      )}

      <div className="form-error" aria-live="polite" data-testid="chat-error">
        {send.error ?? roomError}
      </div>

      {/* ---------------- 목록 ---------------- */}
      {messages.length === 0 && roomPending.length === 0 ? (
        <p className="muted" data-testid="chat-empty">
          첫 메시지를 보내보세요.
        </p>
      ) : (
        <ul className="chat-list" data-testid="chat-list">
          {messages.map((message) => (
            <li key={message.id} data-testid={`chat-message-${message.id}`}>
              <span className="chat-sender">{nameOf(message)}</span>
              <span className="chat-body">{message.body}</span>

              {/* **세 상태에만 붙는다** (BR-8.6). 색이 아니라 문구로 알린다. */}
              {isUnverified(message.verification_status) && (
                <span
                  className="badge badge-warn"
                  data-testid={`chat-unverified-badge-${message.id}`}
                  title="AI 검증을 받지 못한 메시지입니다"
                >
                  검증 안 됨
                </span>
              )}

              {/* **내 메시지에만** 신고 버튼이 있다 (BR-11.1). 남의 메시지를
                  오발송으로 신고할 수 없다 — 이것은 자기 신고다. */}
              {message.sender_id === myUserId && (
                <button
                  type="button"
                  className="link"
                  data-testid={`chat-report-${message.id}`}
                  aria-pressed={message.misdirect_reported_at !== null}
                  onClick={() => void handleReport(message)}
                >
                  {message.misdirect_reported_at === null ? '잘못 보냈어요' : '신고 취소'}
                </button>
              )}
            </li>
          ))}

          {/* 낙관적 렌더링 (FR-4.3) — 201이 오면 위 목록의 실제 메시지로 교체된다.
              그 외에는 사라지고 입력창의 텍스트가 남는다. */}
          {roomPending.map((item) => (
            <li key={item.tempId} className="chat-pending" data-testid={`chat-pending-${item.tempId}`}>
              <span className="chat-body">{item.body}</span>
              <span className="muted">보내는 중…</span>
            </li>
          ))}
        </ul>
      )}

      {/* **콜드스타트 안내** (FR-6.4) — 판정이 왜 안 도는지 알려준다. */}
      {coldStart && room.ai_check_enabled && (
        <p className="field-hint" data-testid="chat-cold-start">
          이 방의 메시지가 {AI_CONTEXT_N}개 미만이라 아직 AI 검증이 동작하지 않습니다. 대화가
          쌓이면 자동으로 시작됩니다.
        </p>
      )}

      {/* ---------------- 입력 ---------------- */}
      <div className="chat-composer">
        <label className="visually-hidden" htmlFor={inputId}>
          메시지 입력
        </label>
        <textarea
          id={inputId}
          ref={inputRef}
          data-testid="chat-message-input"
          value={text}
          maxLength={MESSAGE_MAX_LENGTH}
          rows={2}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          className="primary"
          data-testid="chat-send-button"
          // **FR-6.5·NFR-2** — 판정 대기 중에는 누를 수 없고 "확인 중..."이 보인다.
          // 1~3초 무반응은 앱이 멈춘 것으로 읽힌다.
          disabled={send.busy || text.trim() === ''}
          onClick={() => void handleSend()}
        >
          {send.busy ? '확인 중...' : '보내기'}
        </button>

        {/* **FR-8.4** — 거절했거나 네트워크 오류였을 때만 뜬다. 누르면 같은 텍스트로
            검증부터 다시 시작한다. 횟수 제한은 없고, 요청 중에만 비활성화된다. */}
        {send.retryable && (
          <button
            type="button"
            className="secondary"
            data-testid="chat-retry-button"
            disabled={send.busy || text.trim() === ''}
            onClick={() => void handleSend()}
          >
            다시 시도
          </button>
        )}
      </div>

      {/* ---------------- 팝업 두 종 ---------------- */}
      {send.decision?.kind === 'inappropriate' && (
        <JudgeConfirmDialog
          onConfirm={() => void handleConfirm()}
          onCancel={() => void send.cancel()}
          returnFocusTo={inputRef}
        />
      )}
      {send.decision?.kind === 'judge_failed' && (
        <DegradedDialog
          onAccept={() => void handleConfirm()}
          onReject={() => void send.cancel()}
          returnFocusTo={inputRef}
        />
      )}
    </section>
  )
}
