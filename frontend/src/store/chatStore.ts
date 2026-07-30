/**
 * `chatStore` — 애플리케이션 상태의 단일 출처 (`components.md` § chatStore, ADR-004).
 *
 * **U3이 만든 슬라이스는 `auth`와 `friends`, U4가 더한 것은 `rooms`·`unread`·
 * `messages`·`toasts`·WebSocket 상태다.** `degraded`는 U5가 더한다 — 스토어를 단위마다
 * 나누지 않는 이유는 여러 슬라이스를 한 번에 읽는 화면(방 목록의 안 읽은 개수 +
 * 참여자 표시명)이 있어서다.
 *
 * **토큰은 메모리 + `localStorage`다.** `degraded`가 메모리 전용인 것과 다르다 —
 * FR-8.3이 degraded의 새로고침 초기화를 요구하는 반면, 로그인은 새로고침해도
 * 유지되는 것이 맞다. 리프레시 토큰이 없어(FR-1.2) 다시 로그인하는 비용이 크다.
 */

import { create } from 'zustand'

import {
  listMessages,
  markRead as markReadRequest,
  me as fetchMe,
  setAuthToken,
  type ChatMessage,
  type CurrentUser,
  type Friend,
  type RoomSummary,
} from '../lib/apiClient'
import {
  DEGRADED_RECOVERED_MESSAGE,
  PROBE_EVERY,
  TOAST_MAX_VISIBLE,
  TOKEN_STORAGE_KEY,
} from '../lib/constants'
import { roomDisplayName } from '../lib/roomName'
import type { WsStatus } from '../lib/wsClient'

interface AuthSlice {
  token: string | null
  user: CurrentUser | null
}

/** 화면 오른쪽 아래에 뜨는 알림 하나 (FR-5.3). */
export interface Toast {
  /** 토스트를 특정하는 키. **방 하나당 하나만 뜨므로 `roomId`와 같다.** */
  id: number
  roomId: number
  /** 토스트에 보이는 방 이름 — 어느 방인지 알 수 있어야 한다 (FR-5.3의 수용 기준). */
  roomName: string
  body: string
}

/**
 * 방 입장 시 히스토리를 가져오는 함수.
 *
 * **주입받는 이유** — 히스토리 조회 API(`GET /rooms/{id}/messages`)는 **U5 소관**이다
 * (`business-logic-model.md`). 이 단위가 지는 의무는 그 응답을 **구독 스트림과
 * 병합하는 것**이며(FR-3.3), 그 병합은 API 없이도 검증할 수 있고 검증해야 한다.
 * 기본값이 빈 배열이라 U5가 붙기 전에도 방 입장이 동작한다.
 */
export type HistoryLoader = (roomId: number) => Promise<ChatMessage[]>

/**
 * 기본 히스토리 로더 — `GET /rooms/{id}/messages` (FR-3.3, FR-4.4).
 *
 * U4가 이 자리를 "히스토리 없음"으로 남겨 둔 것은 그 API가 U5 소관이었기 때문이다.
 * 여기서 갈아끼운다. **포인터 먼저, 히스토리 나중**이라는 순서는 `enterRoom()`이
 * 이미 보장하므로 이 함수가 신경 쓸 것은 없다.
 *
 * 실패를 `[]`로 접지 않고 그대로 올리는 이유 — `enterRoom()`이 그 예외를 잡아
 * "구독은 살아 있다"로 처리한다. 여기서 삼키면 "메시지가 없는 방"과 "히스토리를 못
 * 가져온 방"이 화면에서 같아진다.
 */
const loadRoomHistory: HistoryLoader = async (roomId) => {
  const result = await listMessages(roomId)
  if (!result.ok) throw new Error(result.error.message)
  return result.data.messages
}

/**
 * 낙관적 렌더링 중인 임시 메시지 (FR-4.3).
 *
 * **`messages`와 섞지 않는다.** 섞으려면 가짜 `id`와 가짜 `seq`가 필요한데, 그 둘은
 * 각각 중복 제거 키와 정렬 기준이라 가짜 값이 들어가면 두 알고리즘이 동시에
 * 흔들린다. 화면이 목록 뒤에 이어 붙이는 편이 싸고 정확하다.
 */
export interface PendingMessage {
  /** 화면 키. 서버 id와 절대 겹치지 않도록 문자열이다. */
  tempId: string
  roomId: number
  body: string
}

