"""`core/config` 테스트 — FR-1.4, NFR-6, FR-9.5(`CORS_ORIGINS`).

검증하는 것:
  - 필수 키가 없으면 **기동이 막힌다** (FR-1.4의 핵심 장치)
  - 공백만 있는 비밀도 거부한다
  - 기본값이 설계 문서와 일치한다 (`components.md` § core/config)
  - `CORS_ORIGINS` 파싱 (FR-9.5)
  - 비밀이 repr/str/model_dump에 노출되지 않는다 (NFR-6)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings

#: 필수 세 키. 이 값들은 검증만을 위한 자리 채우기이며 실제 접속에 쓰이지 않는다.
_REQUIRED: dict[str, str] = {
    "DATABASE_URL": "mysql+asyncmy://127.0.0.1:3306/unused?charset=utf8mb4",
    "JWT_SECRET": "placeholder-value",
    "OPENAI_API_KEY": "placeholder-value",
}

#: 기본값을 갖는 키. 개발자 환경의 환경변수가 기본값 테스트를 흔들지 않도록
#: 테스트 시작 시 지운다.
_OPTIONAL_KEYS: tuple[str, ...] = (
    "JWT_ALGORITHM",
    "JWT_EXPIRE_MINUTES",
    "OPENAI_MODEL",
    "AI_CONTEXT_N",
    "AI_VERDICT_THRESHOLD",
    "AI_TIMEOUT_SECONDS",
    "CORS_ORIGINS",
)


def _build(**overrides: object) -> Settings:
    """검증 규칙을 확인하기 위해 `Settings`를 직접 만든다.

    `_env_file=None` — 개발자 머신의 `.env`가 테스트 결과를 바꾸지 않게 한다.
    """
    return Settings(_env_file=None, **{**_REQUIRED, **overrides})  # type: ignore[arg-type]


def test_missing_required_keys_block_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """필수 세 키가 없으면 `settings` 생성이 실패한다 (FR-1.4, NFR-6).

    이것이 "조용히 빈 비밀로 도는 앱"을 막는 유일한 장치다. 이 테스트가 깨지면
    앱이 빈 API 키로 기동해 첫 판정 호출에서야 실패한다 — 데모 중에 터진다.
    """
    for key in _REQUIRED:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)  # type: ignore[call-arg]

    missing = {str(error["loc"][0]) for error in excinfo.value.errors()}
    assert missing == set(_REQUIRED)


@pytest.mark.parametrize("key", ["JWT_SECRET", "OPENAI_API_KEY"])
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_secret_is_rejected(key: str, blank: str) -> None:
    """빈 값·공백만 있는 비밀도 거부한다.

    `min_length=1`만으로는 `" "`가 통과한다. `.env`에 `JWT_SECRET= ` 같은 줄이
    남아 있는 상황이 실제로 흔하다.
    """
    with pytest.raises(ValidationError):
        _build(**{key: blank})


def test_blank_database_url_is_rejected() -> None:
    """DB 접속 정보도 FR-1.4가 말하는 비밀이다. 빈 값이면 기동을 막는다."""
    with pytest.raises(ValidationError):
        _build(DATABASE_URL="   ")


def test_defaults_match_the_design(monkeypatch: pytest.MonkeyPatch) -> None:
    """기본값이 `components.md` § core/config와 일치한다.

    `AI_CONTEXT_N`(10)과 `AI_VERDICT_THRESHOLD`(0.7)는 설계 문서가 명시한 값이다.

    **`AI_TIMEOUT_SECONDS`가 5가 아닌 이유를 여기 적어둔다** — 숫자만 보면 FR-8.1의
    "3~5초" 범위에서 상한을 고르는 편이 자연스러워 보여, 이 단언을 5로 "되돌리는"
    수정이 나오기 쉽다. 5는 두 시도의 타임아웃 합만으로 BR-6.7의 총 상한 10초를
    정확히 채워 여유가 0이고, `judge()`가 모델 호출 밖에서 하는 커밋 왕복과 연결
    비용이 그 위에 얹혀 NFR-1의 "최악 10초"를 넘긴다. 4가 그 여유를 만든다.

    그 근거를 숫자가 아니라 부등식으로 고정하는 것은 아래
    `test_default_timeout_leaves_margin_under_the_total_budget`이다.
    """
    for key in _OPTIONAL_KEYS:
        monkeypatch.delenv(key, raising=False)

    config = _build()

    assert config.AI_CONTEXT_N == 10
    assert config.AI_VERDICT_THRESHOLD == pytest.approx(0.7)
    assert config.AI_TIMEOUT_SECONDS == pytest.approx(4.0)
    assert config.JWT_ALGORITHM == "HS256"
    assert config.JWT_EXPIRE_MINUTES == 1440
    assert config.OPENAI_MODEL == "gpt-4o-mini"
    # 비어 있으면 CORS 미들웨어를 붙이지 않는다는 뜻이다 (FR-9.5).
    assert config.cors_origins == []


def test_default_timeout_leaves_margin_under_the_total_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기본 타임아웃 × 2가 총 예산보다 **작다** — BR-6.7, NFR-1.

    위 테스트는 값을 고정하지만 이 테스트는 **규칙을 고정한다.** 기본값을 얼마로
    바꾸든, 두 번의 시도(최초 1회 + 재시도 1회, BR-6.7)가 `TOTAL_BUDGET_SECONDS`를
    다 써버리면 여기서 걸린다.

    **등호를 허용하지 않는 것이 요점이다.** 합이 예산과 정확히 같으면(5초일 때가
    그렇다) 남는 여유가 0이고, `judge()`가 모델 호출 밖에서 하는 두 번의 커밋
    왕복(BR-6.8의 호출 전 기록·호출 후 갱신)이 그대로 초과분이 된다. 그 시간은
    `call_model()`의 예산 계산에 잡히지 않지만 **사용자는 기다린다** — NFR-1이 재는
    것이 그 시간이다.

    `settings`(모듈 전역)가 아니라 새로 만든 객체를 보는 이유 — 개발자 머신의
    `.env`나 환경변수가 아니라 **코드가 정한 기본값**이 이 부등식을 지키는지가
    질문이다. 환경변수를 직접 주입하는 배포에서는 그 기본값이 유일한 출처다.
    """
    from app.judgment.constants import MAX_ATTEMPTS, TOTAL_BUDGET_SECONDS

    for key in _OPTIONAL_KEYS:
        monkeypatch.delenv(key, raising=False)

    default_timeout = _build().AI_TIMEOUT_SECONDS

    assert MAX_ATTEMPTS * default_timeout < TOTAL_BUDGET_SECONDS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", []),
        ("   ", []),
        ("http://localhost:5173", ["http://localhost:5173"]),
        (
            "http://localhost:5173,http://127.0.0.1:5173",
            [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
            ],
        ),
        # 사람이 손으로 쓰는 값이라 공백과 빈 항목이 섞인다
        (" http://a , http://b ", ["http://a", "http://b"]),
        ("http://a,,http://b,", ["http://a", "http://b"]),
    ],
)
def test_cors_origins_parsing(raw: str, expected: list[str]) -> None:
    """쉼표로 구분한 오리진 목록을 파싱한다 (FR-9.5).

    `list[str]`이 아니라 `str`로 받는 이유는 pydantic-settings가 복합 타입을
    JSON으로 파싱하려 하기 때문이다 — `http://a,http://b`는 JSON이 아니다.
    """
    assert _build(CORS_ORIGINS=raw).cors_origins == expected


