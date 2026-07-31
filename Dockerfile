# career-jikimi 애플리케이션 이미지 (FR-9.1, FR-9.4, services.md § 컨테이너 사양)
#
# 스테이지 3개:
#   1. frontend-build — node에서 SPA를 빌드한다
#   2. python-build   — 컴파일러로 wheel을 만든다 (asyncmy·httptools는 C 확장이다)
#   3. runtime        — 위 둘의 산출물만 받는다. 컴파일러가 없다
#
# **스테이지를 나누는 이유** — 런타임 이미지에 gcc와 node가 남지 않는다.
# 공격 표면이 줄고 이미지가 작아지며, 프론트 파일 하나를 고쳐도 pip 설치가
# 다시 돌지 않는다(백엔드 레이어의 캐시가 살아 있다).

# ===========================================================================
# 1. 프론트엔드 빌드
# ===========================================================================
FROM node:22-alpine AS frontend-build

WORKDIR /build

# package.json만 먼저 복사해 의존성 레이어를 소스와 분리한다.
# 소스만 고쳤을 때 npm ci가 다시 돌지 않는다.
COPY frontend/package.json frontend/package-lock.json ./
# npm ci는 package-lock.json을 그대로 재현한다 — install과 달리 버전이 흔들리지 않는다.
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ===========================================================================
# 2. Python wheel 빌드
# ===========================================================================
FROM python:3.12-slim AS python-build

# asyncmy와 uvicorn[standard]의 httptools는 C 확장이다. 휠이 없는 플랫폼에서는
# 여기서 컴파일하고, 그 결과만 런타임으로 넘긴다.
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY backend/requirements.txt backend/requirements-encoder.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# 판정 인코더(JUDGMENT_BACKEND=encoder)용. **CPU 전용 인덱스를 쓴다** —
# 기본 PyPI 빌드는 CUDA를 포함해 이미지가 2GB 넘게 커지는데, 이 컨테이너에는
# GPU를 붙이지 않으므로 순전히 낭비다. transformers는 PyPI에 있어 따로 받는다.
RUN pip wheel --no-cache-dir --wheel-dir /wheels \
      --index-url https://download.pytorch.org/whl/cpu torch
RUN pip wheel --no-cache-dir --wheel-dir /wheels "transformers>=4.48"

# ===========================================================================
# 3. 런타임
# ===========================================================================
FROM python:3.12-slim AS runtime

# PYTHONDONTWRITEBYTECODE: .pyc를 남기지 않는다 (읽기 전용 파일시스템과 호환).
# PYTHONUNBUFFERED: 로그가 버퍼에 갇히지 않는다 — 컨테이너 로그는 즉시 보여야 한다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 휠만 받아 설치한다. --no-index로 네트워크를 아예 쓰지 않으므로,
# 런타임 이미지 빌드가 상류 인덱스 상태에 흔들리지 않는다.
COPY --from=python-build /wheels /wheels
COPY backend/requirements.txt backend/requirements-encoder.txt ./
RUN pip install --no-index --find-links=/wheels \
        -r requirements.txt -r requirements-encoder.txt \
    && rm -rf /wheels

# 백엔드 소스
COPY backend/app ./app
# 파인튜닝 인코더 가중치(약 300MB). 바인드 마운트가 없는 구조라 이미지에 굽는다.
# local_encoder.model_dir()의 기본 경로가 /app/models/context_checker 다.
COPY backend/models ./models
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/docker-entrypoint.sh ./docker-entrypoint.sh

# 빌드된 SPA를 app/main.py가 찾는 자리에 놓는다 (FR-9.5).
# main.py의 STATIC_DIR이 /app/static을 가리킨다.
COPY --from=frontend-build /build/dist ./static

# COPY가 실행 비트를 보존하지 않는 경우(Windows 체크아웃 등)를 대비해 명시한다.
RUN chmod +x ./docker-entrypoint.sh

# --------------------------------------------------------------------------
# 비루트 실행 (services.md § 컨테이너 사양)
# --------------------------------------------------------------------------
# 앱은 파일을 쓰지 않으므로 /app의 소유권을 바꿀 필요조차 없다. 읽기만 하도록
# 남겨두면 컨테이너가 침해되어도 코드를 고칠 수 없다.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# `services.md`가 정한 "DB 연결까지 확인하는 얕은 체크".
# curl이 없는 slim 이미지라 python으로 확인한다 — 그것 하나로 도구를 더 설치하지 않는다.
# /health가 503이면 urlopen이 HTTPError를 던지고 종료 코드가 0이 아니게 된다.
HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# 엔트리포인트가 alembic을 먼저 돌리고 uvicorn을 exec으로 띄운다 (FR-9.2).
ENTRYPOINT ["./docker-entrypoint.sh"]
