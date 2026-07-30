import { useEffect, useId, useState, type FormEvent } from 'react'

import * as api from '../lib/apiClient'
import { ROOM_NAME_MAX_LENGTH } from '../lib/constants'
import { avatarColor, avatarInitial } from '../lib/avatar'
import { roomDisplayName } from '../lib/roomName'
import { formatListTime } from '../lib/time'
import { useChatStore } from '../store/chatStore'

/**
 * 방 목록·생성·입장 화면 (`business-logic-model.md` § RoomListView).
 *
 * | 영역 | 내용 |
 * |---|---|
 * | 목록 | 방 이름(없으면 참여자 표시명 조립) + 안 읽은 배지 |
 * | 배지 | **0이면 표시하지 않는다** |
 * | 생성 | 친구 다중 선택 + 방 이름(선택) |
 * | 비어 있음 | "채팅방이 없습니다. 친구를 초대해 만들어보세요." |
 * | 배너 | `session_replaced` 시 상단 고정 (BR-5.5) |
 * | 현재 방 | 입장한 방의 **내** AI 검증 토글 (FR-6.1) |
 *
 * **배지를 0일 때 숨기는 이유** — "0"이 붙어 있으면 사용자가 그것을 읽고 판단해야
 * 한다. 없으면 볼 것이 없다는 뜻이 즉시 전달된다.
 *
 * **AI 토글이 여기 있는 이유** — 개인 설정이고 방 단위다(FR-6.1). 대화 화면은 U5
 * 소관이므로, 입장한 방의 설정을 이 화면의 "현재 방" 영역에서 바꾼다. `data-testid`가
 * `room-ai-toggle`(방 id 없음)인 것도 화면에 하나만 있다는 뜻이다.
 */
/**
 * `onOpenRoom` — 방에 입장한 직후 호출한다. App 셸이 대화 화면으로 옮긴다.
 *
 * **입장과 화면 전환을 나눈 이유** — 입장은 스토어의 일(포인터 이동 + 히스토리
 * 조회, BR-3.5)이고 어느 화면을 그릴지는 셸의 일이다. `ToastHost`도 같은 모양의
 * 콜백을 받는다.
 */
