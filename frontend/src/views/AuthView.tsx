import { useId, useState, type FormEvent } from 'react'

import * as api from '../lib/apiClient'
import {
  PASSWORD_MIN_LENGTH,
  PASSWORD_TOO_SHORT_MESSAGE,
  USERNAME_MAX_LENGTH,
} from '../lib/constants'
import { useChatStore } from '../store/chatStore'

/**
 * 로그인·회원가입 화면 (`business-logic-model.md` § AuthView).
 *
 * | 상태 | 내용 |
 * |---|---|
 * | 기본 | 로그인 폼 + "회원가입" 전환 |
 * | 회원가입 | 아이디, 비밀번호, 비밀번호 확인 |
 * | 로딩 | 제출 버튼 비활성화 + 스피너 |
 * | 오류 | **폼 상단에** 한 줄. 필드별 표시는 하지 않는다 |
 *
 * **오류를 폼 상단에 모으는 이유** — 입력이 두세 개뿐이라 필드별 오류 목록의 값어치가
 * 없고, 서버가 첫 번째 위반만 응답하므로(`business-rules.md` § 규칙 간 우선순위)
 * 표시할 오류도 한 번에 하나다.
 *
 * **401 문구를 그대로 쓰는 것이 이 화면의 규칙이다.** 프론트가 "아이디가 없습니다"로
 * 바꾸면 BR-1.4의 비구분 원칙이 UI에서 깨져, 서버가 애써 숨긴 계정 존재 여부가
 * 화면으로 새어나간다.
 */

type Mode = 'login' | 'signup'

export default function AuthView() {
  const setAuth = useChatStore((state) => state.setAuth)
  const token = useChatStore((state) => state.auth.token)

  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  // `useId`로 라벨과 입력을 잇는다 — 같은 화면에 폼이 두 번 렌더되어도 id가 겹치지 않는다.
  const usernameId = useId()
  const passwordId = useId()
  const confirmId = useId()
  const hintId = useId()
  const pendingHintId = useId()

  const isSignup = mode === 'signup'

  function switchMode(next: Mode) {
    setMode(next)
    // 오류와 비밀번호를 함께 지운다 — 앞 모드의 오류가 남으면 사용자가 방금 바꾼
    // 화면에 대한 오류라고 오해한다.
    setError(null)
    setPassword('')
    setPasswordConfirm('')
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (pending) return
    setError(null)

    // 클라이언트 검사는 **편의**다. 서버 검사가 진실이며, 여기서 막는 목적은 확실히
    // 실패할 요청의 왕복을 아끼는 것뿐이다 (`business-logic-model.md` § 검증 시점).
    if (isSignup) {
      if (password.length < PASSWORD_MIN_LENGTH) {
        setError(PASSWORD_TOO_SHORT_MESSAGE)
        return
      }
      if (password !== passwordConfirm) {
        // 비밀번호 확인은 서버에 없는 개념이다 — 오타를 잡는 화면 장치이므로
        // 문구도 여기서 만든다.
        setError('비밀번호가 서로 다릅니다')
        return
      }
    }

    setPending(true)
    try {
      const result = isSignup
        ? await api.signup(username, password)
        : await api.login(username, password)

      if (!result.ok) {
        // **서버 문구를 그대로 쓴다.** 401도, 409도, 400도 마찬가지다.
        setError(result.error.message)
        return
      }
      // 회원가입도 토큰을 함께 받는다 — 자동 로그인이므로 로그인과 같은 경로로 저장한다.
      setAuth(result.data.token, result.data.user)
    } catch (caught) {
      // 네트워크·5xx만 여기로 온다 (apiClient의 규약). 사용자가 고칠 수 없는 실패다.
      setError(caught instanceof Error ? caught.message : '요청을 처리할 수 없습니다')
    } finally {
      setPending(false)
    }
  }

  if (token !== null) {
    return (
      <section className="panel" aria-label="로그인 상태">
        <p>로그인되어 있습니다.</p>
        <button
          type="button"
          className="secondary"
          data-testid="auth-logout"
          onClick={() => useChatStore.getState().clearAuth()}
        >
          로그아웃
        </button>
      </section>
    )
  }

  return (
    <section className="panel">
      <form className="form" onSubmit={handleSubmit} noValidate>
        {/* 오류는 폼 상단의 aria-live 영역 하나에만 나온다.
            영역을 항상 렌더해두는 이유 — 나중에 삽입되는 요소의 내용은 일부 스크린리더가
            읽지 않는다. 비어 있는 채로 미리 있어야 변경이 announce된다. */}
        <div className="form-error" aria-live="polite" data-testid="auth-error">
          {error}
        </div>

        <div className="field">
          <label htmlFor={usernameId}>아이디</label>
          <input
            id={usernameId}
            name="username"
            type="text"
            autoComplete="username"
            maxLength={USERNAME_MAX_LENGTH}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </div>

        <div className="field">
          <label htmlFor={passwordId}>비밀번호</label>
          <input
            id={passwordId}
            name="password"
            type="password"
            autoComplete={isSignup ? 'new-password' : 'current-password'}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-describedby={isSignup ? hintId : undefined}
            required
          />
          {isSignup && (
            <p className="field-hint" id={hintId}>
              {PASSWORD_MIN_LENGTH}자 이상
            </p>
          )}
        </div>

        {isSignup && (
          <div className="field">
            <label htmlFor={confirmId}>비밀번호 확인</label>
            <input
              id={confirmId}
              name="passwordConfirm"
              type="password"
              autoComplete="new-password"
              value={passwordConfirm}
              onChange={(event) => setPasswordConfirm(event.target.value)}
              required
            />
          </div>
        )}

        <button
          type="submit"
          className="primary"
          // testid가 모드에 따라 갈리는 이유 — `business-logic-model.md` § 자동화 훅이
          // `auth-login-submit`과 `auth-signup-submit`을 따로 요구한다. 한 화면에 둘이
          // 동시에 있는 것이 아니라 모드에 따라 하나만 있다.
          data-testid={isSignup ? 'auth-signup-submit' : 'auth-login-submit'}
          disabled={pending}
          // 비활성화된 이유를 가리킨다. 스피너는 `aria-hidden`이라 그것만으로는
          // 버튼이 왜 눌리지 않는지 알 수 없다.
          aria-describedby={pending ? pendingHintId : undefined}
        >
          {pending && <span className="spinner" aria-hidden="true" />}
          {isSignup ? '회원가입' : '로그인'}
        </button>

        {/* 비활성화 이유이자 진행 상태 알림. 비어 있는 채로 미리 렌더해두면
            내용이 채워질 때 aria-live가 그것을 읽는다. */}
        <span className="visually-hidden" id={pendingHintId} aria-live="polite">
          {pending ? '처리 중입니다. 잠시 기다려 주세요' : ''}
        </span>
      </form>

      <p className="form-switch">
        {isSignup ? '이미 계정이 있으신가요?' : '계정이 없으신가요?'}{' '}
        <button
          type="button"
          className="link"
          data-testid="auth-switch-mode"
          onClick={() => switchMode(isSignup ? 'login' : 'signup')}
        >
          {isSignup ? '로그인' : '회원가입'}
        </button>
      </p>
    </section>
  )
}
