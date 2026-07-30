import { useEffect, useState } from 'react'

import { connect, disconnect } from './lib/wsClient'
import { useChatStore } from './store/chatStore'
import AuthView from './views/AuthView'
import ChatView from './views/ChatView'
import FriendsView from './views/FriendsView'
import RoomListView from './views/RoomListView'
import ToastHost from './views/ToastHost'

/**
 * 애플리케이션 셸 — 뷰 전환과 세션 수명주기.
 *
 * **라우팅 라이브러리를 넣지 않은 이유** — 화면이 넷뿐이라 상태 하나로 충분하다
 * (`components.md`의 열린 항목). 나중에 필요해지면 이 컴포넌트 하나만 바꾼다.
 *
 * **WebSocket 연결을 여기서 연다** (FR-5.1). 연결은 앱 전체에 하나이며 payload의
 * `room_id`로 여러 방을 멀티플렉싱한다 — 방 화면에서 열면 방을 옮길 때마다 연결이
 * 끊겼다 붙는다. 토큰이 없으면 열지 않는다.
 *
 * **`ToastHost`도 여기 있다.** 어느 화면에서든 다른 방의 메시지 도착을 알려야
 * 하므로(FR-5.3) 뷰 안에 두면 그 화면을 떠난 동안 알림이 사라진다.
 */

/** 로그인해야 들어갈 수 있는 화면. `auth`는 여기 없다. */
const PRIVATE_VIEWS = [
  { id: 'rooms', label: '채팅방' },
  { id: 'chat', label: '대화' },
  { id: 'friends', label: '친구' },
] as const

export type ViewId = 'auth' | (typeof PRIVATE_VIEWS)[number]['id']

/** 로그인 직후·부팅 직후에 여는 화면. 방 목록이 이 앱의 홈이다. */
const HOME_VIEW: ViewId = 'rooms'

export default function App() {
  const [view, setView] = useState<ViewId>('auth')
  const token = useChatStore((state) => state.auth.token)
  const user = useChatStore((state) => state.auth.user)
  const clearAuth = useChatStore((state) => state.clearAuth)
  const hydrateSession = useChatStore((state) => state.hydrateSession)

  // 저장된 토큰이 있으면 부팅 시 한 번 `GET /auth/me`로 사용자를 채우고 홈으로 보낸다.
  //
  // **이것이 없으면 새로고침이 로그인 폼을 보여준다** — 토큰은 살아 있는데 뷰가
  // `auth`로 리셋되기 때문이다. 사용자는 방금 로그인했는데 튕겼다고 느낀다.
  //
  // 의존성 배열이 비어 있는 것이 의도다: 부팅 시 한 번만 돈다. 로그인·로그아웃에
  // 따른 화면 전환은 아래 두 핸들러가 직접 한다.
  useEffect(() => {
    let cancelled = false
    void hydrateSession().then((alive) => {
      if (!cancelled && alive) setView(HOME_VIEW)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (token === null) return
    connect(token)
    // 로그아웃하거나 토큰이 바뀌면 끊는다 — 남겨두면 앞 사용자의 연결로 새 사용자의
    // 메시지가 들어온다.
    return () => disconnect()
  }, [token])

  const signedIn = token !== null
  // 로그아웃 직후에도 비공개 화면에 남아 있으면 그 화면이 401을 맞는다. 토큰이
  // 없으면 무조건 `auth`를 그린다 — 상태를 따로 되돌리지 않아도 화면이 일관된다.
  const active: ViewId = signedIn ? view : 'auth'

  function handleSignedIn() {
    setView(HOME_VIEW)
  }

  function handleSignOut() {
    clearAuth()
    setView('auth')
  }

  return (
    <div className="app-shell" data-testid="app-shell">
      <header className="app-header">
        <h1 className="app-title">career-jikimi</h1>
        <p className="app-tagline">채팅방을 착각해 잘못 보내는 메시지를 전송 전에 경고합니다</p>

        {signedIn && (
          <>
            <nav className="app-nav" aria-label="화면 전환">
              {PRIVATE_VIEWS.map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  className="app-nav-item"
                  data-testid={`nav-${candidate.id}`}
                  aria-current={candidate.id === active ? 'page' : undefined}
                  onClick={() => setView(candidate.id)}
                >
                  {candidate.label}
                </button>
              ))}
            </nav>
            <div className="app-session">
              {/* **`username`을 쓴다.** `CurrentUser`에는 `display_name`이 일부러
                  없다 — 타입에 없으면 화면에 새는 경로가 컴파일에서 막힌다는 U3의
                  설계이고, 그 방어를 이 헤더 하나 때문에 풀 이유가 없다. 내 로그인
                  아이디는 나에게 가장 분명한 식별자이기도 하다.

                  이름이 아직 안 왔을 수도 있다 — `hydrateSession()`이 네트워크 오류로
                  실패하면 `user`가 null인 채로 로그인 상태가 유지된다. 그때 자리를
                  비워두는 편이 "불러오는 중"을 영원히 띄우는 것보다 정직하다. */}
              {user !== null && (
                <span className="app-session-user" data-testid="session-user">
                  {user.username}
                </span>
              )}
              <button
                type="button"
                className="app-signout"
                data-testid="sign-out"
                onClick={handleSignOut}
              >
                로그아웃
              </button>
            </div>
          </>
        )}
      </header>

      <main className="app-main" data-testid={`view-${active}`}>
        {active === 'auth' && <AuthView onSignedIn={handleSignedIn} />}
        {active === 'friends' && <FriendsView />}
        {/* 방을 누르면 곧바로 대화가 열린다 — 목록에 남겨두면 사용자가 "대화" 탭을
            따로 눌러야 하고, 그것이 이 앱의 주 동작이다. */}
        {active === 'rooms' && <RoomListView onOpenRoom={() => setView('chat')} />}
        {active === 'chat' && <ChatView />}
      </main>

      {/* 토스트를 누르면 그 방으로 이동한다 (BR-5.9) — 화면 전환까지 여기서 한다.
          **대화 화면으로 보낸다** — 그 방의 메시지를 보러 가는 것이 사용자의 의도다. */}
      <ToastHost onOpenRoom={() => setView('chat')} />
    </div>
  )
}
