# 파인튜닝 실행 가이드 (Windows + RTX 3050)

모델: `skt/A.X-Encoder-base` (149M, ModernBERT) · 데이터: `dataset/training_dataset_v3_1000.csv`

단계별로 결과를 보며 돌리려면 `train_ax_encoder.ipynb`를 쓴다 (§6).

## 0. 전제조건 — MSVC 재배포 런타임

**Windows용 torch는 전부 MSVC로 빌드되어 있다.** 이 런타임이 없으면 CUDA 여부와 무관하게
`import torch` 자체가 실패한다:

```
OSError: [WinError 126] 지정된 모듈을 찾을 수 없습니다.
Error loading "...\torch\lib\c10.dll" or one of its dependencies.
```

설치 여부는 `C:\Windows\System32\vcruntime140.dll` 존재로 확인한다. 없으면:

```bat
:: (A) 관리자 권한이 있으면 — 정석
winget install Microsoft.VCRedist.2015+.x64
::   또는 https://aka.ms/vs/17/release/vc_redist.x64.exe 직접 설치

:: (B) 관리자 권한이 없으면 — venv 안에서 해결
pip install msvc-runtime
::   DLL이 venv\Scripts\ 에 깔리지만 Python 3.8+ 확장 모듈은 PATH를 검색하지 않는다.
::   torch가 DLL 디렉터리로 등록하는 곳으로 복사해야 인식된다:
copy venv\Scripts\vcruntime140*.dll venv\Lib\site-packages\torch\lib\
copy venv\Scripts\msvcp140*.dll     venv\Lib\site-packages\torch\lib\
copy venv\Scripts\concrt140.dll     venv\Lib\site-packages\torch\lib\
```

## 1. 설치 (최초 1회)

```bat
:: 프로젝트 루트에서 (가상환경 권장)
python -m venv venv
venv\Scripts\activate

:: PyTorch CUDA 빌드 (RTX 3050 = Ampere, cu126 기준)
pip install torch --index-url https://download.pytorch.org/whl/cu126

:: 나머지
pip install "transformers>=4.48" scikit-learn pandas

:: 노트북으로 돌릴 경우에만
pip install ipykernel

:: GPU 인식 확인 — True 나와야 함
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

`transformers>=4.48` 필수 — A.X-Encoder의 ModernBERT 아키텍처 지원 버전.

**transformers 5.x 주의.** A.X-Encoder의 config는 `dtype: bfloat16`을 선언하고, 5.x는 4.x와 달리
체크포인트 dtype을 그대로 따른다. bf16 파라미터는 bf16 그래디언트를 만들고
`GradScaler.unscale_`에는 bf16 CUDA 커널이 없어 학습이 죽는다
(`NotImplementedError: "_amp_foreach_non_finite_check_and_unscale_cuda" not implemented for 'BFloat16'`).
`train_ax_encoder.py`의 `fresh_model()`이 fp32로 못박아 두었으므로 4.x·5.x 양쪽에서 돈다 —
**모델 생성 코드를 복제할 때 이 `.float()`를 빠뜨리지 말 것.**

## 2. 실행

```bat
:: (1) 축소 동작 확인 — 1~2분. 처음엔 모델 다운로드(~700MB) 시간 추가
python training\train_ax_encoder.py --csv dataset\training_dataset_v3_1000.csv --smoke --out smoke_out

:: (2) 본 학습 — 5-fold CV + 최종 모델. RTX 3050(6GB) 실측 약 13분
python training\train_ax_encoder.py --csv dataset\training_dataset_v3_1000.csv --out train_out

:: (3) 추론 확인
python training\predict_example.py --model-dir train_out\final_model
```

기본값(`--batch 16 --max-len 512`)에서 VRAM 실측 5.6/6.0GB — 6GB 카드에서 여유가 거의 없다.
OOM(메모리 부족)이 나면: `--batch 8` → 그래도 나면 `--batch 8 --max-len 384`.

**`_simple.csv`로 학습할 경우.** `training_dataset_v3_1000_simple.csv`는 전체 CSV와 공유 컬럼이
행 단위로 동일하고 `source`/`source_type`/`difficulty`만 빠진 파일이다. 학습 결과는 같지만
(모델 입력은 history+response뿐, 분할 키 `pair_id`도 동일) **`report.json`의 `slices`가 빈 `{}`가
되어 §3의 핵심 진단인 `difficulty=hard`를 볼 수 없다.** 노트북 셀 [9]가 전체 CSV를 `no`로 join해
자동 복원하므로, simple CSV를 쓸 때는 노트북 경로를 권한다.

## 3. 결과 읽는 법 (`train_out/report.json`)

| 항목 | 의미 | 판단 기준 |
|---|---|---|
| `oof_auc` | fold 밖 예측의 AUC | **0.725(어휘 baseline)를 크게 넘어야 성공.** 0.9+ 기대 |
| `chosen_threshold` | 목표 precision(기본 0.95)을 만족하는 threshold | `final_model/threshold.json`에 저장됨 |
| `at_chosen` | 그 threshold에서의 precision/recall | precision ≥ 0.95 확인, recall이 실질 성능 |
| `slices` | source/source_type/difficulty별 성능 | **`difficulty=hard`가 무너지는지 볼 것** — 무너지면 개체 추적 실패 → v2.5 방식으로 hard 데이터 증분 |
| `sweep` | threshold별 precision/recall 표 | 팝업 빈도(flag_rate) 대비 트레이드오프 확인 |

주의: 정확도가 0.95를 넘어도 그건 "이 데이터셋 분포 안에서"입니다. 실전 성능은
웹앱 로그로 검증해야 하고, `oof_predictions.csv`로 오분류 행을 직접 열어보는 것이
다음 데이터 증분의 근거가 됩니다.

## 4. 산출물

```
train_out/
  report.json           전체·슬라이스 지표 + threshold 스윕
  oof_predictions.csv   행별 fold 밖 예측 확률 (오분류 분석용)
  final_model/          배포용 — FastAPI에서 predict_example.py의 ContextChecker 그대로 사용
    threshold.json      운영 threshold (precision 0.95 기준)
```

`ContextChecker.check(최근 N개 메시지, 후보 메시지)` → `('적절'|'부적절', confidence)` —
판정 로그 테이블의 `verdict`/`confidence` 컬럼과 바로 대응됩니다.

## 5. 재현성 메모

- 분할은 `pair_id` 그룹 단위 (StratifiedGroupKFold, seed 42) — 쌍둥이 행 분리 금지
- 입력은 history+response만. source/difficulty 컬럼은 학습에 사용되지 않음
- 데이터 수정 시 `validate_context_dataset.py` 먼저, 그다음 재학습
