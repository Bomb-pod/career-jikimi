import { useEffect, useId, useState, type FormEvent } from 'react'

import * as api from '../lib/apiClient'
import { ALIAS_MAX_LENGTH, USERNAME_MAX_LENGTH } from '../lib/constants'
import { useChatStore } from '../store/chatStore'

/**
 * 친구 검색·등록·별칭 수정 화면 (`business-logic-model.md` § FriendsView).
 *
 * | 영역 | 내용 |
 * |---|---|
 * | 검색 | 아이디 입력 + 검색 버튼. 결과는 0명 또는 1명 |
 * | 검색 결과 | 아이디 표시 + **별칭 입력칸** + "추가" |
 * | 목록 | 별칭 목록. 각 항목에 "이름 수정" |
 * | 비어 있음 | "아직 친구가 없습니다. 아이디로 검색해 추가하세요." |
 *
 * **별칭 입력칸이 검색 결과 안에 있어야 한다.** "추가"를 누른 뒤 별칭을 묻는 2단계로
 * 만들면 사용자가 별칭이 필수라는 것을 누른 다음에야 알게 된다. 입력칸이 비어 있으면
 * 추가 버튼을 비활성화한다 — 오류 메시지보다 나은 오류 예방이다.
 *
 * **목록에는 상대의 `display_name`을 절대 보여주지 않는다** (FR-2.4). 애초에
 * `apiClient`의 `Friend` 타입에 그 필드가 없어 렌더링할 방법이 없다.
 */
