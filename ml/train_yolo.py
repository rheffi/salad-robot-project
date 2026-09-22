#!/usr/bin/env python3
"""Train YOLOv8n on the prepared salad dataset and publish models/best.pt."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ML_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = ML_ROOT / "datasets" / "salad_v1" / "dataset.yaml"
DEFAULT_MODEL = Path("/home/choi-chun-hwan/dev_ws/yolo/yolov8n.pt")
DEFAULT_PROJECT = ML_ROOT / "runs"
DEFAULT_BEST = ML_ROOT / "models" / "best.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="샐러드 객체 YOLOv8n CPU 학습")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--patience", type=int, default=25)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--name", default="salad_yolov8n")
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--best-output", type=Path, default=DEFAULT_BEST)
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.data.expanduser().is_file():
        raise FileNotFoundError(
            f"dataset.yaml이 없습니다: {args.data}\n"
            "먼저 python ml/prepare_dataset.py 를 실행하세요."
        )
    if not args.model.expanduser().is_file():
        raise FileNotFoundError(f"초기 가중치가 없습니다: {args.model}")
    if args.epochs < 1 or args.imgsz < 32 or args.batch < 1 or args.workers < 0:
        raise ValueError("epochs/imgsz/batch/workers 값을 확인하세요.")


def main() -> int:
    args = parse_args()
    try:
        validate_args(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"오류: {exc}")
        return 1

    from ultralytics import YOLO

    data = args.data.expanduser().resolve()
    model_path = args.model.expanduser().resolve()
    project = args.project.expanduser().resolve()
    best_output = args.best_output.expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    best_output.parent.mkdir(parents=True, exist_ok=True)

    print("학습 데이터:", data)
    print("초기 모델:", model_path)
    print(
        f"설정: epochs={args.epochs}, imgsz={args.imgsz}, batch={args.batch}, "
        f"workers={args.workers}, device={args.device}"
    )

    model = YOLO(str(model_path))
    model.train(
        data=str(data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        patience=args.patience,
        device=args.device,
        project=str(project),
        name=args.name,
        exist_ok=False,
        pretrained=True,
        seed=42,
        deterministic=True,
        cache=False,
        plots=True,
        verbose=True,
    )

    save_dir = Path(model.trainer.save_dir).resolve()
    trained_best = save_dir / "weights" / "best.pt"
    if not trained_best.is_file():
        print(f"오류: 학습은 끝났지만 best.pt를 찾지 못했습니다: {trained_best}")
        return 1

    shutil.copy2(trained_best, best_output)
    print("학습 완료!")
    print("전체 결과:", save_dir)
    print("사용할 모델:", best_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