def test_secrets_are_not_exposed_in_repr_or_dump() -> None:
    """비밀이 repr/str/model_dump에 문자열로 새지 않는다 (NFR-6).

    이 경로가 새면 예외 메시지·로그·pydantic 검증 오류에 키가 그대로 찍힌다.
    """
    # 값 자체가 "찾아야 하는 문자열"이므로, FR-1.4의 저장소 전체 비밀 검색에
    # 걸리지 않도록 비밀처럼 보이지 않는 문장을 쓴다.
    signing_probe = "NOT-A-SECRET-probe-one"
    api_probe = "NOT-A-SECRET-probe-two"
    config = _build(JWT_SECRET=signing_probe, OPENAI_API_KEY=api_probe)

    exposed = " ".join([repr(config), str(config), repr(config.model_dump())])

    assert signing_probe not in exposed
    assert api_probe not in exposed
    # 꺼내는 것은 명시적 호출로만 된다
    assert config.JWT_SECRET.get_secret_value() == signing_probe
    assert config.OPENAI_API_KEY.get_secret_value() == api_probe


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AI_VERDICT_THRESHOLD", -0.1),
        ("AI_VERDICT_THRESHOLD", 1.1),
        ("AI_CONTEXT_N", 0),
        ("AI_CONTEXT_N", -3),
        ("AI_TIMEOUT_SECONDS", 0),
        ("JWT_EXPIRE_MINUTES", 0),
    ],
)
def test_out_of_range_values_are_rejected(key: str, value: float) -> None:
    """범위를 벗어난 값은 기동 시점에 막는다.

    `AI_VERDICT_THRESHOLD=1.5`는 "아무것도 부적절하지 않다"가 되어 기능이 조용히
    죽는다. `AI_CONTEXT_N=0`은 문맥 없이 판정하게 만든다. 둘 다 런타임에는
    오류가 아니라 **잘못된 정상 동작**으로 보이므로 여기서 잡아야 한다.
    """
    with pytest.raises(ValidationError):
        _build(**{key: value})


def test_settings_singleton_exposes_the_promised_surface() -> None:
    """`settings` 싱글턴이 `components.md`가 약속한 이름을 모두 갖는다.

    U2~U5가 이 이름을 그대로 import한다. 바꾸면 네 단위가 깨진다
    (`unit-of-work-dependency.md` § U1의 제공 계약).
    """
    for name in (
        "DATABASE_URL",
        "JWT_SECRET",
        "OPENAI_API_KEY",
        "AI_CONTEXT_N",
        "AI_VERDICT_THRESHOLD",
        "AI_TIMEOUT_SECONDS",
        "CORS_ORIGINS",
    ):
        assert hasattr(settings, name), f"{name}이 settings에 없다"
