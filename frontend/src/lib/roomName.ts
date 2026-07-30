/**
 * 방 이름 조립 — `rooms.name`이 비었을 때 참여자 표시명으로 만든다.
 *
 * **규칙의 단일 출처다.** 방 목록과 토스트가 같은 방을 다르게 부르면 사용자가 두
 * 방으로 인식한다. `RoomListView`와 `chatStore`가 이 함수를 함께 쓴다.
 *
 * 규칙 (`code-generation-plan.md` § 열린 항목에서 확정):
 *   - 이름이 있으면 그대로
 *   - 없으면 **참여자 표시명 최대 3명 + `외 N명`**
 *   - **본인은 제외한다** — 넣으면 모든 방 이름이 내 이름으로 시작해 구별에
 *     기여하지 않는다
 *
 * 표시명 자체는 서버가 `resolve_display_names()`로 해석해 보낸 값이다 (FR-2.4,
 * BR-2.8). 클라이언트는 그것을 잇기만 하고 별칭 규칙을 다시 해석하지 않는다.
 */

import type { RoomMember } from './apiClient'
import { ROOM_NAME_MEMBER_LIMIT } from './constants'

/** 이름 조립에 필요한 최소한의 방 정보. `RoomSummary`·`RoomDetail` 둘 다 만족한다. */
export interface NameableRoom {
  name: string | null
  members: RoomMember[]
}

export function roomDisplayName(room: NameableRoom, myUserId: number | null): string {
  if (room.name !== null && room.name.trim() !== '') return room.name

  // 본인 제외. `myUserId`가 `null`인 경우(새로고침 직후 사용자 정보가 없을 때)는
  // 거를 기준이 없으므로 전원을 쓴다 — 이름이 조금 길어질 뿐 틀리지는 않는다.
  const others = room.members.filter((member) => member.user_id !== myUserId)
  if (others.length === 0) return '빈 방'

  const shown = others.slice(0, ROOM_NAME_MEMBER_LIMIT).map((member) => member.display_name)
  const hidden = others.length - shown.length
  return hidden > 0 ? `${shown.join(', ')} 외 ${hidden}명` : shown.join(', ')
}