export interface ChatState {
  auth: AuthSlice
  /** 내 친구 목록. **별칭만 담긴다** (FR-2.4). */
  friends: Friend[]

  /** 내가 속한 방. 서버가 준 순서를 그대로 쓴다 (FR-3.2는 정렬을 규정하지 않는다). */
  rooms: RoomSummary[]
  /**
   * `roomId -> 안 읽은 개수`. **배지의 단일 출처다.**
   *
   * `rooms[].unread_count`를 그대로 쓰지 않는 이유 — 그러면 값이 두 곳에 살고,
   * WebSocket으로 올린 값과 목록을 다시 불러온 값이 어긋난다. 목록을 받을 때
   * 여기로 옮겨 담고, 이후에는 여기만 갱신한다.
   */
  unread: Record<number, number>
  /** 지금 보고 있는 방. `null`이면 목록 화면이다. */
  currentRoomId: number | null
  /** **현재 방의** 메시지. 방을 옮기면 비운다 — 모든 방을 들고 있을 이유가 없다. */
  messages: ChatMessage[]
  toasts: Toast[]
  /** `session_replaced`를 받았는가 (BR-5.5). 배너의 근거다. */
  sessionReplaced: boolean
  wsStatus: WsStatus

  // ---- U5가 더하는 degraded 슬라이스 (FR-8.3, FR-8.5) --------------------
  /**
   * 검증 서버가 죽어 있다고 보고 판정을 건너뛰는 중인가 (FR-8.3).
   *
   * **메모리에만 있다.** `localStorage`·`sessionStorage`에 쓰지 않는다 — FR-8.3이
   * "새로고침하거나 새 탭을 열면 초기화되어 정상 검증을 다시 시도한다"를 요구하므로,
   * 저장하면 요구사항 위반이다. `auth.token`이 저장되는 것과 대비된다.
   *
   * **모든 방에 적용된다** (BR-8.3). 방을 옮겨도 다시 묻지 않는다.
   */
  degraded: boolean
  /**
   * degraded 진입 후 보낸 메시지 수 — 프로브 카운터 (BR-8.5).
   *
   * **사용자 전역이다. 방 단위가 아니다.** degraded 자체가 모든 방에 적용되므로
   * 카운터도 같은 범위여야 한다 — 방 단위로 세면 방을 옮길 때마다 리셋되어 프로브가
   * 거의 돌지 않는다.
   */
  degradedSendCount: number
  /**
   * 방과 무관한 시스템 안내 한 줄 (FR-8.5의 "AI 검증이 다시 켜졌습니다").
   *
   * `toasts`에 넣지 않은 이유 — 그 큐는 **방 단위**다(`id === roomId`이고 누르면 그
   * 방으로 이동한다, BR-5.9). 갈 곳이 없는 안내를 그 큐에 넣으면 `toast-{roomId}`
   * 훅과 클릭 동작이 둘 다 의미를 잃는다.
   */
  notice: string | null
  /** 낙관적 렌더링 중인 임시 메시지 (FR-4.3). 메모리 전용이다. */
  pending: PendingMessage[]

  /** 로그인·회원가입 성공 시 호출한다. 토큰을 apiClient와 `localStorage`에 함께 심는다. */
  setAuth: (token: string, user: CurrentUser) => void
  /** 로그아웃 또는 토큰 만료(401) 시 호출한다. */
  clearAuth: () => void
  /**
   * 저장된 토큰으로 `GET /auth/me`를 불러 `auth.user`를 채운다 — 부팅 시 한 번.
   *
   * 토큰이 없으면 아무 일도 하지 않는다. **401이면 `clearAuth()`를 부른다** — 낡은
   * 토큰을 들고 있으면 이후 모든 요청이 401이 되고 사용자는 로그인했다고 믿는다.
   *
   * 그 밖의 실패(네트워크·5xx)에는 토큰을 지우지 않는다. 서버가 잠깐 죽은 것과
   * 토큰이 죽은 것은 다르며, 전자에서 로그아웃시키면 서버가 돌아와도 다시
   * 로그인해야 한다.
   *
   * 반환값은 "이 토큰이 살아 있는가"다 — App 셸이 첫 화면을 정하는 데 쓴다.
   */
  hydrateSession: () => Promise<boolean>
  setFriends: (friends: Friend[]) => void
  /**
   * 친구 하나를 추가하거나 이미 있으면 갈아끼운다.
   *
   * 목록 전체를 다시 fetch하지 않는 이유 — 등록·수정 응답이 그 항목의 최신 상태를
   * 그대로 준다. 왕복 한 번을 아끼고, 화면이 즉시 갱신된다.
   */
  upsertFriend: (friend: Friend) => void

