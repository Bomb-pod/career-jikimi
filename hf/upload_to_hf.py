# -*- coding: utf-8 -*-
"""모델과 데이터셋을 Hugging Face Hub에 올린다.

    pip install huggingface_hub
    huggingface-cli login          # 또는 --token / HF_TOKEN 환경변수

    python hf/upload_to_hf.py --dry-run      # 무엇이 올라가는지만 확인
    python hf/upload_to_hf.py                # 실제 업로드

기본 저장소 이름은 `.gitignore`에 적혀 있던 것을 따랐다.
바꾸려면 --model-repo / --dataset-repo 를 준다.

## 업로드 전에 확인하는 것

1. 모델 폴더에 필수 파일이 다 있는가 (config / safetensors / tokenizer)
2. `threshold.json`의 값이 실제 운영 임계값과 맞는가
3. 데이터셋 CSV가 존재하고 행 수가 예상과 맞는가
4. **평가셋이 학습셋과 겹치지 않는가** — 겹치면 카드의 주장이 거짓이 된다
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MODEL_FILES = ["config.json", "model.safetensors", "tokenizer.json",
               "tokenizer_config.json", "special_tokens_map.json"]

DATASET_FILES = [
    "dataset/training_dataset_v3_1000.csv",
    "dataset/test_dataset_100.csv",
    "dataset/test_dataset_100_hard.csv",
]


def check_model(model_dir: Path) -> bool:
    print(f"[모델] {model_dir}")
    if not model_dir.exists():
        print("  없음. --model-dir 를 확인할 것."); return False
    ok = True
    for name in MODEL_FILES:
        p = model_dir / name
        if p.exists():
            print(f"  OK   {name:28s} {p.stat().st_size/1e6:8.1f}MB")
        else:
            print(f"  없음 {name}")
            if name in ("config.json", "model.safetensors"):
                ok = False

    tj = model_dir / "threshold.json"
    if tj.exists():
        d = json.loads(tj.read_text(encoding="utf-8"))
        print(f"  threshold.json: threshold={d.get('threshold')} "
              f"max_len={d.get('max_len')} base={d.get('base_model')}")
        print("  ** 이 threshold가 운영값(AI_VERDICT_THRESHOLD)과 같은지 확인할 것 **")
    else:
        print("  threshold.json 없음 — 카드에 임계값을 적었다면 함께 올리는 편이 낫다.")
    return ok


def check_dataset(root: Path) -> bool:
    print("\n[데이터셋]")
    import csv
    rows = {}
    ok = True
    for rel in DATASET_FILES:
        p = root / rel
        if not p.exists():
            print(f"  없음 {rel}"); ok = False; continue
        with p.open(encoding="utf-8-sig", newline="") as f:
            r = list(csv.DictReader(f))
        rows[rel] = r
        labels = {}
        for x in r:
            lab = (x.get("label") or "").strip()
            labels[lab] = labels.get(lab, 0) + 1
        print(f"  OK   {Path(rel).name:34s} {len(r):5d}행  {labels}")
    if not ok:
        return False

    # **카드가 주장하는 것을 여기서 실제로 검증한다.**
    train = rows.get(DATASET_FILES[0], [])
    tp = {(x["history"].strip(), x["response"].strip()) for x in train}
    tr_resp = {x["response"].strip() for x in train}
    print("\n  누출 검사 (평가셋 vs 학습셋)")
    for rel in DATASET_FILES[1:]:
        ev = rows.get(rel, [])
        both = sum(1 for x in ev if (x["history"].strip(), x["response"].strip()) in tp)
        ronly = sum(1 for x in ev if x["response"].strip() in tr_resp)
        mark = "OK" if both == 0 else "**"
        print(f"    {mark} {Path(rel).name:34s} 완전일치 {both}  response일치 {ronly}")
        if both:
            print("       겹친다. 모델 카드의 data contamination 주장이 거짓이 된다.")
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=str(ROOT / "backend" / "models" / "context_checker"))
    ap.add_argument("--model-repo", default="agii0114/career-jikimi-context-guard")
    ap.add_argument("--dataset-repo", default="agii0114/career-jikimi-context-dataset")
    ap.add_argument("--token", default=None, help="없으면 HF_TOKEN 환경변수 또는 로그인 캐시")
    ap.add_argument("--private", action="store_true", help="비공개로 만든다")
    ap.add_argument("--skip-model", action="store_true")
    ap.add_argument("--skip-dataset", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="검사만 하고 올리지 않는다")
    args = ap.parse_args()

    model_dir = Path(args.model_dir)
    ok = True
    if not args.skip_model:
        ok &= check_model(model_dir)
    if not args.skip_dataset:
        ok &= check_dataset(ROOT)

    if not ok:
        print("\n검사에 실패했다. 위 항목을 고치고 다시 실행할 것.")
        return 1
    print("\n검사 통과.")

    if args.dry_run:
        print("\n--dry-run — 업로드하지 않는다.")
        print(f"  모델   -> {args.model_repo}")
        print(f"  데이터 -> {args.dataset_repo} (dataset)")
        return 0

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("\nhuggingface_hub 가 없다:  pip install huggingface_hub")
        return 1

    api = HfApi(token=args.token)
    hf_root = Path(__file__).resolve().parent

    if not args.skip_model:
        print(f"\n모델 업로드 -> {args.model_repo}")
        api.create_repo(args.model_repo, repo_type="model",
                        private=args.private, exist_ok=True)
        # 카드를 README.md 이름으로 올린다 — HF가 그 파일을 카드로 읽는다.
        api.upload_file(path_or_fileobj=str(hf_root / "MODEL_CARD.md"),
                        path_in_repo="README.md", repo_id=args.model_repo,
                        repo_type="model")
        api.upload_folder(folder_path=str(model_dir), repo_id=args.model_repo,
                          repo_type="model",
                          ignore_patterns=["*.md", "__pycache__", ".ipynb_checkpoints"])
        print(f"  https://huggingface.co/{args.model_repo}")

    if not args.skip_dataset:
        print(f"\n데이터셋 업로드 -> {args.dataset_repo}")
        api.create_repo(args.dataset_repo, repo_type="dataset",
                        private=args.private, exist_ok=True)
        api.upload_file(path_or_fileobj=str(hf_root / "DATASET_CARD.md"),
                        path_in_repo="README.md", repo_id=args.dataset_repo,
                        repo_type="dataset")
        for rel in DATASET_FILES:
            api.upload_file(path_or_fileobj=str(ROOT / rel),
                            path_in_repo=Path(rel).name,
                            repo_id=args.dataset_repo, repo_type="dataset")
        print(f"  https://huggingface.co/datasets/{args.dataset_repo}")

    print("\n완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