export default function RoomListView({ onOpenRoom }: { onOpenRoom?: (roomId: number) => void }) {
  const token = useChatStore((state) => state.auth.token)
  const myUserId = useChatStore((state) => state.auth.user?.id ?? null)
  const friends = useChatStore((state) => state.friends)
  const rooms = useChatStore((state) => state.rooms)
  const unread = useChatStore((state) => state.unread)
  const currentRoomId = useChatStore((state) => state.currentRoomId)
  const sessionReplaced = useChatStore((state) => state.sessionReplaced)
  const wsStatus = useChatStore((state) => state.wsStatus)
  const setFriends = useChatStore((state) => state.setFriends)
  const setRooms = useChatStore((state) => state.setRooms)
  const upsertRoom = useChatStore((state) => state.upsertRoom)
  const setAiCheck = useChatStore((state) => state.setAiCheck)
  const enterRoom = useChatStore((state) => state.enterRoom)
  const leaveRoom = useChatStore((state) => state.leaveRoom)

  const [creating, setCreating] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const nameId = useId()
  const friendsHintId = useId()

  useEffect(() => {
    // 토큰이 없으면 요청하지 않는다 — 401을 받아 오류 문구를 띄우는 것보다,
    // 애초에 묻지 않는 편이 낫다.
    if (token === null) return

    let cancelled = false
    void (async () => {
      try {
        // 방 목록과 친구 목록을 함께 불러온다 — 생성 폼이 친구 목록을 필요로 하고,
        // 사용자가 폼을 열고 나서야 불러오면 그 순간 화면이 비어 보인다.
        const [roomResult, friendResult] = await Promise.all([api.listRooms(), api.listFriends()])
        if (cancelled) return
        if (roomResult.ok) setRooms(roomResult.data.rooms)
        else setError(roomResult.error.message)
        if (friendResult.ok) setFriends(friendResult.data.friends)
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : '방 목록을 불러올 수 없습니다')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, setRooms, setFriends])

  function toggleFriend(friendUserId: number): void {
    setSelected((current) =>
      current.includes(friendUserId)
        ? current.filter((item) => item !== friendUserId)
        : [...current, friendUserId],
    )
  }

  async function handleCreate(event: FormEvent): Promise<void> {
    event.preventDefault()
    // **오류 메시지보다 나은 오류 예방** — 아무도 안 고르면 누를 수 없다 (BR-3.1).
    if (busy || selected.length === 0) return
    setError(null)
    setBusy(true)
    try {
      const trimmed = name.trim()
      const result = await api.createRoom(selected, trimmed === '' ? null : trimmed)
      if (!result.ok) {
        setError(result.error.message)
        return
      }
      // 생성 응답이 그 방의 최신 상태를 그대로 준다 — 목록을 다시 부르지 않는다.
      upsertRoom({ ...result.data, unread_count: 0 })
      setCreating(false)
      setSelected([])
      setName('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '방을 만들 수 없습니다')
    } finally {
      setBusy(false)
    }
  }

  async function handleAiCheck(roomId: number, enabled: boolean): Promise<void> {
    setError(null)
    // 낙관적으로 먼저 바꾼다 — 체크박스가 응답을 기다리며 멈춰 있으면 고장으로 보인다.
    setAiCheck(roomId, enabled)
    try {
      const result = await api.setAiCheck(roomId, enabled)
      if (!result.ok) {
        setAiCheck(roomId, !enabled)
        setError(result.error.message)
      }
    } catch (caught) {
      setAiCheck(roomId, !enabled)
      setError(caught instanceof Error ? caught.message : '설정을 바꿀 수 없습니다')
    }
  }

  if (token === null) {
    return (
      <section className="panel">
        <p>채팅방을 보려면 먼저 로그인하세요.</p>
      </section>
    )
  }

  const current = rooms.find((room) => room.id === currentRoomId) ?? null

  return (
    <section className="panel">
      {/* **BR-5.5의 배너.** 밀려난 탭은 재연결하지 않으므로 이 문구가 유일한 안내다.
          전송은 HTTP라 여전히 동작한다 — 그래서 "죽었다"가 아니라 "새로고침하라"다. */}
      {sessionReplaced && (
        <p className="banner" role="status" data-testid="session-replaced-banner">
          다른 탭에서 접속했습니다 — 이 탭에서 계속하려면 새로고침하세요
        </p>
      )}

      {wsStatus === 'reconnecting' && (
        <p className="banner banner-muted" role="status" data-testid="ws-reconnecting-banner">
          연결이 끊겨 다시 연결하는 중입니다
        </p>
      )}

      <div className="form-error" aria-live="polite" data-testid="rooms-error">
        {error}
      </div>

      {/* ---------------- 생성 ---------------- */}
      {creating ? (
        <form className="form" onSubmit={handleCreate}>
          <fieldset className="field">
            <legend>초대할 친구</legend>
            {friends.length === 0 ? (
              <p className="muted" data-testid="room-create-no-friends">
                먼저 친구를 등록하세요. 친구로 등록한 사용자만 초대할 수 있습니다.
              </p>
            ) : (
              <ul className="friend-picker">
                {friends.map((friend) => (
                  <li key={friend.id}>
                    {/* 다중 선택이므로 체크박스다. div로 만들지 않는다 — 키보드와
                        스크린리더가 그대로 동작해야 한다. */}
                    <label>
                      <input
                        type="checkbox"
                        data-testid={`room-create-friend-${friend.friend_user_id}`}
                        checked={selected.includes(friend.friend_user_id)}
                        onChange={() => toggleFriend(friend.friend_user_id)}
                      />
                      {friend.alias}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>

          <div className="field">
            <label htmlFor={nameId}>방 이름 (선택)</label>
            <input
              id={nameId}
              data-testid="room-create-name"
              type="text"
              maxLength={ROOM_NAME_MAX_LENGTH}
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-describedby={friendsHintId}
            />
            <p className="field-hint" id={friendsHintId}>
              비워두면 참여자 이름으로 표시됩니다.
            </p>
          </div>

          <button
            type="submit"
            className="primary"
            data-testid="room-create-submit"
            disabled={busy || selected.length === 0}
          >
            방 만들기
          </button>
          <button type="button" className="secondary" onClick={() => setCreating(false)}>
            취소
          </button>
        </form>
      ) : (
        // 작은 액션 줄에 둔다 — 메신저는 "새 채팅"을 전폭 버튼이 아니라 작게
        // 두고 목록을 주인공으로 남긴다.
        <div className="list-actions">
          <button
            type="button"
            className="primary"
            data-testid="room-create-open"
            onClick={() => setCreating(true)}
          >
            + 새 채팅방
          </button>
        </div>
      )}

      {/* ---------------- 목록 ---------------- */}
      {rooms.length === 0 ? (
        <p className="empty-state" data-testid="rooms-empty">
          채팅방이 없습니다.
          <br />
          친구를 초대해 만들어보세요.
        </p>
      ) : (
        <ul className="list" data-testid="room-list">
          {rooms.map((room) => {
            const count = unread[room.id] ?? 0
            const label = roomDisplayName(room, myUserId)
            // 참여자 수를 부제로 둔다 — 마지막 메시지 미리보기는 서버가 주지
            // 않는다(`RoomSummary`에 없다). 자리를 비우면 행이 무너져 보인다.
            const others = room.members.filter((member) => member.user_id !== myUserId)
            return (
              <li key={room.id} data-testid={`room-list-item-${room.id}`}>
                <button
                  type="button"
                  className="row"
                  aria-current={room.id === currentRoomId ? 'true' : undefined}
                  onClick={() => {
                    // 화면 전환을 기다리지 않는다 — 히스토리가 늦게 와도 대화 화면은
                    // 바로 열려야 한다. 그 화면이 자기 로딩 상태를 그린다.
                    void enterRoom(room.id)
                    onOpenRoom?.(room.id)
                  }}
                >
                  <span
                    className="avatar"
                    style={{ background: avatarColor(label) }}
                    aria-hidden="true"
                  >
                    {avatarInitial(label)}
                  </span>

                  <span className="row-body">
                    <span className="row-title">{label}</span>
                    {/* 부제는 **이름이 있는 방에만** 참여자를 나열한다. 이름이 없는
                        방은 제목이 이미 참여자 목록이라(`roomDisplayName`) 그대로 두면
                        같은 이름이 두 줄에 겹친다.

                        **별칭만 보인다** (FR-2.4) — 서버가 호출자 기준으로 해석해
                        보낸 `display_name`이며 상대가 스스로 정한 이름이 아니다. */}
                    <span className="row-sub">
                      {others.length === 0
                        ? '나만 있는 방'
                        : room.name === null
                          ? `${others.length + 1}명`
                          : others.map((member) => member.display_name).join(', ')}
                    </span>
                  </span>

                  <span className="row-side">
                    <span className="row-time">{formatListTime(room.created_at)}</span>
                    {/* **0이면 아예 렌더링하지 않는다.** 숫자만 두지 않고 aria-label을
                        붙이는 이유 — 스크린리더가 "3"만 읽으면 무엇의 3인지 알 수 없다. */}
                    {count > 0 && (
                      <span
                        className="badge-unread"
                        data-testid={`room-unread-badge-${room.id}`}
                        aria-label={`안 읽은 메시지 ${count}개`}
                      >
                        {count}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {/* ---------------- 현재 방 ---------------- */}
      {current !== null && (
        <div className="card" data-testid="room-current" style={{ margin: '0.875rem' }}>
          <p className="section-title" style={{ marginTop: 0 }}>
            {roomDisplayName(current, myUserId)}
          </p>
          {/* 진짜 체크박스 + 보이는 라벨. div로 만들면 키보드로 조작할 수 없고
              스크린리더가 상태를 읽지 못한다. */}
          <label className="toggle-row">
            <input
              type="checkbox"
              data-testid="room-ai-toggle"
              checked={current.ai_check_enabled}
              onChange={(event) => void handleAiCheck(current.id, event.target.checked)}
            />
            이 방에서 AI 검증 사용
          </label>
          <p className="field-hint">
            내 메시지에만 적용됩니다. 다른 참여자의 설정과 무관합니다.
          </p>
          <button type="button" className="secondary" onClick={() => leaveRoom()}>
            목록으로
          </button>
        </div>
      )}
    </section>
  )
}