  setRooms: (rooms: RoomSummary[]) => void
  /** 방 하나를 추가하거나 갈아끼운다 — 생성 응답을 목록에 즉시 반영한다. */
  upsertRoom: (room: RoomSummary) => void
  /** 그 방의 내 `ai_check_enabled`를 화면 상태에 반영한다 (FR-6.1). */
  setAiCheck: (roomId: number, enabled: boolean) => void

  /**
   * WebSocket으로 도착한 메시지 하나를 처리한다 (BR-5.9).
   *
   * 보고 있는 방이면 목록에 넣고 읽음 처리를, 아니면 배지와 토스트를 올린다.
   */
  receiveMessage: (message: ChatMessage) => void
  /** **포인터를 먼저 옮기고 그다음 히스토리** (BR-3.5, FR-3.3). */
  enterRoom: (roomId: number, loadHistory?: HistoryLoader) => Promise<void>
  /** 목록으로 돌아간다. 이후 도착하는 메시지는 배지·토스트로 간다. */
  leaveRoom: () => void

  dismissToast: (toastId: number) => void
  markSessionReplaced: () => void
  setWsStatus: (status: WsStatus) => void

  // ---- U5 ----------------------------------------------------------------
  /** 이번 전송이 프로브 차례인가 — `degraded && count % 5 === 4` (BR-8.5). */
  shouldProbe: () => boolean
  /** degraded 중에 한 건 보냈다고 카운터를 올린다. 프로브 여부와 무관하게 센다. */
  noteDegradedSend: () => void
  /**
   * degraded로 전환한다 (FR-8.3).
   *
   * **강행 재요청이 끝난 *뒤에* 불러야 한다.** 먼저 부르면 그 재요청이 degraded
   * 경로로 빠져 메시지가 `failed`가 아니라 `degraded`로 저장되고, 시도한 사실이
   * 사라진다 (BR-8.3).
   */
  enterDegraded: () => void
  /** 프로브가 성공해 정상 검증으로 돌아왔다 — 카운터를 비우고 안내를 띄운다. */
  exitDegraded: () => void
  dismissNotice: () => void

  /** 낙관적 렌더링을 시작한다. 돌려받은 `tempId`로 나중에 제거한다 (FR-4.3). */
  addPending: (roomId: number, body: string) => string
  /** 임시 메시지를 치운다 — 201이든 실패든 반드시 호출된다. */
  removePending: (tempId: string) => void
  /** 전송 응답으로 받은 실제 메시지를 목록에 넣는다. WebSocket 푸시와 ID로 접힌다. */
  applySentMessage: (message: ChatMessage) => void
  /** 신고 여부를 화면 상태에 반영한다 (FR-11.3). */
  setReported: (messageId: number, reportedAt: string | null) => void
}

/**
 * `localStorage`에서 토큰을 읽는다. 실패하면 `null`.
 *
 * try/catch를 두는 이유 — 사파리의 프라이빗 모드 등에서 `localStorage` 접근 자체가
 * 예외를 던진다. 여기서 터지면 앱이 아예 뜨지 않는다. 토큰을 못 읽으면 로그인
 * 화면으로 가면 되므로 조용히 `null`로 다룬다(사용자에게 보이는 손실이 없다).
 */
function readStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (token === null) window.localStorage.removeItem(TOKEN_STORAGE_KEY)
    else window.localStorage.setItem(TOKEN_STORAGE_KEY, token)
  } catch {
    // 저장에 실패해도 메모리의 토큰으로 이번 세션은 정상 동작한다.
    // 다음 새로고침에 다시 로그인하는 것이 유일한 손실이다.
  }
}

