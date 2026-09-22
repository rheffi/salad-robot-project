# YOLO 학습

다운로드한 `print_phone/YOLODataset` 사본을 검증·변환한 뒤 YOLOv8n을 CPU로 학습합니다. 다운로드 폴더의 원본은 수정하지 않습니다.

## 클래스 순서

```text
0 lettuce
1 onion
2 cheese
3 berry
4 tomato
5 bowl
6 brocoli
7 carrot
8 bacon
```

받은 데이터셋의 클래스 순서는 위 순서와 다르므로 `prepare_dataset.py`가 모든 라벨 ID를 변환합니다. 같은 원본에서 생성된 `aug0~aug4`는 한쪽 split에만 배치하여 train/val 누수를 방지합니다.

## 1. 데이터 준비

프로젝트 루트에서 실행합니다.

```bash
cd ~/dev_ws/salad_robot_project
/home/choi-chun-hwan/venv/yolo-venv/bin/python ml/prepare_dataset.py
```

완료 후 생성되는 주요 파일은 다음과 같습니다.

```text
ml/datasets/salad_v1/dataset.yaml
ml/datasets/salad_v1/manifest.json
ml/datasets/salad_v1/images/train
ml/datasets/salad_v1/images/val
ml/datasets/salad_v1/labels/train
ml/datasets/salad_v1/labels/val
```

이미 출력 폴더가 있고 의도적으로 다시 만들 때만 다음 명령을 사용합니다.

```bash
/home/choi-chun-hwan/venv/yolo-venv/bin/python ml/prepare_dataset.py --force
```

## 2. 선택 사항: 1 epoch 확인

긴 학습 전에 경로와 데이터 로딩을 확인합니다. 결과는 `ml/runs/smoke_test/`에 생성됩니다.

```bash
/home/choi-chun-hwan/venv/yolo-venv/bin/python ml/train_yolo.py \
  --epochs 1 \
  --name smoke_test
```

## 3. 100 epoch 학습

충전기를 연결하고 노트북 뚜껑을 열어둔 상태에서 실행합니다. 이 실행 파일은 학습 중 시스템 절전을 차단하고 출력을 `ml/train.log`에도 기록합니다.

```bash
bash ml/run_training.sh
```

기본 학습 설정은 다음과 같습니다.

- 초기 모델: `/home/choi-chun-hwan/dev_ws/yolo/yolov8n.pt`
- `epochs=100`
- `imgsz=640`
- `batch=8`
- `workers=4`
- `device=cpu`
- `patience=25`

학습이 정상 완료되면 전체 결과는 `ml/runs/`에 남고 최종 모델은 다음 경로로 복사됩니다.

```text
ml/models/best.pt
```

진행 상황은 다른 터미널에서 확인할 수 있습니다.

```bash
tail -f ml/train.log
```

중단하려면 학습이 실행 중인 터미널에서 `Ctrl+C`를 누릅니다.
