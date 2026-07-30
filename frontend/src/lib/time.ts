/**
 * 시각 표시 — 메신저 관용구.
 *
 * 목록은 "오후 3:24" / "어제" / "7월 28일"처럼 최근일수록 정밀하게, 대화는 항상
 * 시각만 보여준다. 절대 날짜만 쓰면 오늘 온 메시지도 날짜로 표시되어 "방금"인지
 * 알 수 없고, 상대 시간("3분 전")만 쓰면 스크롤백에서 순서를 못 잡는다.
 *
 * **`Intl`을 쓰지 않고 직접 만든다** — jsdom과 브라우저의 `Intl` 출력이 갈려
 * 테스트가 환경에 따라 붉어진다. 형식이 한국어 하나로 고정이라 얻는 것도 없다.
 */

/** ISO 문자열을 `Date`로. 파싱 실패는 `null` — 화면이 `Invalid Date`를 보이면 안 된다. */
function parse(iso: string): Date | null {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

/** `오후 3:24` — 대화 말풍선 옆에 붙는 형식. */
export function formatClock(iso: string): string {
  const date = parse(iso)
  if (date === null) return ''
  const hours = date.getHours()
  const meridiem = hours < 12 ? '오전' : '오후'
  const hour12 = hours % 12 === 0 ? 12 : hours % 12
  return `${meridiem} ${hour12}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** `2026년 7월 30일 목요일` — 대화의 날짜 구분선. */
export function formatDateDivider(iso: string): string {
  const date = parse(iso)
  if (date === null) return ''
  const weekday = ['일', '월', '화', '수', '목', '금', '토'][date.getDay()] ?? ''
  return `${date.getFullYear()}년 ${date.getMonth() + 1}월 ${date.getDate()}일 ${weekday}요일`
}

/** 두 시각이 같은 날인가 — 날짜 구분선을 넣을 자리를 정한다. */
export function isSameDay(a: string, b: string): boolean {
  const left = parse(a)
  const right = parse(b)
  if (left === null || right === null) return false
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  )
}

/**
 * 목록용 — 오늘이면 시각, 어제면 `어제`, 그 밖에는 `7월 28일`.
 *
 * `now`를 인자로 받는 이유 — 테스트가 시간을 고정할 수 있어야 한다. 기본값을
 * 호출 시점에 만들면 자정 직전에 도는 테스트가 간헐적으로 실패한다.
 */
export function formatListTime(iso: string, now: Date = new Date()): string {
  const date = parse(iso)
  if (date === null) return ''

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const startOfTarget = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const dayGap = Math.round((startOfToday.getTime() - startOfTarget.getTime()) / 86_400_000)

  if (dayGap <= 0) return formatClock(iso)
  if (dayGap === 1) return '어제'
  return `${date.getMonth() + 1}월 ${date.getDate()}일`
}
