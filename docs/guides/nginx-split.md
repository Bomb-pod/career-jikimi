# nginx로 프론트/백엔드 컨테이너 분리하기

기본 구성(`docker-compose.yml`)은 FastAPI가 정적 파일까지 서빙한다(FR-9.5, ADR-002).
이 문서는 **그것을 대체하지 않는 병행 구성**이다. 둘 다 그대로 두고 `-f`로 골라 띄운다.

```bash
# 기본 구성 (그대로 유지됨)
docker compose up -d --build

# nginx 분리 구성
cd frontend && npm run build && cd ..     # 바인드 마운트를 쓰므로 한 번은 필요
docker compose -f compose.nginx.yml up -d --build
# → http://localhost      (포트 80이라 주소에 포트를 안 쓴다)
```

**`-d`를 빼면 터미널이 로그에 붙잡힌다.** 컨테이너 로그가 계속 흘러나오고
Ctrl+C를 누르면 컨테이너가 내려간다. 로그는 필요할 때만 따로 본다:

```bash
docker compose -f compose.nginx.yml logs -f          # 전체
docker compose -f compose.nginx.yml logs -f web      # nginx만
docker compose -f compose.nginx.yml logs -f app      # 백엔드만
docker compose -f compose.nginx.yml logs --tail 50 app
```

내릴 때는 `docker compose -f compose.nginx.yml down` (`-v`는 붙이지 말 것 —
DB 볼륨까지 지운다).

둘은 **같은 compose 프로젝트**이므로 DB 볼륨을 공유한다 — 계정과 대화가
그대로 남는다. 자세한 이유는 아래 "알아둘 차이".

80이 이미 잡혀 있으면 `.env`에 `WEB_HOST_PORT=8080`을 넣는다.
확인은 윈도우에서 `netstat -ano | findstr :80`, 맥·리눅스에서 `sudo lsof -i :80`.

## 추가되는 파일 셋

| 파일 | 역할 |
|---|---|
| `deploy/nginx.conf` | 정적 서빙 + API/WS 프록시 규칙 |
| `deploy/Dockerfile.web` | 프론트 빌드 → nginx 이미지 |
| `compose.nginx.yml` | web · app · db 3서비스 |

기존 `deploy/Dockerfile`, `docker-compose.yml`, 백엔드 코드는 **한 줄도 고치지 않았다.**

## 구조

```
브라우저 ──▶ web (nginx:80) ─┬─ /assets/**   → 정적 파일, 1년 캐시
                             ├─ /            → index.html (SPA 폴백)
                             ├─ /auth /users /friends
                             │  /rooms /messages /judgments /health
                             │               → app:8000 프록시
                             └─ /ws          → app:8000 프록시 (업그레이드)

                                app (FastAPI) ──▶ db (MariaDB)
                                app은 포트를 노출하지 않는다
```

## 왜 백엔드 코드를 안 고쳐도 되나

`app/main.py`의 `_mount_spa()`가 이렇게 되어 있다.

```python
if not STATIC_DIR.is_dir():
    logger.info("static/ 이 없어 정적 파일 서빙을 건너뜁니다 (개발 구성)")
    return
```

정적 파일이 없으면 조용히 API 전용 서버가 된다. 원래 Vite dev 서버를 위해 넣은
경로인데, 그대로 이 구성에도 맞는다.

지금은 `app` 이미지에 `static/`이 여전히 구워진다 — `deploy/Dockerfile`을 그대로
쓰기 때문이다. nginx가 앞에 있어 그쪽으로 요청이 가지 않으므로 무해하고,
**백엔드 이미지 정의를 한 곳으로 유지하는 값이 수백 KB 중복보다 크다고 판단했다.**
분리를 확정하게 되면 그때 `deploy/Dockerfile`에서 프론트 스테이지를 빼면 된다.

## 검증한 것

실제 nginx 1.24로 스텁 백엔드를 세워 라우팅을 전부 확인했다.

