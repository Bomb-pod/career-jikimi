"""파인튜닝된 A.X-Encoder로 판정한다 — `client.call_model()`의 로컬 대체.

**`call_model()`과 시그니처·반환 타입이 같다.** 그래서 `service.judge()`의 9단계
(로그 행 생성 → 호출 → 클램프 → 임계값 → 갱신)를 한 줄도 고치지 않는다.
`judgment_logs`·강행 전송·`report`·`evaluate`가 전부 그대로 산다.

교체 방법 — `service.py`의 import 한 줄:

    # from app.judgment.client import call_model
    from app.judgment.local_encoder import call_model

되돌리려면 주석을 반대로 옮긴다. 그게 전부다.

**임계값은 여기서 판단하지 않는다.** `threshold.json`의 값을 `.env`의
`AI_VERDICT_THRESHOLD`에 넣는다 — 그래야 `judge()`가 그 값으로 판정하고
`judgment_logs.threshold`에 실제 쓴 값이 남아 재현이 된다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Final

from app.judgment.client import (
    KIND_CONTRACT,
    KIND_UNEXPECTED,
    ModelCall,
)
from app.judgment.prompt import CANDIDATE_HEADING, CONTEXT_HEADING, ChatMessage

logger = logging.getLogger(__name__)

from app.core.config import settings

#: 모델 디렉터리. `.env`의 ENCODER_MODEL_DIR이 이기고, 없으면 아래 기본 경로.
#: `deploy/Dockerfile`이 `COPY backend/models ./models` 로 굽는다.
_DEFAULT_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "models" / "context_checker"


def model_dir() -> Path:
    return Path(settings.ENCODER_MODEL_DIR) if settings.ENCODER_MODEL_DIR else _DEFAULT_DIR


#: 학습 때와 **같은 값이어야 한다.** 다르면 잘리는 위치가 달라져 점수가 바뀐다.
#: threshold.json에 학습 때 쓴 값이 들어 있으므로 그것을 우선 읽는다.
def max_len() -> int:
    path = model_dir() / "threshold.json"
    if path.exists():
        try:
            import json as _json
            v = _json.loads(path.read_text(encoding="utf-8")).get("max_len")
            if v:
                return int(v)
        except Exception:  # noqa: BLE001 - 읽기 실패는 기본값으로 넘어간다
            pass
    return 384

_model: Any = None
_tokenizer: Any = None


def _load() -> tuple[Any, Any]:
    """첫 호출에 모델을 올린다. `get_client()`와 같은 지연 생성 이유다 —
    판정을 하지 않는 진입점(`report` CLI 등)이 모델 없이도 돌아야 한다."""
    global _model, _tokenizer
    if _model is None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        d = model_dir()
        if not d.exists():
            raise FileNotFoundError(f"모델 디렉터리가 없습니다: {d}")

        _tokenizer = AutoTokenizer.from_pretrained(str(d))
        _model = AutoModelForSequenceClassification.from_pretrained(str(d))
        _model.to("cuda" if torch.cuda.is_available() else "cpu").eval()
        logger.info("판정 인코더를 올렸습니다: %s (%s, max_len=%d)",
                    d, next(_model.parameters()).device, max_len())
    return _model, _tokenizer


def split_prompt(user_content: str) -> tuple[str, str]:
    """조립된 user 메시지에서 문맥과 후보를 도로 꺼낸다.

    `prompt.py`의 절 제목 상수를 그대로 쓴다 — 문안이 바뀌어도 같이 따라간다.
    후보 줄의 `"B: "` 화자 라벨은 **떼어낸다.** 학습 데이터의 response 컬럼에는
    라벨이 없었으므로, 붙인 채로 넣으면 학습 때와 입력 분포가 어긋난다.
    """
    if CANDIDATE_HEADING not in user_content:
        raise ValueError(f"후보 절 제목을 찾지 못했습니다: {CANDIDATE_HEADING!r}")

    context_part, candidate_part = user_content.split(CANDIDATE_HEADING, 1)
    context = context_part.replace(CONTEXT_HEADING, "", 1).strip()

    candidate = candidate_part.strip()
    label, sep, rest = candidate.partition(": ")
    # 라벨은 A~Z 조합(엑셀 열 이름 규칙)뿐이다. 그 모양일 때만 떼어낸다 —
    # 본문이 "메모: 내일" 처럼 시작하는 경우를 잘라먹지 않기 위해서다.
    if sep and label and label.isascii() and label.isalpha() and label.isupper():
        candidate = rest

    return context, candidate


def _infer(context: str, candidate: str) -> tuple[float, int]:
    """동기 추론. `to_thread`로 감싸 이벤트 루프를 막지 않는다."""
    import torch

    model, tokenizer = _load()
    enc = tokenizer(
        context, candidate,
        truncation="only_first", max_length=max_len(), return_tensors="pt",
    ).to(model.device)
    with torch.no_grad():
        logits = model(**enc).logits
    score = torch.softmax(logits.float(), -1)[0, 1].item()
    return score, int(enc["input_ids"].shape[1])


async def call_model(messages: list[ChatMessage]) -> ModelCall:
    """`client.call_model()`의 로컬 대체. **예외를 밖으로 내보내지 않는다** (BR-6.7).

    재시도가 없다. 로컬 추론에는 타임아웃·429·5xx가 없고, 실패는 모델 파일이
    없거나 입력이 깨진 경우뿐이라 다시 해도 같은 결과다.
    """
    started = time.monotonic()
    user_content = next((m["content"] for m in messages if m.get("role") == "user"), None)

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    if user_content is None:
        return ModelCall(ok=False, latency_ms=elapsed_ms(),
                         error="user 메시지가 없습니다", error_kind=KIND_CONTRACT, attempts=0)

    try:
        context, candidate = split_prompt(user_content)
    except ValueError as exc:
        return ModelCall(ok=False, latency_ms=elapsed_ms(),
                         error=str(exc), error_kind=KIND_CONTRACT, attempts=0)

    try:
        score, n_tokens = await asyncio.to_thread(_infer, context, candidate)
    except Exception as exc:  # noqa: BLE001 - 판정 실패는 예외가 아니라 반환값이다
        logger.exception("로컬 인코더 추론에 실패했습니다")
        return ModelCall(ok=False, latency_ms=elapsed_ms(),
                         error=f"{type(exc).__name__}: {exc}",
                         error_kind=KIND_UNEXPECTED, attempts=1)

    # completion_tokens는 0이다 — 생성하지 않는다. prompt_tokens는 실제 입력
    # 길이를 남긴다. 비용은 0이지만 입력 크기 추이는 여전히 관찰값이다.
    return ModelCall(ok=True, latency_ms=elapsed_ms(), score=score,
                     prompt_tokens=n_tokens, completion_tokens=0, attempts=1)


__all__ = ["call_model", "max_len", "model_dir", "split_prompt"]
