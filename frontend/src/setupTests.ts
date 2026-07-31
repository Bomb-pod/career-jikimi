// jest-dom 매처(`toBeInTheDocument` 등)를 vitest의 expect에 붙인다.
// `/vitest` 하위 경로를 import해야 vitest용 타입 확장까지 적용된다.
import '@testing-library/jest-dom/vitest'

// jsdom의 `document.hasFocus()`는 **기본이 `false`다** — 진짜 창이 없으니 포커스도
// 없다는 뜻이고, jsdom 입장에서는 맞는 답이다.
//
// 그런데 실제 사용자의 창은 대개 포커스를 갖고 있고, 그것이 화면 동작의 기본
// 조건이다(`lib/viewedRooms`의 `isViewing()`). 기본값을 그대로 두면 모든 테스트가
// "창이 뒤로 밀려 있는 상태"에서 돌아 — 읽음 처리가 미뤄지고 배지가 쌓이는 쪽이
// 기본이 된다. 그건 예외 상황이지 기본이 아니다.
//
// 그래서 여기서 **포커스 있음을 기본으로 세운다.** 그 반대를 재는 테스트는
// `vi.spyOn(document, 'hasFocus').mockReturnValue(false)`로 직접 뒤집는다 —
// 예외를 테스트가 명시하게 하는 편이, 기본이 예외인 것보다 읽기 쉽다.
Object.defineProperty(document, 'hasFocus', {
  configurable: true,
  writable: true,
  value: () => true,
})