| 항목 | 결과 |
|---|---|
| `/health` `/auth/me` `/rooms` `/rooms/12/messages` `/messages/5/report` `/judgments/7` `/users/search` `/friends` | 전부 app으로 프록시 |
| `/` `/login` `/rooms-not-api` `/healthcheck` | 전부 `index.html` (SPA 폴백) |
| `/ws` 업그레이드 요청 | **HTTP/1.1 101 Switching Protocols** |
| `/ws` 일반 GET | 정상 프록시 (`Connection: close`) |
| `/assets/index-abc123.js` | 200, `Cache-Control: public, max-age=31536000, immutable` (1줄) |
| `/assets/nope.js` | **404** — 폴백하지 않음 |
| `/index.html` | `Cache-Control: no-store, must-revalidate` |
| `nginx -t` | 문법 통과 |

`/rooms-not-api`가 SPA로 가고 `/rooms/12`가 API로 가는 이유는 프록시 정규식이
`^/(auth|…|health)(/|$)`로 **경계를 요구**하기 때문이다. 이게 없으면
`/roomsomething` 같은 경로가 백엔드로 새어 들어간다.

## 걸려 넘어지기 쉬운 자리

**1. WebSocket 업그레이드 헤더 — 가장 흔한 실패**

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade    $http_upgrade;
proxy_set_header Connection $connection_upgrade;
```

이 셋이 없으면 핸드셰이크가 101로 못 올라가고 400이 떨어진다. `Connection`을
`"upgrade"`로 고정하지 않고 `map`을 쓰는 이유는, 고정하면 일반 HTTP 요청의
keepalive가 깨지기 때문이다.

**2. `proxy_read_timeout` 기본 60초**

이 앱은 타이핑 인디케이터도 읽음 표시도 없어서(범위 밖) 대화가 없으면
프레임이 전혀 오가지 않는다. 기본값이면 **1분 뒤 조용히 끊긴다.**
`3600s`로 올려두었다.

**3. `expires`와 `add_header Cache-Control`을 같이 쓰지 말 것**

둘 다 쓰면 `Cache-Control` 헤더가 두 줄로 나간다. 처음에 그렇게 썼다가
검증에서 잡아 `add_header` 하나로 정리했다.

**4. `/assets/`는 폴백하면 안 된다**

없는 자산에 `index.html`을 주면 브라우저가 JS를 기대한 자리에서 HTML을
파싱하다 `Unexpected token '<'`로 죽는다. `try_files $uri =404;`로 막았다.

**5. 프록시 경로 목록이 두 곳에 있다**

`deploy/nginx.conf`와 `frontend/vite.config.ts`의 `BACKEND_PATHS`. 새 최상위 라우터가
생기면 **두 곳을 같이 고쳐야 한다.** 빠뜨리면 JSON을 기대한 자리에
`<!doctype html>`이 온다.

**6. `depends_on: service_healthy`가 필요하다**

nginx는 설정을 읽는 시점에 upstream 이름을 해석한다. `app`보다 먼저 뜨면
`host not found in upstream`으로 죽는다.

**7. `deploy/Dockerfile.web`에서 `nginx -t`를 돌리면 안 된다**

같은 이유다. 처음에 빌드 시점 검사로 넣었다가 뺐다. 빌드 중에는 compose
네트워크도 `app` 컨테이너도 없으므로 **설정이 멀쩡해도** 이렇게 죽는다.

```
#47 [web runtime 5/5] RUN nginx -t
#47 3.642 nginx: [emerg] host not found in upstream "app:8000"
```

즉 그 자리의 `nginx -t`는 문법이 아니라 "지금 app이 떠 있는가"를 검사한다.
빌드 단계에서 그건 언제나 거짓이다. 실제로 확인했다 — 같은 설정에 `app`
이름만 해석되게 해주면 그대로 통과한다.

설정 검사는 컨테이너가 뜰 때 nginx가 어차피 한다. 그때는 `depends_on`이
app을 먼저 띄워둔 뒤라 이름이 풀린다. 문법만 미리 보고 싶으면 호스트에서:

```bash
docker run --rm -v "$PWD/deploy/nginx.conf:/etc/nginx/conf.d/x.conf:ro" \
  nginx:1.27-alpine sh -c \
  'sed -i s/app:8000/127.0.0.1:8000/ /etc/nginx/conf.d/x.conf && nginx -t'
