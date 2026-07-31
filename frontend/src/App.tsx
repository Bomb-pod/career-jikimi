import { useEffect, useRef, useState } from 'react'

import * as api from './lib/apiClient'
import { announceRoomViewing, watchViewedRooms } from './lib/viewedRooms'
import { readRoomFromUrl } from './lib/roomWindow'
import { connect, disconnect } from './lib/wsClient'
import { useChatStore } from './store/chatStore'
import AuthView from './views/AuthView'
import ChatView from './views/ChatView'
import FriendsView from './views/FriendsView'
import { FriendsIcon, RoomsIcon, SignOutIcon } from './views/Icons'
import RoomListView from './views/RoomListView'
import ToastHost from './views/ToastHost'

/**
 * 애플리케이션 셸 — 상단 바 + 본문 + 하단 탭, 그리고 세션 수명주기.
 *
 * **메신저 관용구를 따른다** — 하단 탭이 1차 내비게이션이고 상단 바가 현재 화면을
 * 알린다. 사용자가 새로 배울 것이 없는 형태가 데모에서 가장 빠르게 읽힌다.
 *
 * **대화는 탭이 아니라 새 창이다.** 방을 고르는 것과 대화하는 것은 한 흐름이지 나란한
 * 두 목적지가 아니다 — 탭으로 두면 "대화" 탭을 눌렀는데 아무 방도 안 열려 있는 빈
 * 화면이 존재하게 되고, 그 화면은 사용자가 도달할 이유가 없는 상태다. 목록에서 방을
 * 누르면 `?room=<id>`를 단 **별도의 창**이 뜬다 (`lib/roomWindow`).
 *
 * 그래서 이 컴포넌트에는 모습이 둘이다:
 *
 * | 창 | 조건 | 그리는 것 |
 * |---|---|---|
 * | 앱 창 | 주소에 `?room=` 없음 | 상단 바 + 친구/채팅 + 하단 탭 |
 * | 대화 창 | `?room=<id>` | **대화 하나뿐** — 탭도 상단 바도 없다 |
 *
 * 대화 창에 탭바를 남기면 그 창에서 친구 목록으로 갈 수 있게 되고, 창의 목적이
 * 흐려진다. 방 하나를 보는 창이라는 것이 그 창의 전부다.
 *
 * **같은 창 안의 오버레이도 남겨 두었다.** 팝업이 차단되면 `window.open()`이 `null`을
 * 주고, 그때 `RoomListView`가 `enterRoom()`으로 떨어진다 — 그 경로에서 `currentRoomId`가
 * 채워지면 이 셸이 목록 위에 대화를 덮는다. 차단된 것을 모른 채 아무 일도 일어나지
 * 않는 화면이 가장 나쁘다.
 *
 * **여는 조건이 `currentRoomId`다.** 스토어가 이미 `null`을 "목록 화면"으로 정의해
 * 두었으므로(`chatStore`) 뷰 상태를 따로 만들지 않는다. 상태가 둘이면 방을 나갔는데
 * 팝업이 남거나 그 반대가 된다.
 *
 * **라우팅 라이브러리를 넣지 않은 이유** — 화면이 셋뿐이라 상태 하나로 충분하다
 * (`components.md`의 열린 항목). 나중에 필요해지면 이 컴포넌트 하나만 바꾼다.
 * 지금 넣으면 `/rooms`·`/friends`가 같은 이름의 API와 정면으로 충돌한다.
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
  { id: 'friends', label: '친구', Icon: FriendsIcon },
  { id: 'rooms', label: '채팅', Icon: RoomsIcon },
] as const

export type ViewId = 'auth' | (typeof PRIVATE_VIEWS)[number]['id']

/** 로그인 직후·부팅 직후에 여는 화면. 채팅 목록이 이 앱의 홈이다. */
const HOME_VIEW: ViewId = 'rooms'

const TITLES: Record<ViewId, string> = {
  auth: 'career-jikimi',
  friends: '친구',
  rooms: '채팅',
}