/**
 * 메시지 목록을 **ID로 중복 제거해** `seq` 순으로 정렬한다.
 *
 * **중복 제거가 이 단위의 명시된 의무다** (FR-3.3, FR-4.3). 같은 메시지가 두 경로로
 * 들어온다:
 *   - 내가 보낸 메시지 — HTTP 응답과 WebSocket 푸시 (BR-5.8)
 *   - 방에 입장할 때 — 히스토리 응답과 구독 스트림
 *
 * `seq`로 정렬하는 이유는 도착 순서가 저장 순서와 다를 수 있어서다. `created_at`이
 * 아니라 `seq`인 것은 FR-4.2가 정한 정렬 기준이다 — 동시 도착 시 같은 마이크로초를
 * 가질 수 있고 시계가 뒤로 갈 수도 있다(NFR-4).
 *
 * **나중 것이 이긴다.** 같은 id가 겹치면 뒤에 온 쪽으로 덮어쓴다 — 히스토리보다
 * 스트림이 최신이고, 서버 ack가 낙관적 렌더링보다 정확하다.
 */
function mergeById(messages: ChatMessage[]): ChatMessage[] {
  const byId = new Map<number, ChatMessage>()
  for (const message of messages) byId.set(message.id, message)
  return [...byId.values()].sort((left, right) => left.seq - right.seq)
}

/**
 * 읽음 처리를 보낸다. **실패해도 조용히 넘어간다.**
 *
 * 실패를 사용자에게 알리지 않는 이유 — 이것은 사용자가 요청한 동작이 아니라 화면을
 * 본 결과의 부수 효과다. 여기서 오류를 띄우면 메시지를 읽었을 뿐인데 실패 문구가
 * 뜬다. 배지는 다음 목록 조회에서 서버 값으로 다시 맞춰진다.
 */
function markReadQuietly(roomId: number, upToSeq: number): void {
  if (upToSeq <= 0) return
  void markReadRequest(roomId, upToSeq).catch(() => undefined)
}

/** `addPending()`의 임시 키에 붙는 일련번호. 같은 밀리초에 두 번 보내도 키가 갈린다. */
let pendingSeed = 0

const initialToken = readStoredToken()
// 스토어 생성 시점에 apiClient도 같은 값을 알아야 한다 — 새로고침 직후의 첫 요청이
// 헤더 없이 나가면 401이 되고, 사용자는 방금 로그인했는데 튕겼다고 느낀다.
setAuthToken(initialToken)

