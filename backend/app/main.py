"""FastAPI 애플리케이션 — 앱 생성, `/health`, 정적 파일 서빙, 라우터 등록 지점.

U1(foundation)이 만드는 것은 **바닥**뿐이다. 엔드포인트는 `/health` 하나이며,
나머지는 U2~U5의 라우터가 아래 "라우터 등록 지점"에 붙는다.

프로세스 모델은 **uvicorn 워커 1개 고정**이다 (FR-9.4, CON-1). 성능 판단이 아니라
정합성 요구다 — U4의 WebSocket 연결 레지스트리가 프로세스 메모리에 있어 워커를
늘리면 각 워커가 자기 레지스트리를 갖고, 다른 워커에 붙은 사용자에게 못 보낸다.
워커 수는 `docker-entrypoint.sh`가 `--workers 1`로 고정한다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.auth.router import router as auth_router
from app.core.config import settings
from app.core.db import check_database, dispose_engine, wait_for_database
from app.core.errors import register_error_handlers
from app.friends.router import router as friends_router
from app.judgment import backend as judgment_backend
from app.judgment.router import router as judgment_router
from app.messages.router import router as messages_router
from app.rooms.router import router as rooms_router
from app.rooms.ws import router as ws_router

# uvicorn은 자기 로거만 설정하므로, 앱 로거의 출력을 명시적으로 붙인다.
# 로그는 stdout/stderr로만 나간다 — 파일에 쓰지 않는다 (services.md § 컨테이너 사양).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

#: 빌드된 프론트엔드가 놓이는 자리. `deploy/Dockerfile`의 프론트 빌드 스테이지가
#: `frontend/dist`를 여기로 복사한다. **개발 중에는 없다** — 그때는 Vite dev
#: 서버가 SPA를 서빙하고 이 앱은 API만 담당한다 (FR-9.5).
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """기동 시 DB 연결을 확인하고, 종료 시 커넥션 풀을 정리한다.

    **기동 시 DB를 확인하는 이유** (FR-9.2) — compose의
    `depends_on: condition: service_healthy`가 db healthcheck를 기다리지만,
    MariaDB는 ping에 응답하면서도 초기화 스크립트를 돌리는 중일 수 있다.
    여기서 확인하지 않으면 첫 사용자 요청이 오류가 된다.

    연결에 끝내 실패하면 `DatabaseUnavailableError`가 올라가 프로세스가 죽는다 —
    DB 없이 뜬 앱은 모든 요청에 실패하므로, 조용히 사는 것보다 죽는 편이 낫다.
    """
    await wait_for_database()
    # 판정 백엔드를 미리 올린다. 인코더는 299MB를 읽느라 첫 호출이 수 초 걸려
    # AI_TIMEOUT_SECONDS(4.0)를 넘기고, 그러면 첫 메시지가 failed가 된다.
    # 워밍업 실패는 기동을 막지 않는다 — 판정만 느려질 뿐 앱은 살아야 한다.
    await judgment_backend.warmup()
    logger.info("애플리케이션을 시작합니다 (uvicorn 워커 1개, CON-1)")
    try:
        yield
    finally:
        # SIGTERM 이후 여기까지 온다. uvicorn이 진행 중 요청과 열린 WebSocket을
        # 먼저 정리하고(graceful shutdown), 그 다음 이 블록이 돈다.
        # compose의 `stop_grace_period: 15s`가 그 시간을 준다.
        logger.info("애플리케이션을 종료합니다")
        await dispose_engine()


app = FastAPI(
    title="career-jikimi",
    description="문맥을 벗어난 오발송 메시지를 전송 전에 경고하는 채팅 데모",
    version="0.1.0",
    lifespan=lifespan,
)

register_error_handlers(app)

# --------------------------------------------------------------------------
# CORS (FR-9.5)
# --------------------------------------------------------------------------
# **비어 있으면 미들웨어를 아예 붙이지 않는다.** 배포 구성에서는 FastAPI가
# 프론트엔드를 같은 오리진에서 서빙하므로 CORS가 필요 없다. 필요 없는 미들웨어를
# 기본으로 켜두면 나중에 왜 켜져 있는지 아무도 모르게 되고, 넓게 열린 설정이
# 그대로 남는다.
#
# compose 프로파일로 나누지 않고 환경변수로 분기하는 이유 —
# `settings`에 이미 `CORS_ORIGINS`가 있어 프로파일을 새로 만들면 같은 설정이
# 두 곳으로 갈라진다 (code-generation-plan.md § 열린 항목).
if settings.cors_origins:
    logger.info("CORS를 허용합니다: %s", ", ".join(settings.cors_origins))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # 자격증명(Authorization 헤더)을 허용한다. `allow_origins`가 명시적 목록이라
        # 와일드카드와 함께 쓸 수 없는 조합 문제는 발생하지 않는다.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# --------------------------------------------------------------------------
# /health
# --------------------------------------------------------------------------
async def db_health_probe() -> bool:
    """DB 도달 가능 여부. `/health`의 유일한 의존성.

    의존성으로 뺀 이유는 테스트에서 실제 DB 없이 정상/실패 두 갈래를 모두
    검증하기 위해서다 (`app.dependency_overrides`).
    """
    return await check_database()


@app.get("/health", tags=["ops"])
async def health(db_ok: bool = Depends(db_health_probe)) -> JSONResponse:
    """컨테이너 헬스체크 엔드포인트.

    **얕은 체크와 깊은 체크를 나누지 않고 하나만 둔다**
    (code-generation-plan.md § 열린 항목). `services.md`가 "DB 연결까지 확인하는
    얕은 체크"로 이미 정했고, 데모 규모에서 두 엔드포인트를 나눌 값어치가 없다.
    타임아웃이 2초로 짧아 DB가 잠깐 느릴 때의 오탐도 억제된다.

    Returns:
        200 `{"status": "ok", "db": "ok"}` — DB에 닿았다.
        503 `{"status": "unavailable", "db": "error"}` — 닿지 못했다.

    503을 쓰는 이유 — DB 도달 실패는 서버 버그(500)가 아니라 의존 서비스
    이용 불가다. Docker HEALTHCHECK와 사람이 원인을 오해하지 않게 한다.
    """
    if db_ok:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok", "db": "ok"})
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "unavailable", "db": "error"},
    )


# ==========================================================================
# 라우터 등록 지점 — U2~U5가 여기에 붙인다
# ==========================================================================
#
# **라우터는 반드시 이 위치, 즉 아래 정적 파일 서빙보다 먼저 등록해야 한다.**
# SPA 폴백이 `/{spa_path:path}`라는 catch-all이라서, 뒤에 등록된 GET 경로는
# 전부 이 폴백에 가려진다 (Starlette는 라우트를 등록 순서대로 매칭한다).
#
# 경로에 `/api` 접두사를 두지 않는다 — `application-design/components.md`가
# `POST /auth/signup`, `GET /rooms/{id}` 처럼 접두사 없는 경로로 확정했다.
# ==========================================================================

# U3 auth-friends — /auth/signup, /auth/login, /users/search, /friends*
# (import는 파일 상단에 있다. 등록 **순서**가 이 위치의 요구사항이다.)
app.include_router(auth_router)
app.include_router(friends_router)

# U2 judgment-core — PATCH /judgments/{id}
# **이 단위의 유일한 HTTP 표면이다.** 지표는 화면이 아니라 CLI로 노출하므로
# (ADR-008) `GET /metrics`도 관리자 화면도 없다.
app.include_router(judgment_router)

# U4 rooms-realtime — POST/GET /rooms, GET /rooms/{id}, POST /rooms/{id}/read,
# PATCH /rooms/{id}/ai-check, 그리고 WebSocket /ws.
#
# **WebSocket 라우터도 SPA 폴백보다 먼저 등록한다.** 폴백이 `@app.get`이라 프로토콜이
# 달라 실제로 가려지지는 않지만, 두 등록을 떼어놓으면 "왜 하나만 위에 있지"를 나중에
# 되묻게 된다. 등록 순서의 규칙을 하나로 유지한다.
app.include_router(rooms_router)
app.include_router(ws_router)

# U5 messaging — POST/GET /rooms/{id}/messages, POST/DELETE /messages/{id}/report.
#
# **`rooms_router`보다 뒤에 있어도 가려지지 않는다.** Starlette는 등록 순서대로
# 매칭하지만 `GET /rooms/{room_id}`와 `GET /rooms/{room_id}/messages`는 경로 세그먼트
# 수가 달라 서로 겹치지 않는다. SPA 폴백(`/{spa_path:path}`)만이 catch-all이며,
# 그것보다 앞이라는 점이 이 위치의 요구사항이다.
app.include_router(messages_router)


def _mount_spa(application: FastAPI) -> None:
    """빌드된 프론트엔드를 서빙한다. `static/`이 없으면 아무것도 하지 않는다 (FR-9.5).

    없을 때 조용히 넘어가는 것이 개발 경로다 — 개발 중에는 Vite dev 서버가 SPA를
    서빙하고 이 앱은 API만 담당한다. 여기서 예외를 던지면 백엔드만 띄워
    개발할 수 없게 된다.
    """
    if not STATIC_DIR.is_dir():
        logger.info("static/ 이 없어 정적 파일 서빙을 건너뜁니다 (개발 구성)")
        return

    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        # 디렉터리는 있는데 index.html이 없다 = 빌드가 실패했거나 복사가 덜 됐다.
        # 조용히 넘기면 사용자에게 빈 화면이 뜨고 원인을 알 수 없다.
        logger.error("static/index.html 이 없습니다. 프론트엔드 빌드를 확인하세요")
        return

    logger.info("정적 파일을 서빙합니다: %s", STATIC_DIR)

    @application.get("/{spa_path:path}", include_in_schema=False)
    async def spa(spa_path: str) -> FileResponse:
        """요청 경로에 해당하는 파일이 있으면 그것을, 없으면 `index.html`을 준다.

        SPA 폴백이 필요한 이유 — 클라이언트 라우팅에서 사용자가 `/rooms/12`를
        새로고침하면 브라우저가 그 경로를 서버에 묻는데, 서버에 그런 파일은 없다.
        `index.html`을 주면 SPA가 다시 그 경로를 해석한다.

        경로 탈출 방어: `resolve()` 후 STATIC_DIR 하위인지 확인한다. 이 검사가
        없으면 `GET /../../etc/passwd` 류의 요청으로 이미지 안의 임의 파일을
        읽을 수 있다.
        """
        if spa_path:
            candidate = (STATIC_DIR / spa_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(STATIC_DIR):
                return FileResponse(candidate)
        return FileResponse(index_file)


_mount_spa(app)
