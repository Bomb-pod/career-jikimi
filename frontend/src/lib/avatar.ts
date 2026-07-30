/**
 * 아바타 표시 — 이름에서 머리글자와 배경색을 뽑는다.
 *
 * **이미지를 쓰지 않는 이유** — 프로필 사진이 요구사항에 없다(파일·이미지 전송이
 * 범위 밖이다). 메신저 목록은 아바타 자리가 비면 행이 무너져 보이므로, 이름에서
 * 결정적으로 만든 색 원을 대신 둔다.
 *
 * **표시명을 그대로 받는다** — 호출부가 이미 FR-2.4를 지켜 별칭으로 해석한 값을
 * 넘긴다. 이 파일은 문자열을 색과 글자로만 바꾸며 어디서 온 이름인지 모른다.
 */

/** 아바타 배경 팔레트. 흰 글자와 4.5:1 이상이 되도록 어두운 쪽으로 고른 값들이다. */
const PALETTE = [
  '#5b7ba8',
  '#6b8e6b',
  '#a8735b',
  '#7a6ba8',
  '#a85b7b',
  '#5b8ea8',
  '#8e7a5b',
  '#6b6b8e',
] as const

/**
 * 이름에서 머리글자 한 글자를 뽑는다.
 *
 * 한글은 첫 글자, 라틴 문자는 대문자 한 글자. 이모지로 시작하는 이름은
 * 그 이모지가 나온다 — 서로게이트 쌍이 쪼개지지 않게 `Array.from`으로 센다.
 */
export function avatarInitial(name: string): string {
  const trimmed = name.trim()
  if (trimmed === '') return '?'
  const first = Array.from(trimmed)[0] ?? '?'
  return first.toUpperCase()
}

/**
 * 이름에서 배경색을 고른다. **같은 이름은 항상 같은 색이다.**
 *
 * 무작위로 고르면 리렌더마다 색이 바뀌어 목록이 깜빡인다. 해시가 결정적이어야
 * 사용자가 색으로 사람을 기억할 수 있다.
 */
export function avatarColor(name: string): string {
  let hash = 0
  for (const character of name) {
    // 곱수 31 — 문자열 해시의 관용값이다. 암호학적 성질은 필요 없고
    // 짧은 한글 이름들이 서로 다른 칸에 떨어지기만 하면 된다.
    hash = (hash * 31 + character.codePointAt(0)!) % 0xffffffff
  }
  return PALETTE[hash % PALETTE.length] as string
}
