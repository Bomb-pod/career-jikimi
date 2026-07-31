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

// jsdom에는 `Element.prototype.scrollIntoView`가 **아예 없다** — 레이아웃을 계산하지
// 않으니 스크롤이라는 개념도 없다는 뜻이고, 그 입장에서는 맞는 답이다.
//
// 그런데 없으면 `vi.spyOn`이 "존재하지 않는다"며 거부하고, 실제 코드는 "함수가
// 아니다"로 터진다 — 안 읽은 메시지가 있는 방을 그리는 테스트가 전부 붉어진다.
// 아무것도 하지 않는 함수로 채워, 호출 여부는 테스트가 감시할 수 있게 한다.
//
// **여기서 확인되는 것은 "어디로 가야 하는가"까지다.** 실제로 어디에 섰는지는
// jsdom이 계산하지 못하므로 브라우저로 따로 봐야 한다.
Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  writable: true,
  value: () => undefined,
})