```

## 알아둘 차이

| | `docker-compose.yml` | `compose.nginx.yml` |
|---|---|---|
| 서비스 | app · db | **web** · app · db |
| 정적 파일 | FastAPI | nginx |
| 프론트 수정 반영 | 이미지 재빌드 | `npm run build`만 |
| 접속 주소 | `localhost:8000` | **`localhost`** (포트 80) |
| app 포트 | 8000 직접 노출 | 미노출 (web만 진입점) |
| DB 호스트 포트 | 3307 | 3307 (동일) |
| DB 볼륨 | `mini_project_db_data` | **같은 볼륨** |
| CORS | 불필요 | **여전히 불필요** |

**CORS는 여전히 필요 없다.** nginx가 정적과 API를 같은 오리진으로 묶기 때문이다.
`.env`의 `CORS_ORIGINS`는 비워둔 채로 둘 것 — 채우면 불필요한 헤더만 붙는다.
정적 파일을 별도 도메인(S3/CDN)에 올리는 방식이었다면 그때는 CORS가 필수가 된다.

**DB 데이터는 그대로 유지된다.** 두 파일 모두 `name:`을 두지 않아 compose가
디렉터리 이름(`mini_project`)을 프로젝트 이름으로 쓴다. 즉 **둘은 같은 프로젝트의
두 가지 기동 방식**이고, 볼륨과 네트워크를 공유한다. 계정·대화를 다시 만들 필요가 없다.

겹쳐서 문제가 되지 않는 이유는 **애초에 동시에 띄울 수 없기 때문이다** — 두 파일이
같은 프로젝트의 같은 서비스 이름(`app`·`db`)을 정의하므로, 한쪽을 올리면 compose가
다른 쪽 컨테이너를 그 정의로 다시 만든다. 호스트 포트가 달라도(80 vs 8000)
둘이 나란히 살지는 못한다.

`db` 서비스 정의를 기본 구성과 **한 글자도 다르지 않게** 맞춰둔 것도 같은 이유다.
다르면 구성을 바꿔 띄울 때마다 compose가 db를 지웠다 다시 만든다. 실제로 대조해
확인했다 — `image` `command` `environment` `volumes` `healthcheck` `ports` `restart`
전부 일치하므로 **db 컨테이너는 재생성되지 않고, app만 다시 만들어진다.**

`docker-compose.yml`의 db를 고치면 `compose.nginx.yml`의 db도 같이 고칠 것.

## 두 구성 전환하기

```bash
# 분리 구성으로
docker compose -f compose.nginx.yml up -d --build

# 기본 구성으로 되돌리기
docker compose up -d --remove-orphans
```

`--remove-orphans`가 없으면 web 컨테이너가 고아로 남아 계속 떠 있고
"orphan containers" 경고가 뜬다.

## 여기서 더 나간다면

원격 배포로 나갈 때 nginx가 앞에 있으면 세 가지가 한꺼번에 풀린다.

- TLS 종단 — certbot이나 앞단 LB
- HANDOFF의 `starlette` 취약점 8건 — "로컬 전용이라 원격 도달 경로 없음"이라는
  전제가 깨지는 시점이다. nginx가 앞에 있으면 요청 필터링 지점이 생긴다
- `/docs`·`/redoc` 접근 제어 — 지금은 열려 있다. `deploy/nginx.conf`의 해당 블록에
  `allow`/`deny`나 basic auth를 붙이면 된다

반대로 **워커 확장은 nginx로 해결되지 않는다.** `ws_registry`가 프로세스 메모리에
있어서(CON-1) app 인스턴스를 늘리면 로드밸런싱이 오히려 문제를 만든다.
그건 Redis pub/sub이 먼저다.