export default function App() {
  const [view, setView] = useState<ViewId>('auth')
  const token = useChatStore((state) => state.auth.token)
  const user = useChatStore((state) => state.auth.user)
  const currentRoomId = useChatStore((state) => state.currentRoomId)
  const clearAuth = useChatStore((state) => state.clearAuth)
  const hydrateSession = useChatStore((state) => state.hydrateSession)
  const leaveRoom = useChatStore((state) => state.leaveRoom)
  const enterRoom = useChatStore((state) => state.enterRoom)
  const upsertRoom = useChatStore((state) => state.upsertRoom)
  const setRoomsViewedElsewhere = useChatStore((state) => state.setRoomsViewedElsewhere)
  const markCurrentRoomRead = useChatStore((state) => state.markCurrentRoomRead)

  /** 대화 전용 창이 방을 불러오지 못한 이유. `null`이면 아직 문제가 없다. */
  const [roomWindowError, setRoomWindowError] = useState<string | null>(null)

  // **부팅 시 한 번만 읽는다.** `useRef`인 이유는 이 창의 정체가 수명 내내 바뀌지
  // 않기 때문이다 — 대화 창은 끝까지 대화 창이다. state로 두면 재렌더마다 주소를
  // 다시 파싱하고, 그 값이 아래 effect의 의존성이 되어 방에 다시 입장하게 된다.
  const windowRoomId = useRef(readRoomFromUrl()).current
  const isRoomWindow = windowRoomId !== null

  // 저장된 토큰이 있으면 부팅 시 한 번 `GET /auth/me`로 사용자를 채우고 홈으로 보낸다.
  //
  // **이것이 없으면 새로고침이 로그인 폼을 보여준다** — 토큰은 살아 있는데 뷰가
  // `auth`로 리셋되기 때문이다. 사용자는 방금 로그인했는데 튕겼다고 느낀다.
  //
  // 의존성 배열이 비어 있는 것이 의도다: 부팅 시 한 번만 돈다. 로그인·로그아웃에
  // 따른 화면 전환은 아래 두 핸들러가 직접 한다.
  useEffect(() => {
    let cancelled = false
    void hydrateSession().then(async (alive) => {
      if (cancelled || !alive) return
      setView(HOME_VIEW)
      if (windowRoomId === null) return

      // **대화 창은 방 하나를 직접 불러온다.**
      //
      // 이 창에는 방 목록 화면이 없어 `rooms`가 비어 있다. `enterRoom()`은
      // 포인터와 히스토리만 다루고 방 자체(이름·참여자·내 토글)는 목록이 채우던
      // 값이라, 이 조회를 빠뜨리면 `ChatView`가 방을 찾지 못해 "방을 선택하세요"만
      // 그린다 — 대화 창인데 대화가 없는 화면이 된다.
      //
      // 세션 복구 뒤여야 한다 — 토큰이 스토어에 들어오기 전에 부르면 401을 맞는다.
      //
      // 목록 전체(`listRooms`)가 아니라 이 방 하나만 부르는 이유는 이 창이 다른
      // 방을 그릴 일이 없기 때문이다. 방이 서른 개인 사용자의 창 하나를 여는 데
      // 서른 개를 받아올 이유가 없다.
      if (!cancelled) await openWindowRoom(windowRoomId)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * 대화 창이 자기 방을 불러와 들어간다.
   *
   * 부팅 직후와 **이 창에서 로그인한 직후** 두 곳에서 부른다. 부팅 effect에만 두면,
   * 토큰이 만료된 채로 열린 창에서 로그인해도 방이 열리지 않는다 — 그 effect는
   * 마운트 시 한 번만 돌기 때문이다.
   */
  async function openWindowRoom(roomId: number): Promise<void> {
    const result = await api.getRoom(roomId)
    if (!result.ok) {
      // 없는 방이거나 참여자가 아니면 403이다 (BR-3.3). 주소를 손으로 고친
      // 경우가 그렇고, 빈 대화로 두면 원인이 화면 어디에도 없다.
      setRoomWindowError(result.error.message)
      return
    }
    // `unread_count`는 상세 응답에 없다 — 이 창은 그 방을 보고 있으므로 0이다.
    upsertRoom({ ...result.data, unread_count: 0 })
    void enterRoom(roomId)
  }

  useEffect(() => {
    if (token === null) return
    connect(token)
    // 로그아웃하거나 토큰이 바뀌면 끊는다 — 남겨두면 앞 사용자의 연결로 새 사용자의
    // 메시지가 들어온다.
    return () => disconnect()
  }, [token])

  // ------------------------------------------------------------------------
  // 창끼리 "어느 방을 보고 있는지" 알리기 (`lib/viewedRooms`)
  // ------------------------------------------------------------------------
  // 두 창은 별개 문서라 서로를 모른다. 이것이 없으면 대화 창에서 보고 있는 방의
  // 메시지가 목록 창의 배지를 올린다 — 보고 있는데 안 읽은 개수가 늘어난다.
  //
  // 창의 성격에 따라 역할이 갈린다: 대화 창은 **알리고**, 앱 창은 **듣는다**.
  // 한 창이 둘 다 할 이유가 없고, `BroadcastChannel`은 자기가 보낸 메시지를
  // 자기에게 주지 않으므로 섞어도 자기 방을 오해하지는 않는다.
  //
  // 기준은 창이 열려 있는지가 아니라 **포커스가 있는지**다. 대화 창을 한쪽에 띄워
  // 두고 다른 창에서 일하는 동안 온 메시지는 배지로 알려져야 한다.
  useEffect(() => {
    if (windowRoomId === null) return
    // 다시 앞으로 나오면 그동안 밀린 읽음 처리를 한 번에 민다.
    return announceRoomViewing(windowRoomId, markCurrentRoomRead)
  }, [windowRoomId, markCurrentRoomRead])

  useEffect(() => {
    if (windowRoomId !== null) return
    return watchViewedRooms(setRoomsViewedElsewhere)
  }, [windowRoomId, setRoomsViewedElsewhere])

  const signedIn = token !== null
  // 로그아웃 직후에도 비공개 화면에 남아 있으면 그 화면이 401을 맞는다. 토큰이
  // 없으면 무조건 `auth`를 그린다 — 상태를 따로 되돌리지 않아도 화면이 일관된다.
  const active: ViewId = signedIn ? view : 'auth'
  const title = TITLES[active]

  // 로그아웃 직후에도 방 포인터가 남아 있으면 팝업이 그대로 떠 있다. `clearAuth()`가
  // `currentRoomId`를 비우지만, 그 순서에 기대지 않고 여기서도 로그인 여부를 본다.
  const chatOpen = signedIn && currentRoomId !== null

  function handleSignedIn() {
    setView(HOME_VIEW)
    // 대화 창에서 로그인했으면 그대로 그 방으로 들어간다 — 목록이 없는 창이라
    // 여기서 보내주지 않으면 갈 곳이 없다.
    if (windowRoomId !== null) void openWindowRoom(windowRoomId)
  }

  function handleSignOut() {
    clearAuth()
    setView('auth')
  }

  // ------------------------------------------------------------------------
  // 대화 전용 창 — `?room=<id>`로 열린 창
  // ------------------------------------------------------------------------
  // 탭바도 상단 바도 없다. 방 하나를 보는 창이라는 것이 이 창의 전부이며, 여기서
  // 친구 목록으로 갈 수 있으면 그 목적이 흐려진다. 로그인은 부모 창과 같은 오리진의
  // `localStorage`를 공유하므로 대개 이미 되어 있다 — 안 되어 있으면(토큰 만료 등)
  // 이 창에서 바로 로그인하고, 위 effect가 아니라 아래 분기가 방으로 보낸다.
  if (isRoomWindow) {
    return (
      <div className="app-shell app-shell-room" data-testid="app-shell">
        {!signedIn ? (
          <main className="app-main" data-testid="view-auth">
            <AuthView onSignedIn={handleSignedIn} />
          </main>
        ) : roomWindowError !== null ? (
          <main className="app-main">
            <section className="panel" data-testid="room-window-error">
              <p className="empty-state">{roomWindowError}</p>
              <button type="button" className="secondary" onClick={() => window.close()}>
                창 닫기
              </button>
            </section>
          </main>
        ) : currentRoomId === null ? (
          // 조회가 끝나기 전의 짧은 순간. `ChatView`를 먼저 그리면 그 사이 "방을
          // 선택하세요"가 번쩍이는데, 목록이 없는 이 창에서는 뜻이 통하지 않는 문구다.
          <main className="app-main">
            <p className="empty-state" data-testid="room-window-loading">
              대화를 불러오는 중입니다…
            </p>
          </main>
        ) : (
          <div className="chat-window" data-testid="chat-window">
            {/* `window.close()`가 이 창의 "닫기"다. 스크립트로 연 창이라 브라우저가
                닫기를 허용한다 — 사용자가 주소를 직접 친 창이었다면 무시되고, 그때는
                탭 닫기 버튼이 남는다. */}
            <ChatView onClose={() => window.close()} />
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="app-shell" data-testid="app-shell">
      <header className="app-topbar">
        <div className="app-topbar-title">
          <h1 style={{ margin: 0, fontSize: 'inherit', fontWeight: 'inherit' }}>{title}</h1>
          {signedIn && user !== null && (
            // **`username`을 쓴다.** `CurrentUser`에는 `display_name`이 일부러 없다 —
            // 타입에 없으면 화면에 새는 경로가 컴파일에서 막힌다는 U3의 설계이고,
            // 그 방어를 이 헤더 하나 때문에 풀 이유가 없다.
            <p className="app-topbar-sub" data-testid="session-user">
              {user.username}
            </p>
          )}
        </div>

        {signedIn && (
          <button
            type="button"
            className="icon-button"
            data-testid="sign-out"
            aria-label="로그아웃"
            title="로그아웃"
            onClick={handleSignOut}
          >
            <SignOutIcon />
          </button>
        )}
      </header>

      <main className="app-main" data-testid={`view-${active}`}>
        {active === 'auth' && <AuthView onSignedIn={handleSignedIn} />}
        {active === 'friends' && <FriendsView />}
        {/* 방을 누르면 `enterRoom()`이 포인터를 옮기고, 그 포인터가 아래 팝업을
            연다. 이 화면은 뷰를 바꾸지 않는다 — 닫으면 목록이 그대로 있어야 한다. */}
        {active === 'rooms' && <RoomListView />}
      </main>

      {/* ---------------- 대화 오버레이 (팝업 차단 시의 대체 경로) ---------------- */}
      {/* 평소에는 뜨지 않는다 — 방을 누르면 새 창이 열리고 이 창의 `currentRoomId`는
          `null`로 남는다. `window.open()`이 차단돼 `null`을 준 경우에만
          `RoomListView`가 `enterRoom()`으로 떨어지고 여기가 그린다.

          탭바 위를 덮는다 — 대화 중에는 탭 전환이 목적이 아니고, 덮지 않으면
          하단 입력바와 탭바가 붙어 어느 것을 누르는지 헷갈린다. */}
      {chatOpen && (
        <div className="chat-overlay" data-testid="chat-overlay">
          <ChatView onClose={() => leaveRoom()} />
        </div>
      )}

      {signedIn && (
        <nav className="app-tabbar" aria-label="화면 전환">
          {PRIVATE_VIEWS.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              className="app-nav-item"
              data-testid={`nav-${id}`}
              aria-current={id === active ? 'page' : undefined}
              onClick={() => setView(id)}
            >
              <Icon />
              {label}
            </button>
          ))}
        </nav>
      )}

      {/* 토스트를 누르면 그 방으로 이동한다 (BR-5.9). `ToastHost`가 부르는
          `enterRoom()`이 포인터를 옮기고 그것이 위 팝업을 연다 — 화면 전환을 여기서
          따로 하지 않는다. */}
      <ToastHost />
    </div>
  )
}
