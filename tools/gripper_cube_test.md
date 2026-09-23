# 70mm 폼 박스 그리퍼 시험 사용법

대상 파일: [`gripper_cube_test.py`](gripper_cube_test.py)

현재 로봇 자세를 실제 집기점으로 기억한 후 수직으로만 움직이며 그리퍼 `position/current` 조합을 반복 시험한다.

이 파일은 `robot_measurements.yaml`의 `pick_reference`로 자동 이동하지 않는다. 실행 직전에 사용자가 맞춘 현재 자세가 집기점이 된다.

## 실행 전 준비

- E0509 bringup과 그리퍼 서비스가 실행 중이어야 한다.
- `ROS_DOMAIN_ID=15`여야 한다.
- 기본 플랜지/0 오프셋 TCP를 유지한다.
- 70×70×30mm 폼 박스를 사용한다.
- 작업대 위에서 Z 방향 80mm 상승·하강 경로가 비어 있어야 한다.
- 비상정지 버튼을 즉시 누를 수 있어야 한다.

```bash
cd ~/dev_ws/salad_robot_project
source /opt/ros/jazzy/setup.bash
source ~/doosan_ws/install/setup.bash
export ROS_DOMAIN_ID=15
PY=/home/choi-chun-hwan/venv/yolo-venv/bin/python
```

## 현재 자세 맞추기

1. 로봇을 수동 모드로 전환한다.
2. 박스를 시험 위치에 놓는다.
3. 그리퍼 중심을 박스 중심에 맞춘다.
4. 손가락을 닫으면 박스를 잡을 실제 Z까지 이동한다.
5. 자세를 정지하고 작업영역에서 손을 뺀다.

현재 자세는 박스 위 접근점이 아니라 실제로 그리퍼를 닫을 집기점이어야 한다.

## 1단계: DRY RUN

```bash
$PY tools/gripper_cube_test.py \
  --size-mm 70 \
  --height-mm 30
```

`--live`가 없으면 로봇에 연결하지 않고 동작 계획만 출력한다.

## 2단계: 실제 시험

```bash
$PY tools/gripper_cube_test.py \
  --size-mm 70 \
  --height-mm 30 \
  --lift-mm 80 \
  --vel 10 \
  --acc 10 \
  --live
```

현재 좌표와 TCP가 표시되면 실제 집기점이 맞는지 확인한다.

```text
위 자세가 정확한 집기점이면 RUN을 입력:
```

정확할 때만 `RUN`을 입력한다. 스크립트는 로봇을 자동 모드로 전환하고 그리퍼를 연 뒤 집기점에서 Z +80mm 위치로 상승한다.

## position/current 입력

```text
닫힘 position (0~749, 종료 q):
닫힘 current (1~400, 종료 q):
```

### position

- `0`: 가장 닫힌 상태
- `750`: 가장 열린 상태
- 숫자가 작을수록 더 많이 닫힌다.
- 숫자가 클수록 덜 닫힌다.

처음에는 과도하게 누르지 않도록 큰 값부터 시작한다.

```text
600 → 550 → 500
```

### current

파지 힘과 관련된 값이다. 허용 범위는 1~400이다.

```text
첫 시험 권장값: position=600, current=200
```

- 접촉하지 않으면 position을 조금 낮춘다.
- 접촉하지만 미끄러지면 position을 조금 낮추거나 current를 조금 올린다.
- 폼이 심하게 찌그러지면 position을 올리거나 current를 낮춰 파지량과 힘을 줄인다.
- 한 번에 큰 폭으로 바꾸지 않는다.

## 한 번의 시험 동작

값을 입력한 뒤 박스를 처음 가르친 위치에 놓고 손을 뺀다.

```text
박스를 원래 집기점에 놓고 손을 뺀 뒤 RUN 입력:
```

`RUN` 입력 후 다음 순서로 실행된다.

1. 안전 접근점에서 원래 집기점으로 Z -80mm 하강
2. 입력한 position/current로 그리퍼 닫기
3. Z +80mm 상승
4. 기본 2초 동안 유지
5. 사용자가 Enter를 누르면 원래 집기점으로 하강
6. 그리퍼 열기
7. Z +80mm 안전 접근점으로 다시 상승

XY 이동, 손목 회전, HOME 복귀는 하지 않는다.

## 결과 입력과 판정

```text
결과 (성공 y / 실패 n / 애매 u):
```

- `y`: 들어 올린 동안 안정적으로 유지되고 폼 손상이 적음
- `n`: 잡히지 않음, 빠짐, 심한 미끄러짐 또는 과도한 찌그러짐
- `u`: 경계 상태라 재시험 필요

메모에는 다음처럼 남긴다.

```text
안정적으로 유지됨
상승 후 오른쪽으로 미끄러짐
폼 모서리가 심하게 눌림
손가락이 박스에 닿지 않음
```

결과는 다음 파일에 누적된다.

```text
results/gripper_trials.csv
```

`position`, `current`, 자세, 속도, 성공 여부와 메모가 함께 저장된다.

## 종료

새 시험의 position 또는 current 입력 단계에서 `q`를 입력한다. 정상 종료하면 로봇은 집기점보다 `lift-mm`만큼 높은 위치에 남는다.

`Ctrl+C`나 오류 발생 시 추가 복귀 동작을 하지 않는다. 중단 후에는 로봇 위치와 그리퍼 상태를 직접 확인한다.

## 옵션 요약

| 옵션 | 기본값 | 의미 |
|---|---:|---|
| `--size-mm` | 필수 | 박스 크기 기록값 |
| `--height-mm` | 30 | 박스 높이 기록값 |
| `--open-position` | 750 | 완전 열림 명령값 |
| `--lift-mm` | 80 | 집기점 위 수직 이동 거리 |
| `--vel` | 10 | 수직 이동 속도 |
| `--acc` | 10 | 수직 이동 가속도 |
| `--close-wait` | 1초 | 닫은 후 상승 전 대기 |
| `--hold` | 2초 | 들어 올린 상태 유지 시간 |
| `--output` | `results/gripper_trials.csv` | 결과 저장 파일 |
| `--live` | 꺼짐 | 실제 로봇 동작 허용 |

`--size-mm`과 `--height-mm`은 기록용이다. 박스 크기를 보고 position이나 Z를 자동 계산하지 않는다.

안정적인 조합 하나를 찾으면 그 값을 실제 단일 집기 코드에 사용하고, 다음 단계인 XY 보정과 Hover 시험을 진행한다.
