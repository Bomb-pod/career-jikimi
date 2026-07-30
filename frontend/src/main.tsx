import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './index.css'

const container = document.getElementById('root')

// 마운트 지점이 없으면 조용히 빈 화면이 된다 — 원인을 알 수 없는 실패다.
// 여기서 던지면 콘솔에 무엇이 잘못됐는지 그대로 남는다.
if (!container) {
  throw new Error('#root 요소를 찾을 수 없습니다. index.html을 확인하세요.')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
