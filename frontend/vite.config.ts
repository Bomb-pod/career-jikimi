import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * 개발 서버가 백엔드로 넘겨주는 경로 접두사.
 *
 * **`/api` 접두사를 쓰지 않는 이유** — `application-design/components.md`가
 * 엔드포인트를 `POST /auth/signup`, `GET /rooms/{id}` 처럼 접두사 없이 확정했다.
 * 프록시를 위해 `/api`를 새로 만들면 개발과 배포의 경로가 갈라지고, 그 차이가
 * 프론트엔드 코드에 조건문으로 남는다.
 *
 * U2~U5가 라우터를 추가할 때 새 최상위 접두사가 생기면 이 목록에도 넣어야 한다.
 * 빠뜨리면 dev에서 그 요청이 Vite로 가서 index.html이 돌아온다 — "JSON인데 왜
 * <!doctype html>이 오지" 하는 30분을 보내게 된다.
 */
const BACKEND_PATHS = [
  '/auth',
  '/users',
  '/friends',
  '/rooms',
  '/messages',
  '/judgments',
  '/health',
]

const BACKEND_ORIGIN = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      ...Object.fromEntries(
        BACKEND_PATHS.map((path) => [path, { target: BACKEND_ORIGIN, changeOrigin: true }]),
      ),
      // WebSocket은 수신 전용 채널이다 (ADR-001). ws: true가 없으면
      // 업그레이드 요청이 프록시를 통과하지 못한다.
      '/ws': { target: BACKEND_ORIGIN, ws: true, changeOrigin: true },
    },
  },
  build: {
    // Dockerfile의 프론트 빌드 스테이지가 이 디렉터리를 런타임 이미지의
    // backend/static/ 으로 복사한다 (FR-9.5).
    outDir: 'dist',
    sourcemap: true,
  },
})
