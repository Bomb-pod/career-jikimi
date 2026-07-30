import { useEffect, useState } from 'react'

import { connect, disconnect } from './lib/wsClient'
import { useChatStore } from './store/chatStore'
import AuthView from './views/AuthView'
import ChatView from './views/ChatView'
import FriendsView from './views/FriendsView'
import RoomListView from './views/RoomListView'
import ToastHost from './views/ToastHost'

/**
 * 애플리케이션 셸 — **뷰 전환 자리만** 만든다.
 *
 * U1(foundation)은 화면을 만들지 않는다. 네 뷰(`AuthView`·`FriendsView`·
 * `RoomListView`·`ChatView`)는 U3~U5 소관이며(`components.md` § 뷰 컴포넌트),
 * 각 단위가 자기 뷰를 아래 `VIEWS` 항목의 자리에 끼운다.
 *
 * **라우팅 라이브러리를 넣지 않은 이유** — 화면이 넷뿐이라 상태 하나로 충분하다
 * (`components.md`의 열린 항목). 나중에 필요해지면 이 컴포넌트 하나만 바꾼다.
 *
 * U3이 `auth`·`friends`를, U4가 `rooms`를, U5가 `chat`을 채웠다 — 네 자리가 모두 찼다.
 *
 * **WebSocket 연결을 여기서 연다** (FR-5.1). 연결은 앱 전체에 하나이며 payload의
 * `room_id`로 여러 방을 멀티플렉싱한다 — 방 화면에서 열면 방을 옮길 때마다 연결이
 * 끊겼다 붙는다. 토큰이 없으면 열지 않는다.
 *
 * **`ToastHost`도 여기 있다.** 어느 화면에서든 다른 방의 메시지 도착을 알려야
 * 하므로(FR-5.3) 뷰 안에 두면 그 화면을 떠난 동안 알림이 사라진다.
 */

const VIEWS = [
  { id: 'auth', label: '로그인', owner: 'U3 auth-friends' },
  { id: 'friends', label: '친구', owner: 'U3 auth-friends' },
  { id: 'rooms', label: '채팅방', owner: 'U4 rooms-realtime' },
  { id: 'chat', label: '대화', owner: 'U5 messaging' },
] as const

export type ViewId = (typeof VIEWS)[number]['id']

export default function App() {
  const [view, setView] = useState<ViewId>('auth')
  const token = useChatStore((state) => state.auth.token)

  useEffect(() => {
    if (token === null) return
    connect(token)
    // 로그아웃하거나 토큰이 바뀌면 끊는다 — 남겨두면 앞 사용자의 연결로 새 사용자의
    // 메시지가 들어온다.
    return () => disconnect()
  }, [token])

  // `find`가 undefined를 줄 수 있어(noUncheckedIndexedAccess) 폴백을 둔다.
  // 단정(`!`)을 쓰지 않는 이유는 나중에 VIEWS를 동적으로 만들면 그 단정이
  // 조용히 거짓이 되기 때문이다.
  const active = VIEWS.find((candidate) => candidate.id === view) ?? VIEWS[0]

  return (
    <div className="app-shell" data-testid="app-shell">
      <header className="app-header">
        <h1 className="app-title">career-jikimi</h1>
        <p className="app-tagline">채팅방을 착각해 잘못 보내는 메시지를 전송 전에 경고합니다</p>
        <nav className="app-nav" aria-label="화면 전환">
          {VIEWS.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              className="app-nav-item"
              data-testid={`nav-${candidate.id}`}
              aria-current={candidate.id === active.id ? 'page' : undefined}
              onClick={() => setView(candidate.id)}
            >
              {candidate.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="app-main" data-testid={`view-${active.id}`}>
        <h2>{active.label}</h2>
        {active.id === 'auth' && <AuthView />}
        {active.id === 'friends' && <FriendsView />}
        {active.id === 'rooms' && <RoomListView />}
        {active.id === 'chat' && <ChatView />}
      </main>

      {/* 토스트를 누르면 그 방으로 이동한다 (BR-5.9) — 화면 전환까지 여기서 한다.
          **대화 화면으로 보낸다** — 그 방의 메시지를 보러 가는 것이 사용자의 의도다. */}
      <ToastHost onOpenRoom={() => setView('chat')} />
    </div>
  )
}
