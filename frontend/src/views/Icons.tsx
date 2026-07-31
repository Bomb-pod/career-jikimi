/**
 * 탭·상단 바 아이콘.
 *
 * **인라인 SVG를 쓰는 이유** — 이모지는 OS마다 모양과 폭이 달라 탭 정렬이 틀어지고,
 * 아이콘 폰트는 의존성이 하나 늘면서 로드 전까지 빈칸이 보인다. SVG는 `currentColor`를
 * 따라가므로 현재 탭 강조가 색 한 곳만 바꾸면 된다.
 *
 * **`aria-hidden`이 붙어 있다** — 옆에 항상 보이는 텍스트 라벨이 있으므로
 * 스크린리더에는 아이콘이 중복이다.
 */

type Props = { className?: string }

function svg(children: React.ReactNode, props: Props) {
  return (
    <svg
      className={props.className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  )
}

export function FriendsIcon(props: Props) {
  return svg(
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.5 19c0-3 2.5-5 5.5-5s5.5 2 5.5 5" />
      <path d="M16 5.6a3 3 0 0 1 0 5.8" />
      <path d="M17.5 14.2c2 .7 3.5 2.4 3.5 4.8" />
    </>,
    props,
  )
}

export function RoomsIcon(props: Props) {
  return svg(
    <path d="M4 5.5h16v10H9.5L5.5 19v-3.5H4z" />,
    props,
  )
}

export function ChatIcon(props: Props) {
  return svg(
    <>
      <path d="M4 5.5h16v10H9.5L5.5 19v-3.5H4z" />
      <path d="M8.5 10.5h7" />
    </>,
    props,
  )
}

export function BackIcon(props: Props) {
  return svg(<path d="M14.5 5.5 8 12l6.5 6.5" />, props)
}

export function CloseIcon(props: Props) {
  return svg(
    <>
      <path d="m6 6 12 12" />
      <path d="m18 6-12 12" />
    </>,
    props,
  )
}

/** 톱니바퀴 — 방 설정 팝업을 여는 버튼. */
export function SettingsIcon(props: Props) {
  return svg(
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v2.2M12 19.3v2.2M21.5 12h-2.2M4.7 12H2.5M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6M18.7 18.7l-1.6-1.6M6.9 6.9 5.3 5.3" />
    </>,
    props,
  )
}

export function SignOutIcon(props: Props) {
  return svg(
    <>
      <path d="M14.5 6.5V5a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 5v14A1.5 1.5 0 0 0 6 20.5h7a1.5 1.5 0 0 0 1.5-1.5v-1.5" />
      <path d="M9.5 12h11" />
      <path d="m17.5 8.5 3.5 3.5-3.5 3.5" />
    </>,
    props,
  )
}
