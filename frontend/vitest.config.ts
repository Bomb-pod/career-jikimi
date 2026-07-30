import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

/**
 * vitest 설정.
 *
 * **vite.config.ts와 따로 두면서 react 플러그인을 다시 선언하는 이유** —
 * vitest는 vitest.config.ts가 있으면 그것만 읽고 vite.config.ts를 무시한다.
 * 플러그인을 여기 넣지 않으면 JSX가 변환되지 않아 테스트가 구문 오류로 죽는다.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    // 브라우저 DOM이 필요하다 — 렌더 결과를 조회하는 테스트다.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