export const useChatStore = create<ChatState>((set, get) => ({
  auth: {
    token: initialToken,
    // 새로고침 직후에는 토큰만 있고 사용자 정보가 없다. `hydrateSession()`이
    // `GET /auth/me`로 이 한 조각을 채운다 — App 셸이 부팅 시 한 번 부른다.
    user: null,
  },
  friends: [],

  rooms: [],
  unread: {},
  currentRoomId: null,
  messages: [],
  toasts: [],
  sessionReplaced: false,
  wsStatus: 'idle',

  // **메모리 전용이다** — 저장하면 FR-8.3 위반이다. 스토어가 다시 만들어지면
  // (새로고침·새 탭) 이 두 값이 여기 적힌 초기값으로 돌아간다.
  degraded: false,
  degradedSendCount: 0,
  notice: null,
  pending: [],

  setAuth: (token, user) => {
    setAuthToken(token)
    writeStoredToken(token)
    set({ auth: { token, user } })
  },

  hydrateSession: async () => {
    if (get().auth.token === null) return false

    const result = await fetchMe()
    if (result.ok) {
      set((state) => ({ auth: { ...state.auth, user: result.data } }))
      return true
    }
    // 401만 토큰을 지운다 — 만료·위조·서명 오류가 전부 여기로 온다.
    if (result.error.status === 401) {
      get().clearAuth()
      return false
    }
    // 네트워크·5xx는 토큰을 건드리지 않는다. 사용자 이름만 비어 있을 뿐
    // 나머지 화면은 그대로 동작하며, 다음 새로고침에 다시 시도된다.
    return true
  },

  clearAuth: () => {
    setAuthToken(null)
    writeStoredToken(null)
    // 친구 목록도 함께 비운다 — 다음 사용자에게 앞 사용자의 별칭이 보이면 FR-2.4
    // 위반이다. 로그아웃이 남긴 화면 잔상이 가장 흔한 유출 경로다.
    //
    // 방·메시지·배지·토스트도 같은 이유로 비운다. 방 이름은 참여자 표시명으로
    // 조립되므로(별칭 포함) 남아 있으면 그것도 유출이다.
    set({
      auth: { token: null, user: null },
      friends: [],
      rooms: [],
      unread: {},
      currentRoomId: null,
      messages: [],
      toasts: [],
      // 임시 메시지도 비운다 — 다음 사용자에게 앞 사용자가 쓰다 만 문장이 보이면
      // 그것도 유출이다. `degraded`는 남겨도 새 사용자에게 해가 없지만, 로그아웃은
      // 세션의 끝이므로 함께 되돌린다.
      pending: [],
      degraded: false,
      degradedSendCount: 0,
      notice: null,
    })
  },

  setFriends: (friends) => set({ friends }),

  upsertFriend: (friend) =>
    set((state) => {
      const index = state.friends.findIndex((item) => item.id === friend.id)
      if (index === -1) return { friends: [...state.friends, friend] }
      const next = [...state.friends]
      next[index] = friend
      return { friends: next }
    }),

  setRooms: (rooms) =>
    set((state) => ({
      rooms,
      // 서버가 계산한 배지 값을 단일 출처로 옮겨 담는다. 보고 있는 방은 0으로
      // 덮는다 — 서버 응답이 만들어진 뒤 그 방을 열었을 수 있다.
      unread: Object.fromEntries(
        rooms.map((room) => [room.id, room.id === state.currentRoomId ? 0 : room.unread_count]),
      ),
    })),

  upsertRoom: (room) =>
    set((state) => {
      const index = state.rooms.findIndex((item) => item.id === room.id)
      const rooms = index === -1 ? [room, ...state.rooms] : [...state.rooms]
      if (index !== -1) rooms[index] = room
      return { rooms, unread: { ...state.unread, [room.id]: room.unread_count } }
    }),

  setAiCheck: (roomId, enabled) =>
    set((state) => ({
      rooms: state.rooms.map((room) => (room.id === roomId ? { ...room, ai_check_enabled: enabled } : room)),
    })),

  receiveMessage: (message) => {
    const state = get()

    if (state.currentRoomId === message.room_id) {
      // 보고 있는 방이다 — 목록에 넣고 읽음 위치를 전진시킨다 (BR-5.2).
      // **토스트를 띄우지 않는다** (BR-5.9) — 이미 보고 있다.
      set({
        messages: mergeById([...state.messages, message]),
        unread: { ...state.unread, [message.room_id]: 0 },
      })
      markReadQuietly(message.room_id, message.seq)
      return
    }

    // 보고 있지 않은 방이다 — 배지와 토스트 (BR-5.9).
    set({
      unread: {
        ...state.unread,
        [message.room_id]: (state.unread[message.room_id] ?? 0) + 1,
      },
      toasts: pushToast(state, message),
    })
  },

  enterRoom: async (roomId, loadHistory = loadRoomHistory) => {
    const before = get()

    // **1. 포인터를 먼저 옮긴다** (BR-3.5, FR-3.3).
    //
    // WebSocket은 이미 모든 방의 메시지를 받고 있으므로 "구독"은 이 한 줄이다.
    // 반대 순서면 히스토리를 기다리는 동안 도착한 메시지가 "보고 있지 않은 방"으로
    // 분류되어 목록에 들어가지 않는다 — 그것이 FR-3.3이 말하는 유실이다.
    set({
      currentRoomId: roomId,
      messages: [],
      unread: { ...before.unread, [roomId]: 0 },
      // 그 방의 토스트는 의미를 잃는다 (BR-5.9 — 클릭 시 배지 소멸).
      toasts: before.toasts.filter((toast) => toast.roomId !== roomId),
    })

    // 목록에서 아는 최신 seq로 서버의 읽음 위치도 전진시킨다. 히스토리 응답을
    // 기다리지 않는 이유 — 그 왕복 동안 배지가 남아 있으면 사용자는 방을 열었는데도
    // 안 읽음으로 보이는 화면을 본다.
    const known = before.rooms.find((room) => room.id === roomId)
    if (known !== undefined) markReadQuietly(roomId, known.last_seq)

    // **2. 그다음 히스토리.**
    let history: ChatMessage[] = []
    try {
      history = await loadHistory(roomId)
    } catch {
      // 히스토리를 못 가져와도 구독은 살아 있다 — 새 메시지는 계속 들어온다.
      // 여기서 예외를 올리면 방 입장 자체가 실패한 것처럼 보인다.
      return
    }

    // **3. 병합.** 기다리는 동안 도착한 메시지가 `messages`에 이미 들어와 있고,
    // 겹치는 것은 id로 접힌다 (FR-3.3의 두 수용 기준).
    set((state) => {
      // 응답이 오기 전에 다른 방으로 갔으면 그 방의 화면을 덮어쓰지 않는다.
      if (state.currentRoomId !== roomId) return {}
      return { messages: mergeById([...history, ...state.messages]) }
    })
  },

  leaveRoom: () => set({ currentRoomId: null, messages: [] }),

  dismissToast: (toastId) =>
    set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== toastId) })),

  markSessionReplaced: () => set({ sessionReplaced: true }),

  setWsStatus: (status) => set({ wsStatus: status }),

  // ------------------------------------------------------------------------
  // U5 · degraded 관리 (FR-8.3, FR-8.5, BR-8.5)
  // ------------------------------------------------------------------------
  shouldProbe: () => {
    const state = get()
    // `% PROBE_EVERY === PROBE_EVERY - 1`은 0-index 기준 다섯 번째다 — 0,1,2,3을
    // 보낸 뒤 인덱스 4에서 프로브가 나간다. degraded 진입 직후를 프로브로 삼지 않는
    // 이유는 방금 실패한 API를 곧바로 다시 부르는 것이 의미가 적어서다.
    return state.degraded && state.degradedSendCount % PROBE_EVERY === PROBE_EVERY - 1
  },

  noteDegradedSend: () => set((state) => ({ degradedSendCount: state.degradedSendCount + 1 })),

  enterDegraded: () => set({ degraded: true, degradedSendCount: 0 }),

  exitDegraded: () =>
    set({ degraded: false, degradedSendCount: 0, notice: DEGRADED_RECOVERED_MESSAGE }),

  dismissNotice: () => set({ notice: null }),

  // ------------------------------------------------------------------------
  // U5 · 낙관적 렌더링 (FR-4.3)
  // ------------------------------------------------------------------------
  addPending: (roomId, body) => {
    // 문자열 키라 서버의 숫자 id와 절대 겹치지 않는다. 카운터를 붙이는 이유는
    // 같은 밀리초에 두 번 보내도 키가 갈리게 하기 위해서다.
    pendingSeed += 1
    const tempId = `pending-${Date.now()}-${pendingSeed}`
    set((state) => ({ pending: [...state.pending, { tempId, roomId, body }] }))
    return tempId
  },

  removePending: (tempId) =>
    set((state) => ({ pending: state.pending.filter((item) => item.tempId !== tempId) })),

  applySentMessage: (message) =>
    set((state) => {
      // 보고 있지 않은 방의 응답은 목록에 넣지 않는다 — 응답을 기다리는 동안
      // 사용자가 방을 옮겼을 수 있다. `receiveMessage()`가 배지로 처리한다.
      if (state.currentRoomId !== message.room_id) return {}
      return { messages: mergeById([...state.messages, message]) }
    }),

  setReported: (messageId, reportedAt) =>
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === messageId ? { ...message, misdirect_reported_at: reportedAt } : message,
      ),
    })),
}))

