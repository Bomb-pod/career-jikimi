# DB 직접 확인하기

## 접속 정보

| | 값 |
|---|---|
| 호스트 | `127.0.0.1` |
| 포트 | **3307** (`.env`의 `DB_HOST_PORT`로 변경) |
| 데이터베이스 | `career_jikimi` |
| 사용자 | `app` / 비밀번호 `app` |
| root | `root` / `rootpw` |

> 위 계정은 `.env.example` 기본값이다. **본인 `.env`의
> `MARIADB_USER` / `MARIADB_PASSWORD` / `MARIADB_ROOT_PASSWORD`를 확인할 것.**

`127.0.0.1`에만 바인딩되어 같은 PC에서만 붙는다. 같은 공유기의 다른 기기에서는
안 보인다.

```bash
docker compose up -d      # 포트 반영에 재기동이 필요하다
docker compose ps         # db 행에 127.0.0.1:3307->3306/tcp 가 보여야 한다
```

## 포트 없이 보기

포트를 열지 않아도 컨테이너 안에서는 언제든 볼 수 있다.

```bash
docker compose exec db mariadb -u app -papp career_jikimi
```

## 시드 데이터 확인용 쿼리

```sql
-- 방별 메시지 수. AI_CONTEXT_N=10 미만이면 판정을 건너뛴다.
SELECT r.id, r.name, r.last_seq, COUNT(m.id) AS msgs,
       IF(COUNT(m.id) >= 10, 'OK', '문맥 부족') AS ai
FROM rooms r LEFT JOIN messages m ON m.room_id = r.id
GROUP BY r.id ORDER BY r.id;

-- 특정 방의 대화 (판정에 들어가는 순서 그대로)
SELECT m.seq, u.display_name, m.body, m.verification_status
FROM messages m JOIN users u ON u.id = m.sender_id
WHERE m.room_id = 1 ORDER BY m.seq;

-- 방별 참여자와 AI 검증 토글
SELECT r.name, u.display_name, rm.ai_check_enabled, rm.last_read_seq
FROM room_members rm
JOIN rooms r ON r.id = rm.room_id JOIN users u ON u.id = rm.user_id
ORDER BY r.id, u.id;

-- 판정 로그 (메시지를 보내야 쌓인다)
SELECT id, room_id, context_from_seq, context_to_seq, score, threshold,
       verdict, user_action, latency_ms, created_at
FROM judgment_logs ORDER BY id DESC LIMIT 20;

-- verification_status 분포. 시드는 전부 disabled 라 성능 집계에서 빠진다.
SELECT verification_status, COUNT(*) FROM messages GROUP BY verification_status;

-- 성능 집계 모집단 (ok + flagged_sent 만 쓴다)
SELECT verdict, user_action, COUNT(*)
FROM judgment_logs WHERE verdict IS NOT NULL
GROUP BY verdict, user_action;
```

## 한글이 깨져 보이면

클라이언트 연결 설정에서 문자셋을 `utf8mb4`로 지정한다. 서버는 이미
`--character-set-server=utf8mb4`로 떠 있으므로 클라이언트 쪽 문제다.

```sql
SHOW VARIABLES LIKE 'character_set%';   -- 전부 utf8mb4 여야 한다
```

## 발표 전에 닫으려면

`docker-compose.yml`의 `db` 서비스에서 아래 두 줄을 지우고 `docker compose up -d`.

```yaml
    ports:
      - "127.0.0.1:${DB_HOST_PORT:-3307}:3306"
```
