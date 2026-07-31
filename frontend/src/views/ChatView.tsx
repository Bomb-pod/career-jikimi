import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

import * as api from '../lib/apiClient'
import type { ChatMessage, VerificationStatus } from '../lib/apiClient'
import {
  AI_CONTEXT_N,
  MESSAGE_MAX_LENGTH,
  TOAST_TIMEOUT_MS,
} from '../lib/constants'
import { avatarColor, avatarInitial } from '../lib/avatar'
import { roomDisplayName } from '../lib/roomName'
import { formatClock, formatDateDivider, isSameDay } from '../lib/time'
import { useChatStore } from '../store/chatStore'
import DegradedDialog from './DegradedDialog'
import { CloseIcon, SettingsIcon } from './Icons'
import JudgeConfirmDialog from './JudgeConfirmDialog'
import RoomSettingsDialog from './RoomSettingsDialog'
import { useSendMessage } from './useSendMessage'

/**
 * 대화 화면 (`business-logic-model.md` § ChatView).
 *
 * | 영역 | 내용 |
 * |---|---|
 * | 헤더 | 닫기 + 방 이름 + **설정 버튼** |
 * | 목록 | 메시지 + 발신자 표시명 + **내 메시지의 미검증 배지** + 신고 |
 * | 입력 | textarea + 전송 버튼 (+ "다시 시도" 조건부) |
 * | 비어 있음 | "첫 메시지를 보내보세요." + **콜드스타트 안내** |
 *
 * **AI 검증 토글은 이 화면에 없다.** 설정 버튼이 여는 `RoomSettingsDialog` 안에만
 * 있다 — 개인 설정이 여러 화면에 흩어지면 어느 쪽이 진짜인지 확인하는 일이 사용자
 * 몫이 된다.
 *
 * **프라이버시 고지는 두 곳에 나뉜다** (NFR-5). 전문은 설정 팝업 안에 늘 펼쳐져
 * 있고(끄고 켜는 결정을 그 자리에서 한다), 대화 화면에는 **검증이 켜져 있을 때만**
 * 한 줄 요약이 남는다. 전송이 실제로 일어나는 상태에서는 그 사실이 화면에서 사라지지
 * 않아야 한다.
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

/**
 * `onClose` — 대화를 닫는다. 앱 셸이 `leaveRoom()`으로 연결한다.
 *
 * 대화가 팝업으로 열리므로 닫는 버튼이 이 화면 안에 있어야 한다. 셸의 상단 바에
 * 두면 팝업 바깥의 버튼이 팝업을 닫는 모양이 되어, 어느 것이 무엇을 닫는지
 * 화면에서 읽히지 않는다.
 */