/**
 * 토스트 큐에 하나를 넣는다 — **방 하나당 하나, 최대 3개, 오래된 것부터 제거**
 * (`code-generation-plan.md` § 열린 항목).
 *
 * 방마다 하나로 접는 이유는 두 가지다. 한 방에 메시지가 연달아 오면 같은 토스트가
 * 쌓여 화면을 가리고, `data-testid`가 `toast-{roomId}`라 같은 방의 토스트가 여럿이면
 * 그 훅이 특정 요소를 가리키지 못한다. 새 메시지는 그 방의 토스트를 **갱신하고 맨
 * 뒤로 보낸다** — 방금 온 것이 가장 오래 남아야 한다.
 */
function pushToast(state: ChatState, message: ChatMessage): Toast[] {
  const room = state.rooms.find((item) => item.id === message.room_id)
  const toast: Toast = {
    id: message.room_id,
    roomId: message.room_id,
    // **FR-5.3의 수용 기준이 "토스트 안에 방 이름이 보인다"** 이므로 이름이 없는
    // 방도 참여자 표시명으로 조립한다. 목록과 같은 함수를 쓴다 — 두 곳이 같은 방을
    // 다르게 부르면 사용자가 두 방으로 인식한다.
    roomName:
      room === undefined
        ? '새 메시지'
        : roomDisplayName(room, state.auth.user?.id ?? null),
    body: message.body,
  }
  const others = state.toasts.filter((item) => item.roomId !== message.room_id)
  return [...others, toast].slice(-TOAST_MAX_VISIBLE)
}
