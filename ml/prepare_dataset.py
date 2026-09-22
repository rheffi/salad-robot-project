#!/usr/bin/env python3
"""Validate and convert the received print_phone YOLO dataset.

The received dataset uses a different class order and mixes augmented images
from the same source photograph across train and validation. This script
remaps every class ID and creates a deterministic group-aware 80/20 split.
It never modifies the received source copy.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml


ML_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ML_ROOT / "datasets" / "print_phone_source"
DEFAULT_OUTPUT = ML_ROOT / "datasets" / "salad_v1"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# Class order embedded in the received Downloads/print_phone dataset.
SOURCE_NAMES = (
    "tomato",
    "cheese",
    "onion",
    "lettuce",
    "berry",
    "carrot",
    "brocoli",
    "bowl",
    "bacon",
)

# Class order agreed by the project team. Keep "brocoli" spelling unchanged.
TARGET_NAMES = (
    "lettuce",
    "onion",
    "cheese",
    "berry",
    "tomato",
    "bowl",
    "brocoli",
    "carrot",
    "bacon",
)

SOURCE_TO_TARGET = {
    source_id: TARGET_NAMES.index(name)
    for source_id, name in enumerate(SOURCE_NAMES)
}


@dataclass(frozen=True)
class Sample:
    stem: str
    image: Path
    label: Path
    group: str
    source_split: str
    target_class_counts: Counter[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="print_phone 데이터 검증, 클래스 변환 및 그룹 단위 재분할"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument(
        "--force",
        action="store_true",
        help="출력 폴더가 있으면 삭제하고 다시 생성합니다.",
    )
    return parser.parse_args()


def group_key(stem: str) -> str:
    """Keep every augN image derived from one original in the same split."""
    match = re.match(r"^(IMG_\d+)_aug\d+(?:_|$)", stem)
    if match:
        return f"augmented:{match.group(1)}"
    return f"single:{stem}"


def parse_label(path: Path) -> tuple[list[str], Counter[int]]:
    converted: list[str] = []
    counts: Counter[int] = Counter()

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{path}:{line_number}: 열 개수가 5개가 아닙니다.")
        try:
            source_id = int(parts[0])
            values = [float(value) for value in parts[1:]]
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: 숫자 형식 오류") from exc
        if source_id not in SOURCE_TO_TARGET:
            raise ValueError(f"{path}:{line_number}: 알 수 없는 class ID {source_id}")
        if not all(0.0 <= value <= 1.0 for value in values):
            raise ValueError(f"{path}:{line_number}: 좌표가 0~1 범위를 벗어났습니다.")
        if values[2] <= 0.0 or values[3] <= 0.0:
            raise ValueError(f"{path}:{line_number}: box 폭/높이는 0보다 커야 합니다.")

        target_id = SOURCE_TO_TARGET[source_id]
        counts[target_id] += 1
        converted.append(" ".join((str(target_id), *parts[1:])))

    return converted, counts


def validate_source_yaml(source: Path) -> None:
    yaml_path = source / "dataset.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"원본 dataset.yaml이 없습니다: {yaml_path}")
    document = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    raw_names = document.get("names") if isinstance(document, dict) else None
    if isinstance(raw_names, list):
        actual_names = tuple(str(name) for name in raw_names)
    elif isinstance(raw_names, dict):
        try:
            actual_names = tuple(
                str(raw_names[key] if key in raw_names else raw_names[str(key)])
                for key in range(len(raw_names))
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"원본 YAML의 names 형식을 해석할 수 없습니다: {raw_names}") from exc
    else:
        raise ValueError("원본 YAML에 names 목록이 없습니다.")
    if actual_names != SOURCE_NAMES:
        raise ValueError(
            "원본 YAML 클래스 순서가 검사 당시와 다릅니다.\n"
            f"예상: {SOURCE_NAMES}\n실제: {actual_names}"
        )


def collect_samples(source: Path) -> list[Sample]:
    samples: list[Sample] = []
    seen_stems: set[str] = set()
    validate_source_yaml(source)

    for split in ("train", "val"):
        image_dir = source / "images" / split
        label_dir = source / "labels" / split
        if not image_dir.is_dir() or not label_dir.is_dir():
            raise FileNotFoundError(f"필수 폴더가 없습니다: {image_dir} 또는 {label_dir}")

        images = {
            path.stem: path
            for path in image_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        }
        labels = {path.stem: path for path in label_dir.glob("*.txt")}
        missing_labels = sorted(set(images) - set(labels))
        missing_images = sorted(set(labels) - set(images))
        if missing_labels or missing_images:
            raise ValueError(
                f"{split} 이미지/라벨 불일치: "
                f"라벨 없음={missing_labels}, 이미지 없음={missing_images}"
            )

        duplicates = seen_stems.intersection(images)
        if duplicates:
            raise ValueError(f"train/val에 중복 파일명이 있습니다: {sorted(duplicates)}")
        seen_stems.update(images)

        for stem in sorted(images):
            _, class_counts = parse_label(labels[stem])
            samples.append(
                Sample(
                    stem=stem,
                    image=images[stem],
                    label=labels[stem],
                    group=group_key(stem),
                    source_split=split,
                    target_class_counts=class_counts,
                )
            )

    if not samples:
        raise ValueError("학습 이미지가 없습니다.")
    return samples


def choose_validation_groups(
    samples: list[Sample], val_ratio: float
) -> tuple[set[str], dict[str, list[Sample]]]:
    if not 0.05 <= val_ratio <= 0.5:
        raise ValueError("val-ratio는 0.05~0.5 범위여야 합니다.")

    grouped: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.group].append(sample)

    keys = sorted(grouped)
    val_group_count = max(1, round(len(keys) * val_ratio))
    total_boxes: Counter[int] = Counter()
    for sample in samples:
        total_boxes.update(sample.target_class_counts)
    target_image_count = len(samples) * val_ratio

    best_score: tuple[float, ...] | None = None
    best_groups: tuple[str, ...] | None = None

    for candidate in itertools.combinations(keys, val_group_count):
        val_samples = [sample for key in candidate for sample in grouped[key]]
        val_boxes: Counter[int] = Counter()
        for sample in val_samples:
            val_boxes.update(sample.target_class_counts)

        missing_classes = sum(
            1 for class_id, total in total_boxes.items() if total and not val_boxes[class_id]
        )
        image_difference = abs(len(val_samples) - target_image_count)
        class_ratio_error = sum(
            abs((val_boxes[class_id] / total) - val_ratio)
            for class_id, total in total_boxes.items()
            if total
        )
        score = (float(missing_classes), image_difference, class_ratio_error)
        if best_score is None or score < best_score:
            best_score = score
            best_groups = candidate

    if best_groups is None:
        raise RuntimeError("validation 그룹을 선택하지 못했습니다.")
    if best_score and best_score[0] > 0:
        raise ValueError("모든 클래스를 포함하는 validation split을 만들 수 없습니다.")
    return set(best_groups), dict(grouped)


def write_dataset_yaml(destination: Path, final_dataset_root: Path) -> None:
    lines = [
        f"path: {final_dataset_root.resolve()}",
        "train: images/train",
        "val: images/val",
        "test:",
        "",
        "names:",
    ]
    lines.extend(f"  {class_id}: {name}" for class_id, name in enumerate(TARGET_NAMES))
    (destination / "dataset.yaml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def build_dataset(
    source: Path, output: Path, val_ratio: float, force: bool
) -> dict[str, object]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if source == output:
        raise ValueError("source와 output은 서로 달라야 합니다.")

    samples = collect_samples(source)
    val_groups, grouped = choose_validation_groups(samples, val_ratio)

    if output.exists() and not force:
        raise FileExistsError(
            f"출력 폴더가 이미 있습니다: {output}\n"
            "다시 만들려면 내용을 확인한 뒤 --force를 사용하세요."
        )

    building = output.with_name(f"{output.name}.building")
    if building.exists():
        raise FileExistsError(
            f"이전 작업의 임시 폴더가 남아 있습니다: {building}\n"
            "내용을 확인하고 직접 정리한 뒤 다시 실행하세요."
        )

    split_counts = Counter()
    class_counts: dict[str, Counter[int]] = {
        "train": Counter(),
        "val": Counter(),
    }

    try:
        for split in ("train", "val"):
            (building / "images" / split).mkdir(parents=True, exist_ok=True)
            (building / "labels" / split).mkdir(parents=True, exist_ok=True)

        for sample in samples:
            split = "val" if sample.group in val_groups else "train"
            shutil.copy2(sample.image, building / "images" / split / sample.image.name)
            converted, counts = parse_label(sample.label)
            label_target = building / "labels" / split / sample.label.name
            label_target.write_text("\n".join(converted) + "\n", encoding="utf-8")
            split_counts[split] += 1
            class_counts[split].update(counts)

        write_dataset_yaml(building, output)
        manifest = {
            "source": str(source),
            "output": str(output),
            "val_ratio_requested": val_ratio,
            "source_names": dict(enumerate(SOURCE_NAMES)),
            "target_names": dict(enumerate(TARGET_NAMES)),
            "source_to_target": SOURCE_TO_TARGET,
            "image_counts": dict(split_counts),
            "box_counts": {
                split: {str(i): class_counts[split][i] for i in range(len(TARGET_NAMES))}
                for split in ("train", "val")
            },
            "validation_groups": sorted(val_groups),
            "all_groups": sorted(grouped),
        }
        (building / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if output.exists():
            shutil.rmtree(output)
        building.rename(output)
    except Exception:
        if building.exists():
            shutil.rmtree(building)
        raise

    return manifest


def main() -> int:
    args = parse_args()
    try:
        manifest = build_dataset(args.source, args.output, args.val_ratio, args.force)
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as exc:
        print(f"오류: {exc}")
        return 1

    print("데이터 준비 완료")
    print("출력:", manifest["output"])
    print("이미지:", manifest["image_counts"])
    print("validation 그룹:", manifest["validation_groups"])
    print("다음 단계: python ml/train_yolo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