export default function ChatView({ onClose }: { onClose?: () => void } = {}) {
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
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [roomError, setRoomError] = useState<string | null>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const settingsButtonRef = useRef<HTMLButtonElement>(null)
  const inputId = useId()

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
      <div className="chat-screen">
        <p className="empty-state" data-testid="chat-no-room">
          채팅방 목록에서 방을 선택하면 대화가 열립니다.
        </p>
      </div>
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
    <div className="chat-screen">
      {/* ---------------- 헤더 ---------------- */}
      {/* 닫기와 설정이 대화 화면 안에 있다 — 대화가 팝업으로 열리므로 그 팝업을
          여닫는 버튼이 팝업 바깥에 있으면 무엇이 무엇을 닫는지 읽히지 않는다. */}
      <div className="chat-header">
        <button
          type="button"
          className="icon-button"
          data-testid="chat-close"
          aria-label="대화 닫기"
          onClick={() => onClose?.()}
        >
          <CloseIcon />
        </button>

        <strong className="chat-header-title" data-testid="chat-room-name">
          {roomDisplayName(room, myUserId)}
        </strong>

        <button
          type="button"
          className="icon-button"
          ref={settingsButtonRef}
          data-testid="chat-settings-open"
          aria-label="채팅방 설정"
          aria-haspopup="dialog"
          aria-expanded={settingsOpen}
          onClick={() => setSettingsOpen(true)}
        >
          <SettingsIcon />
        </button>
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
        // **`chat-empty`가 남은 공간을 전부 먹는다.** 이 클래스가 없으면 문단이
        // 자기 높이만 차지하고 입력바가 그 바로 아래 — 화면 한가운데 — 에 뜬다.
        // 방금 만든 방에서 반드시 마주치는 상태라 눈에 잘 띈다.
        <p className="empty-state chat-empty" data-testid="chat-empty">
          첫 메시지를 보내보세요.
        </p>
      ) : (
        <ul className="chat-list" data-testid="chat-list">
          {messages.map((message, index) => {
            const mine = message.sender_id === myUserId
            const previous = index === 0 ? null : (messages[index - 1] ?? null)
            // 날짜가 바뀌면 구분선을 넣는다 — 스크롤백에서 "언제 일인지"를
            // 말풍선마다 반복하지 않고 한 줄로 알린다.
            const newDay = previous === null || !isSameDay(previous.created_at, message.created_at)
            // 같은 사람이 같은 분에 연달아 보내면 아바타·이름·시각을 접는다.
            // 메신저의 관용구이며, 반복되는 이름이 대화의 흐름을 끊는다.
            const grouped =
              previous !== null &&
              !newDay &&
              previous.sender_id === message.sender_id &&
              formatClock(previous.created_at) === formatClock(message.created_at)

            return (
              <li key={message.id} data-testid={`chat-message-${message.id}`}>
                {newDay && (
                  <div className="date-divider">
                    <span>{formatDateDivider(message.created_at)}</span>
                  </div>
                )}

                <div
                  className={`msg ${mine ? 'msg-mine' : 'msg-other'}${grouped ? ' msg-grouped' : ''}`}
                >
                  {/* 아바타는 상대에게만. 내 말풍선은 오른쪽 정렬 자체가 화자를 알린다. */}
                  {!mine &&
                    (grouped ? (
                      <span className="avatar avatar-sm" style={{ background: 'transparent' }} />
                    ) : (
                      <span
                        className="avatar avatar-sm"
                        style={{ background: avatarColor(nameOf(message)) }}
                        aria-hidden="true"
                      >
                        {avatarInitial(nameOf(message))}
                      </span>
                    ))}

                  <div className="msg-stack">
                    {/* **별칭만 보인다** (FR-2.4) — `nameOf`가 방 참여자 목록에서
                        호출자 기준으로 해석된 표시명을 준다. */}
                    {!mine && !grouped && <span className="msg-sender">{nameOf(message)}</span>}

                    <div className="msg-line">
                      <div className="bubble">{message.body}</div>
                      <span className="msg-time">{formatClock(message.created_at)}</span>
                    </div>

                    {/* 배지와 신고를 말풍선 아래 줄로 뺀다 — 말풍선 안에 넣으면
                        본문과 섞여 어디까지가 사용자가 쓴 말인지 흐려진다.

                        **둘 다 내 메시지에만 붙는다.** 신고는 원래 자기 신고이고
                        (BR-11.1), 배지도 같은 이유로 내 것에만 둔다 — 검증은 발신자
                        개인 설정이라(FR-6.1) 남의 메시지에 붙은 "검증 안 됨"은 그 사람이
                        토글을 껐거나 그 사람 쪽 호출이 실패했다는 뜻이 되어, 내가 어쩔
                        수 없는 남의 설정 상태를 읽게 한다. 배지가 답해야 하는 질문은
                        "내가 검증받았다고 믿은 이 메시지가 실제로는 아니었는가"다. */}
                    {mine && (
                      <div className="msg-meta">
                        {/* **세 상태에만 붙는다** (BR-8.6). 색이 아니라 아이콘과
                            문구로 알린다 — 색 의존 금지. */}
                        {isUnverified(message.verification_status) && (
                          <span
                            className="badge-warn"
                            data-testid={`chat-unverified-badge-${message.id}`}
                            title="AI 검증을 받지 못한 메시지입니다"
                          >
                            검증 안 됨
                          </span>
                        )}

                        <button
                          type="button"
                          className="link"
                          data-testid={`chat-report-${message.id}`}
                          aria-pressed={message.misdirect_reported_at !== null}
                          onClick={() => void handleReport(message)}
                        >
                          {message.misdirect_reported_at === null ? '잘못 보냈어요' : '신고 취소'}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            )
          })}

          {/* 낙관적 렌더링 (FR-4.3) — 201이 오면 위 목록의 실제 메시지로 교체된다.
              그 외에는 사라지고 입력창의 텍스트가 남는다. */}
          {roomPending.map((item) => (
            <li
              key={item.tempId}
              className="chat-pending"
              data-testid={`chat-pending-${item.tempId}`}
            >
              <div className="msg msg-mine">
                <div className="msg-stack">
                  <div className="msg-line">
                    <div className="bubble">{item.body}</div>
                    <span className="msg-time">보내는 중…</span>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* **콜드스타트 안내** (FR-6.4) — 판정이 왜 안 도는지 알려준다. */}
      {coldStart && room.ai_check_enabled && (
        <p className="chat-hint" data-testid="chat-cold-start">
          이 방의 메시지가 {AI_CONTEXT_N}개 미만이라 아직 AI 검증이 동작하지 않습니다. 대화가
          쌓이면 자동으로 시작됩니다.
        </p>
      )}

      {/* **NFR-5의 상시 고지** — 전문은 설정 팝업 안에 있고 여기엔 한 줄만 남긴다.
          검증이 **켜져 있을 때만** 보이는 것이 요점이다: 외부 전송이 실제로 일어나는
          동안에는 그 사실이 화면에서 사라지지 않아야 하고, 꺼져 있으면 일어나지 않는
          일을 알릴 이유가 없다. 콜드스타트 안내가 이미 떠 있으면 겹치지 않게 접는다 —
          그 상태에서는 판정 자체가 돌지 않아 전송도 없다. */}
      {room.ai_check_enabled && !coldStart && (
        <p className="chat-hint" data-testid="chat-privacy-line">
          AI 검증 켜짐 · 전송 전 최근 {AI_CONTEXT_N}개 메시지 본문이 외부 AI로 전송됩니다
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
          className="send-button"
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

      {/* ---------------- 설정 팝업 ---------------- */}
      {/* **AI 검증 토글의 유일한 자리다** (FR-6.1). 결정 팝업 두 종보다 먼저 그리되,
          동시에 뜰 일은 없다 — 판정 대기 중에는 설정 버튼도 화면에 있지만 팝업이
          모달이라 그 버튼에 닿을 수 없다. */}
      {settingsOpen && (
        <RoomSettingsDialog
          roomName={roomDisplayName(room, myUserId)}
          aiCheckEnabled={room.ai_check_enabled}
          onChangeAiCheck={(enabled) => void handleAiCheck(enabled)}
          onClose={() => setSettingsOpen(false)}
          returnFocusTo={settingsButtonRef}
        />
      )}

      {/* ---------------- 결정 팝업 두 종 ---------------- */}
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
    </div>
  )
}
