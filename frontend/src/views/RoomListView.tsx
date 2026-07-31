import { useEffect, useId, useState, type FormEvent } from 'react'

import * as api from '../lib/apiClient'
import { ROOM_NAME_MAX_LENGTH } from '../lib/constants'
import { avatarColor, avatarInitial } from '../lib/avatar'
import { roomDisplayName } from '../lib/roomName'
import { openRoomWindow } from '../lib/roomWindow'
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
 *
 * **배지를 0일 때 숨기는 이유** — "0"이 붙어 있으면 사용자가 그것을 읽고 판단해야
 * 한다. 없으면 볼 것이 없다는 뜻이 즉시 전달된다.
 *
 * **AI 검증 토글은 이 화면에 없다.** 한때 "현재 방" 카드에 있었으나 대화 화면의
 * 설정 팝업(`RoomSettingsDialog`)으로 옮겼다 — 방 설정은 그 방 안에서 바꾸는 것이
 * 자연스럽고, 같은 개인 설정이 목록과 대화 두 곳에 있으면 사용자가 어느 쪽이 진짜인지
 * 확인하려 든다. 이 화면은 방을 **고르는** 일만 한다.
 *
 * **방을 누르면 새 창이 열린다** (`lib/roomWindow`). 이 창은 목록으로 남는다 —
 * 목록과 대화를 나란히 보는 것이 새 창으로 여는 이유이기 때문이다.
 *
 * 팝업이 차단되면 `window.open()`이 `null`을 주고, 그때만 `enterRoom()`으로 떨어져
 * 셸이 같은 창 안에 대화를 덮는다. 차단된 것을 모른 채 아무 일도 일어나지 않는
 * 화면이 가장 나쁘다.
 */
export default function RoomListView() {
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
  const enterRoom = useChatStore((state) => state.enterRoom)
  const clearUnread = useChatStore((state) => state.clearUnread)

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

  function handleOpenRoom(roomId: number): void {
    const opened = openRoomWindow(roomId)
    if (opened === null) {
      // 팝업이 차단됐다. 같은 창 안에서라도 열어준다 — 아무 일도 일어나지 않는
      // 화면보다 낫다. 기다리지 않는 이유는 히스토리가 늦게 와도 대화는 바로
      // 열려야 하기 때문이다(BR-3.5의 포인터 우선 순서를 `enterRoom`이 지킨다).
      void enterRoom(roomId)
      return
    }
    // 읽는 것은 새 창이고 서버의 `last_read_seq`도 그쪽이 전진시키지만, 이 창의
    // 배지는 자기 상태라 아무도 지워주지 않는다.
    clearUnread(roomId)
  }

  if (token === null) {
    return (
      <section className="panel">
        <p>채팅방을 보려면 먼저 로그인하세요.</p>
      </section>
    )
  }

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
        <form className="room-create" onSubmit={handleCreate}>
          <h2 className="room-create-title">새 채팅방</h2>

          <fieldset className="picker-field">
            <legend>초대할 친구</legend>

            {/* **고른 인원 수를 `aria-live`로 알린다.** 체크박스를 켜고 끄는 변화는
                시각적으로는 즉시 보이지만 스크린리더에는 개별 체크 상태만 읽힌다 —
                "지금 몇 명인가"는 방 만들기 버튼이 켜지는 조건이라 따로 알려야 한다. */}
            <p className="picker-count" aria-live="polite" data-testid="room-create-count">
              {selected.length === 0 ? '아직 고르지 않았습니다' : `${selected.length}명 선택`}
            </p>

            {friends.length === 0 ? (
              <p className="picker-empty" data-testid="room-create-no-friends">
                먼저 친구를 등록하세요.
                <br />
                친구로 등록한 사용자만 초대할 수 있습니다.
              </p>
            ) : (
              <ul className="friend-picker">
                {friends.map((friend) => {
                  const picked = selected.includes(friend.friend_user_id)
                  return (
                    <li key={friend.id}>
                      {/* 다중 선택이므로 체크박스다. div로 만들지 않는다 — 키보드와
                          스크린리더가 그대로 동작해야 한다. 골랐다는 사실은 색뿐
                          아니라 체크 표시로도 드러난다(색 의존 금지). */}
                      <label className={picked ? 'picked' : undefined}>
                        <input
                          type="checkbox"
                          data-testid={`room-create-friend-${friend.friend_user_id}`}
                          checked={picked}
                          onChange={() => toggleFriend(friend.friend_user_id)}
                        />
                        <span
                          className="avatar avatar-sm"
                          style={{ background: avatarColor(friend.alias) }}
                          aria-hidden="true"
                        >
                          {avatarInitial(friend.alias)}
                        </span>
                        {/* 별칭만 보인다 (FR-2.4) — `Friend` 타입에 상대의 이름이 없다. */}
                        <span className="picker-name">{friend.alias}</span>
                      </label>
                    </li>
                  )
                })}
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
              placeholder="예) 개발 3팀"
              aria-describedby={friendsHintId}
            />
            <p className="field-hint" id={friendsHintId}>
              비워두면 참여자 이름으로 표시됩니다.
            </p>
          </div>

          {/* 취소가 왼쪽, 실행이 오른쪽 — 폼의 관용구다. 위 `ConfirmDialog`가 취소를
              DOM 앞에 두는 것과 같은 순서라 Tab 순서도 어긋나지 않는다. */}
          <div className="room-create-actions">
            <button type="button" className="secondary" onClick={() => setCreating(false)}>
              취소
            </button>
            <button
              type="submit"
              className="primary"
              data-testid="room-create-submit"
              // **오류 메시지보다 나은 오류 예방** — 아무도 안 고르면 누를 수 없다.
              disabled={busy || selected.length === 0}
            >
              방 만들기
            </button>
          </div>
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
                  onClick={() => handleOpenRoom(room.id)}
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
    </section>
  )
}
