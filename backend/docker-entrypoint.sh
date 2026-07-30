#!/bin/sh
# 컨테이너 기동 순서 (FR-9.2, services.md § 기동 순서):
#
#   alembic upgrade head  (실패 시 재시도)
#        |
#        +--> uvicorn (워커 1개, FR-9.4)
#
# **compose의 depends_on: service_healthy 만으로 부족한 이유** — MariaDB는
# `mariadb-admin ping`에 응답하면서도 초기화 스크립트(사용자·DB 생성)를 돌리는
# 중일 수 있다. 그때 alembic이 붙으면 "Access denied" 또는 "Unknown database"로
# 죽는다. 그래서 재시도를 함께 둔다.
#
# set -eu: 정의되지 않은 변수나 예상 못 한 실패에서 조용히 넘어가지 않는다.
set -eu

MIGRATION_MAX_ATTEMPTS="${MIGRATION_MAX_ATTEMPTS:-10}"

attempt=1
delay=1

while : ; do
    if alembic upgrade head; then
        echo "[entrypoint] 마이그레이션 적용 완료 (시도 ${attempt}회)"
        break
    fi

    if [ "${attempt}" -ge "${MIGRATION_MAX_ATTEMPTS}" ]; then
        echo "[entrypoint] 마이그레이션이 ${MIGRATION_MAX_ATTEMPTS}번 모두 실패했습니다. 종료합니다." >&2
        # 여기서 죽는 것이 맞다 — 스키마 없이 뜬 앱은 모든 요청에 실패하면서
        # 컨테이너는 살아 있는 것처럼 보인다.
        exit 1
    fi

    echo "[entrypoint] 마이그레이션 실패 (시도 ${attempt}/${MIGRATION_MAX_ATTEMPTS}) — ${delay}초 후 재시도" >&2
    sleep "${delay}"
    attempt=$((attempt + 1))
    # 지수 백오프, 상한 8초. 상한이 없으면 시도 간격이 금방 분 단위가 된다.
    delay=$((delay * 2))
    if [ "${delay}" -gt 8 ]; then
        delay=8
    fi
done

# exec으로 넘겨 uvicorn이 PID 1이 된다 — SIGTERM을 셸이 아니라 uvicorn이 직접
# 받아야 graceful shutdown이 돈다. 쉘이 PID 1이면 SIGTERM을 자식에게 전달하지
# 않아 열린 WebSocket이 그냥 끊긴다 (services.md § Graceful shutdown).
#
# --workers 1: 성능 판단이 아니라 정합성 요구다 (FR-9.4, CON-1). WebSocket 연결
# 레지스트리가 프로세스 메모리에 있어 워커를 늘리면 갈라진다.
#
# --timeout-graceful-shutdown 10: compose의 stop_grace_period(15초)보다 짧게 둔다.
# 반대면 SIGKILL이 먼저 와서 graceful shutdown이 끝까지 못 간다.
echo "[entrypoint] uvicorn을 시작합니다 (워커 1개)"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --timeout-graceful-shutdown 10 \
    --no-server-header
