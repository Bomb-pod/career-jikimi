"""`core/config` — 환경변수를 타입 붙은 설정 객체로 노출한다.

공개 표면은 **`settings` 싱글턴 하나**다
(`inception/application-design/components.md` § core/config).

    from app.core.config import settings
    settings.DATABASE_URL
    settings.JWT_SECRET.get_secret_value()

**경계**: 비밀은 여기를 통해서만 들어온다. 다른 모듈은 `os.environ`을 직접 읽지 않는다
(FR-1.4, NFR-6). 이 규칙이 깨지면 "어디서 이 값을 읽는가"가 흩어지고, 비밀이
로그·응답으로 새는 경로를 한곳에서 막을 수 없게 된다.

**기본값을 주지 않는 세 키** — `DATABASE_URL`, `JWT_SECRET`, `OPENAI_API_KEY`.
FR-1.4가 "비밀(JWT 서명 키, DB 접속 정보, OpenAI API 키)은 환경변수로 주입한다.
소스 코드에 하드코딩하지 않는다"를 요구하고, 그 수용 기준이 "소스 코드를 검색하면
API 키·비밀번호·서명 키에 해당하는 리터럴 문자열이 존재하지 않는다"이므로
이 파일에는 그 값의 예시조차 두지 않는다. 데모용 값은 `.env.example`에만 있다.

비어 있으면 `settings` 생성 시점에 `ValidationError`가 나고 앱이 기동하지 못한다.
조용히 빈 키로 도는 것보다 낫다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 저장소 루트 — `backend/app/core/config.py`에서 세 단계 위.
#: `.env`를 cwd와 무관하게 찾는 데 쓴다 (아래 `env_file` 참조).
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """환경변수에서 읽어 검증한 설정.

    직접 인스턴스화하지 말고 모듈 하단의 `settings`를 import한다. 단위 테스트에서
    검증 규칙을 확인할 때만 `Settings(_env_file=None, ...)`로 직접 만든다.
    """

    model_config = SettingsConfigDict(
        # 두 자리를 모두 본다 — 앞의 것이 이긴다.
        #
        # `".env"`(cwd 기준)만 두면 저장소 루트에서 돌릴 때만 잡히고, `backend/`에서
        # `python -m app.judgment.evaluate`처럼 돌리면 못 찾아 기동이 실패한다.
        # 컨테이너에서는 compose가 환경변수를 직접 주입하므로 둘 다 없어도 된다.
        #
        # **환경변수가 파일보다 우선한다** — pydantic-settings의 기본 우선순위이며,
        # CI·k8s가 파일 없이 주입하는 경로를 파일이 덮어쓰면 안 된다.
        env_file=(".env", _REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        # 모르는 환경변수를 무시한다. compose가 MARIADB_* 같은 db 컨테이너용 변수를
        # 같은 env_file로 주입하므로 "extra=forbid"면 앱이 기동하지 못한다.
        extra="ignore",
    )

    # --- DB (core/db) -----------------------------------------------------
    # 자격증명을 포함하므로 기본값이 없다 (FR-1.4).
    DATABASE_URL: str = Field(min_length=1)

    # --- 인증 (U3 auth) ---------------------------------------------------
    # SecretStr: repr/str/로그/에러 메시지에 값이 찍히지 않는다. 꺼낼 때만
    # `.get_secret_value()`를 명시적으로 호출한다 — 실수로 새지 않게 하는 장치다.
    JWT_SECRET: SecretStr
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = Field(default=1440, gt=0)

    # --- 판정 (U2 judgment) -----------------------------------------------
    OPENAI_API_KEY: SecretStr
    # ADR-005가 Structured Outputs(strict)를 요구한다. 지원 여부 확인은 U2 몫이다.
    OPENAI_MODEL: str = "gpt-4o-mini"
    # 판정에 넣는 문맥 메시지 개수 N (FR-6.2). 방 메시지가 N개 미만이면
    # U5가 판정을 건너뛰고 skipped_no_context로 남긴다 (FR-6.4).
    AI_CONTEXT_N: int = Field(default=10, gt=0)
    # score >= 임계값이면 '부적절' (FR-6.3). 판정 시점의 값이 judgment_logs.threshold에
    # 함께 저장되므로 나중에 바꿔도 과거 판정을 재현할 수 있다.
    AI_VERDICT_THRESHOLD: float = Field(default=0.7, ge=0.0, le=1.0)
    # 재시도는 1회뿐이므로 사용자 대기 상한이 대략 이 값의 **두 배**다 (FR-8.1).
    #
    # **기본값이 5가 아니라 4인 이유** — BR-6.7의 총 상한이 10초이고, NFR-1이 재는
    # 것은 사용자가 실제로 기다리는 전송 대기 시간이다. 5면 두 시도의 타임아웃 합만
    # 이미 정확히 10초라 여유가 0이고, `judge()`가 모델 호출 **밖에서** 하는 두 번의
    # 커밋 왕복(BR-6.8이 요구하는 호출 전 로그 기록과 호출 후 갱신)과 연결 수립·
    # 직렬화 비용이 그 위에 얹혀 상한을 넘긴다. 그 비용은 `judgment.client`의
    # `TOTAL_BUDGET_SECONDS` 예산 계산에 잡히지 않는다 — 예산은 API 호출 구간만
    # 재기 때문이다. 4면 8초 + 오버헤드로 2초의 여유가 남는다.
    #
    # **이 기본값이 실제로 쓰이는 경로다.** `.env`를 쓰지 않고 환경변수를 직접
    # 주입하는 배포(CI·k8s·필수 세 비밀만 남긴 `.env`)에서는 여기가 유일한 출처다.
    # 값을 올리려면 `2 * AI_TIMEOUT_SECONDS < TOTAL_BUDGET_SECONDS`를 먼저 확인한다 —
    # `tests/test_config.py`가 그 부등식을 지킨다.
    AI_TIMEOUT_SECONDS: float = Field(default=4.0, gt=0.0)

    # --- CORS (main.py, FR-9.5) -------------------------------------------
    # 쉼표로 구분한 오리진 목록. **비어 있으면 CORS 미들웨어를 아예 붙이지 않는다.**
    #
    # 왜 list[str]이 아니라 str인가 — pydantic-settings는 복합 타입(list 등)을 환경변수에서
    # 읽을 때 JSON으로 먼저 파싱하려 한다. `http://a,http://b`는 JSON이 아니라서 실패한다.
    # 원시 문자열로 받고 `cors_origins`가 쪼개면 `.env`에 사람이 읽을 수 있는 값을 쓸 수 있다.
    CORS_ORIGINS: str = ""

    @field_validator("DATABASE_URL", "JWT_ALGORITHM", "OPENAI_MODEL")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """공백만 있는 값을 거부한다.

        `min_length=1`은 `" "`를 통과시킨다. `.env`에 `JWT_ALGORITHM= ` 같은 줄이
        남아 있을 때 앱이 이상한 값으로 도는 것을 막는다.
        """
        if not value.strip():
            raise ValueError("빈 값이거나 공백만 있습니다")
        return value

    @field_validator("JWT_SECRET", "OPENAI_API_KEY")
    @classmethod
    def _reject_blank_secret(cls, value: SecretStr) -> SecretStr:
        """비밀이 빈 값이면 기동을 막는다 (FR-1.4, NFR-6).

        빈 API 키로 도는 앱은 첫 판정 호출에서야 실패한다 — 데모 중에 터진다.
        기동 시점에 실패하는 편이 낫다.
        """
        if not value.get_secret_value().strip():
            raise ValueError("필수 비밀이 비어 있습니다. 환경변수로 주입하세요")
        return value

    @property
    def cors_origins(self) -> list[str]:
        """`CORS_ORIGINS`를 오리진 목록으로 쪼갠다. 비어 있으면 빈 목록.

        빈 목록은 "CORS 미들웨어를 붙이지 않는다"는 뜻이다 (FR-9.5). 배포 구성에서는
        프론트엔드를 같은 오리진에서 서빙하므로 CORS가 필요 없고, 필요 없는 미들웨어를
        기본으로 켜두면 나중에 왜 켜져 있는지 아무도 모르게 된다.
        """
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


# 모듈 import 시점에 만들어진다 — 필수 키가 비어 있으면 여기서 즉시 실패한다.
# 이것이 FR-1.4/NFR-6의 "조용히 빈 비밀로 돌지 않는다"를 실제로 보장하는 지점이다.
settings = Settings()  # type: ignore[call-arg]  # 값은 환경변수에서 온다
