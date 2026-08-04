"""판정 백엔드 선택 — `openai` / `ollama` / `encoder`.

`.env`의 `JUDGMENT_BACKEND` 한 줄로 갈아끼운다. 코드 변경 없이 동작한다.

    JUDGMENT_BACKEND=openai     # OpenAI API (기본)
    JUDGMENT_BACKEND=ollama     # 로컬 LLM (Qwen 등). 키 불필요
    JUDGMENT_BACKEND=encoder    # 파인튜닝 인코더. 외부 전송 없음

## 설계

`service.judge()`는 `call_model(messages)` 하나만 부른다. 셋 다 같은 `ModelCall`을
돌려주므로 판정 로직·로그·강행 전송·지표가 그대로다.

**임계값은 여기서 정하지 않는다.** `judge()`는 `settings.AI_VERDICT_THRESHOLD`만
보고, 그래야 `judgment_logs.threshold`가 설정값과 같다는 불변식(BR-6.5)이 유지된다.
인코더로 바꾸면 그 설정값도 같이 바꿔야 하고, 안 바꾸면 `warmup()`이 경고한다.

`openai`와 `ollama`는 **같은 코드 경로**를 쓴다. Ollama가 OpenAI 호환
엔드포인트를 내주므로 `base_url`과 모델명만 다르다 — `client.call_model()`의
타임아웃·재시도·예산 계산(BR-6.7)을 두 벌로 만들지 않기 위해서다.

**torch는 지연 import한다.** `encoder`가 아닐 때 컨테이너에 torch가 없어도
앱이 떠야 하기 때문이다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

from app.core.config import settings
from app.judgment.client import KIND_CONTRACT, ModelCall
from app.judgment.prompt import ChatMessage

logger = logging.getLogger(__name__)

OPENAI: Final = "openai"
OLLAMA: Final = "ollama"
ENCODER: Final = "encoder"
BACKENDS: Final = (OPENAI, OLLAMA, ENCODER)

#: 설정 문제로 인한 실패. `try` CLI가 장애와 구분해 보여준다.
KIND_CONFIG: Final = KIND_CONTRACT


def active() -> str:
    """현재 백엔드. 오타는 여기서 잡는다 — 판정 중에 터지면 원인을 찾기 어렵다."""
    name = (settings.JUDGMENT_BACKEND or OPENAI).strip().lower()
    if name not in BACKENDS:
        raise ValueError(
            f"JUDGMENT_BACKEND가 올바르지 않습니다: {name!r}. "
            f"{' | '.join(BACKENDS)} 중 하나여야 합니다."
        )
    return name


def _encoder_dir() -> Path:
    if settings.ENCODER_MODEL_DIR:
        return Path(settings.ENCODER_MODEL_DIR)
    # backend/app/judgment/backend.py → backend/models/context_checker
    return Path(__file__).resolve().parents[2] / "models" / "context_checker"


_calibrated_cache: float | None = None
_calibrated_read: bool = False


def calibrated_threshold() -> float | None:
    """모델 폴더의 `threshold.json`에 적힌 보정 임계값. 없으면 `None`.

    **판정에 쓰지 않는다.** `judge()`는 `settings.AI_VERDICT_THRESHOLD` 하나만
    본다 — `judgment_logs.threshold`가 그 설정값과 같다는 불변식(BR-6.5)을
    지켜야 나중에 판정을 재현할 수 있기 때문이다.

    이 값은 `warmup()`이 설정값과 비교해 경고하는 데만 쓴다. 자동으로 덮어쓰면
    설정 파일만 보고는 어떤 기준으로 판정됐는지 알 수 없게 된다.
    """
    global _calibrated_cache, _calibrated_read
    if not _calibrated_read:
        _calibrated_read = True
        path = _encoder_dir() / "threshold.json"
        if path.exists():
            try:
                _calibrated_cache = float(
                    json.loads(path.read_text(encoding="utf-8"))["threshold"]
                )
            except Exception:  # noqa: BLE001 - 읽기 실패가 기동을 막지 않는다
                logger.exception("threshold.json을 읽지 못했습니다: %s", path)
    return _calibrated_cache


async def call_model(messages: list[ChatMessage]) -> ModelCall:
    """`client.call_model()`과 시그니처·반환 타입이 같다.

    **어떤 예외도 밖으로 내지 않는다** (BR-6.7). import 실패까지 포함한다 —
    `JUDGMENT_BACKEND=encoder`인데 컨테이너에 torch가 없으면 지연 import가
    `ImportError`를 내는데, 그것이 `judge()` 밖으로 나가면 판정 실패가 아니라
    500 오류가 되어 전송 자체가 깨진다. `failed`로 기록되고 "검증 안 됨"
    배지가 붙는 편이 맞다.
    """
    name = active()
    if name == ENCODER:
        # 지연 import — openai/ollama 백엔드에서는 torch가 없어도 된다.
        try:
            from app.judgment import local_encoder
        except Exception as exc:  # noqa: BLE001
            logger.exception("인코더 백엔드를 불러오지 못했습니다")
            return ModelCall(
                ok=False, latency_ms=0,
                error=f"{type(exc).__name__}: {exc}",
                error_kind=KIND_CONFIG, attempts=0,
            )
        return await local_encoder.call_model(messages)

    from app.judgment.client import call_model as api_call_model

    return await api_call_model(messages)


async def warmup() -> None:
    """첫 사용자가 로딩을 기다리지 않게 미리 올린다. `main.py`의 lifespan에서 부른다.

    인코더는 299MB를 읽어야 해서 첫 호출이 수 초 걸리고, 그대로 두면
    `AI_TIMEOUT_SECONDS=4.0`을 넘겨 첫 메시지가 `failed`가 된다.

    임계값이 학습 때 보정한 값과 어긋나면 여기서 경고한다 — 인코더로 바꾸면서
    `AI_VERDICT_THRESHOLD`를 안 고치는 것이 가장 흔한 실수이고, 그러면 판정이
    조용히 엉뚱해진다.
    """
    name = active()
    configured = float(settings.AI_VERDICT_THRESHOLD)
    logger.info("판정 백엔드: %s (모델 %s, 임계값 %s)", name, settings.active_model, configured)
    if name != ENCODER:
        return

    cal = calibrated_threshold()
    if cal is None:
        logger.warning(
            "threshold.json이 없습니다. AI_VERDICT_THRESHOLD(%s)가 인코더 점수 "
            "분포에 맞는 값인지 확인하십시오.", configured,
        )
    elif abs(cal - configured) > 0.02:
        logger.warning(
            "임계값이 어긋납니다 — 설정 %s, 학습 때 보정한 값 %s. "
            "AI_VERDICT_THRESHOLD를 %s로 바꾸는 것을 검토하십시오.",
            configured, cal, cal,
        )

    try:
        import asyncio

        from app.judgment import local_encoder

        await asyncio.to_thread(local_encoder._load)  # noqa: SLF001
        logger.info("인코더 워밍업 완료")
    except Exception:  # noqa: BLE001 - 워밍업 실패가 기동을 막지 않는다
        logger.exception("인코더 워밍업에 실패했습니다. 첫 판정이 느려집니다.")


__all__ = ["BACKENDS", "ENCODER", "OLLAMA", "OPENAI", "active",
           "calibrated_threshold", "call_model", "warmup"]