export default function FriendsView() {
  const token = useChatStore((state) => state.auth.token)
  const friends = useChatStore((state) => state.friends)
  const setFriends = useChatStore((state) => state.setFriends)
  const upsertFriend = useChatStore((state) => state.upsertFriend)

  const [query, setQuery] = useState('')
  const [searched, setSearched] = useState(false)
  const [found, setFound] = useState<api.SearchedUser | null>(null)
  const [alias, setAlias] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  /** 지금 이름을 수정하고 있는 friendship. `null`이면 수정 중이 아니다. */
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingAlias, setEditingAlias] = useState('')

  const searchId = useId()
  const aliasId = useId()
  const aliasHintId = useId()
  const editHintId = useId()

  useEffect(() => {
    // 토큰이 없으면 요청하지 않는다 — 401을 받아 오류 문구를 띄우는 것보다,
    // 애초에 묻지 않는 편이 낫다.
    if (token === null) return

    let cancelled = false
    void (async () => {
      try {
        const result = await api.listFriends()
        // 응답이 도착하기 전에 화면을 떠났으면 상태를 건드리지 않는다.
        if (cancelled) return
        if (result.ok) setFriends(result.data.friends)
        else setError(result.error.message)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : '목록을 불러올 수 없습니다')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, setFriends])

  async function handleSearch(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setError(null)
    setBusy(true)
    try {
      const result = await api.searchUser(query)
      if (!result.ok) {
        setError(result.error.message)
        return
      }
      // **결과가 없는 것은 오류가 아니다** (BR-2.1). 서버가 200 + null을 주고
      // 화면은 "결과 없음"을 보여준다.
      setFound(result.data.user)
      setSearched(true)
      setAlias('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '검색할 수 없습니다')
    } finally {
      setBusy(false)
    }
  }

  async function handleAdd(event: FormEvent) {
    event.preventDefault()
    if (busy || found === null || alias.trim() === '') return
    setError(null)
    setBusy(true)
    try {
      const result = await api.addFriend(found.username, alias)
      if (!result.ok) {
        // 409 `ALREADY_FRIEND`도 여기로 온다 — apiClient가 던지지 않으므로
        // 폼 오류 문구와 같은 경로로 처리된다.
        setError(result.error.message)
        return
      }
      upsertFriend(result.data)
      // 검색 결과를 비운다 — 추가한 사람이 그대로 남아 있으면 한 번 더 누르게 되고,
      // 그 요청은 409가 된다.
      setFound(null)
      setSearched(false)
      setQuery('')
      setAlias('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '등록할 수 없습니다')
    } finally {
      setBusy(false)
    }
  }

  async function handleRename(event: FormEvent, friendshipId: number) {
    event.preventDefault()
    if (busy || editingAlias.trim() === '') return
    setError(null)
    setBusy(true)
    try {
      const result = await api.updateAlias(friendshipId, editingAlias)
      if (!result.ok) {
        setError(result.error.message)
        return
      }
      upsertFriend(result.data)
      setEditingId(null)
      setEditingAlias('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '수정할 수 없습니다')
    } finally {
      setBusy(false)
    }
  }

  if (token === null) {
    return (
      <section className="panel">
        <p>친구 목록을 보려면 먼저 로그인하세요.</p>
      </section>
    )
  }

  const aliasIsEmpty = alias.trim() === ''

  return (
    <section className="panel">
      <div className="form-error" aria-live="polite" data-testid="friends-error">
        {error}
      </div>

      {/* ---------------- 검색 ---------------- */}
      <form className="form form-inline" onSubmit={handleSearch}>
        <div className="field">
          <label htmlFor={searchId}>친구 아이디</label>
          <input
            id={searchId}
            data-testid="friends-search-input"
            type="text"
            maxLength={USERNAME_MAX_LENGTH}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            required
          />
        </div>
        <button type="submit" className="primary" data-testid="friends-search-submit" disabled={busy}>
          검색
        </button>
      </form>

      {/* 검색 결과 개수를 스크린리더에 알린다. 시각 사용자는 아래 카드로 알지만
          결과가 0명일 때는 화면에 카드가 생기지 않아 변화가 announce되지 않는다. */}
      <span className="visually-hidden" aria-live="polite" data-testid="friends-search-status">
        {searched ? (found === null ? '결과 없음' : '1명 찾음') : ''}
      </span>

      {searched && found === null && (
        <p className="muted" data-testid="friends-search-empty">
          그 아이디의 사용자를 찾을 수 없습니다.
        </p>
      )}

      {found !== null && (
        <form className="result-card" onSubmit={handleAdd}>
          {/* 표시하는 것은 사용자가 방금 입력한 **아이디**다. 상대가 스스로 정한 이름은
              보여주지 않는다 (FR-2.4). */}
          <p className="result-name" data-testid="friends-search-result">
            {found.username}
          </p>
          <div className="field">
            <label htmlFor={aliasId}>이 사람에게 붙일 이름 (필수)</label>
            <input
              id={aliasId}
              data-testid="friends-add-alias-input"
              type="text"
              maxLength={ALIAS_MAX_LENGTH}
              value={alias}
              onChange={(event) => setAlias(event.target.value)}
              aria-describedby={aliasHintId}
              required
            />
            <p className="field-hint" id={aliasHintId}>
              친구 목록에는 여기 적은 이름만 표시됩니다.
            </p>
          </div>
          <button
            type="submit"
            className="primary"
            data-testid="friends-add-submit"
            // **오류 메시지보다 나은 오류 예방** — 별칭이 비면 누를 수 없다.
            disabled={busy || aliasIsEmpty}
            aria-describedby={aliasIsEmpty ? aliasHintId : undefined}
          >
            추가
          </button>
        </form>
      )}

      {/* ---------------- 목록 ---------------- */}
      <h3>내 친구</h3>
      {friends.length === 0 ? (
        <p className="muted" data-testid="friends-empty">
          아직 친구가 없습니다. 아이디로 검색해 추가하세요.
        </p>
      ) : (
        <ul className="friend-list" data-testid="friends-list">
          {friends.map((friend) => (
            <li key={friend.id} data-testid={`friends-list-item-${friend.id}`}>
              {editingId === friend.id ? (
                <form className="form-inline" onSubmit={(event) => handleRename(event, friend.id)}>
                  <div className="field">
                    <label htmlFor={`${editHintId}-${friend.id}`}>새 이름</label>
                    <input
                      id={`${editHintId}-${friend.id}`}
                      data-testid={`friends-alias-input-${friend.id}`}
                      type="text"
                      maxLength={ALIAS_MAX_LENGTH}
                      value={editingAlias}
                      onChange={(event) => setEditingAlias(event.target.value)}
                      required
                    />
                  </div>
                  <button
                    type="submit"
                    className="primary"
                    data-testid={`friends-alias-save-${friend.id}`}
                    disabled={busy || editingAlias.trim() === ''}
                  >
                    저장
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => {
                      setEditingId(null)
                      setEditingAlias('')
                    }}
                  >
                    취소
                  </button>
                </form>
              ) : (
                <>
                  {/* 별칭만 보인다. `Friend` 타입에 상대의 이름이 없어 다른 것을
                      보여줄 방법이 없다 (FR-2.4). */}
                  <span className="friend-alias">{friend.alias}</span>
                  <button
                    type="button"
                    className="secondary"
                    data-testid={`friends-alias-edit-${friend.id}`}
                    onClick={() => {
                      setEditingId(friend.id)
                      // 기존 값을 채워 넣는다 — 수정은 대개 일부만 바꾸는 일이다.
                      setEditingAlias(friend.alias)
                    }}
                  >
                    이름 수정
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
