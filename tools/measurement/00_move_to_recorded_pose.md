# 00 기록 자세 이동 도구 사용법

대상 파일: [`00_move_to_recorded_pose.py`](00_move_to_recorded_pose.py)

`robot_measurements.yaml`에 저장된 `home` 또는 `safe_wait` 관절 자세로 이동하는 선택 도구다. Hover 시험은 자체적으로 `safe_wait` 이동을 수행하므로 이 도구가 필수는 아니지만, 준비 자세를 별도로 확인하거나 먼저 이동할 때 사용할 수 있다.

이 도구는 충돌을 감지하거나 회피 경로를 계산하지 않는다. 현재 자세에서 목표까지 `movej` 관절 보간으로 이동하므로 사람이 이동 경로와 주변을 먼저 확인해야 한다.

## 사전 준비

- E0509 bringup이 실행 중이어야 한다.
- `ROS_DOMAIN_ID=15`여야 한다.
- 기본 플랜지/0 오프셋 TCP를 유지한다.
- 비상정지 버튼을 즉시 누를 수 있어야 한다.
- 현재 자세에서 목표까지 로봇팔이 작업대·카메라·사람과 충돌하지 않아야 한다.

```bash
cd ~/dev_ws/salad_robot_project
source /opt/ros/jazzy/setup.bash
source ~/doosan_ws/install/setup.bash
export ROS_DOMAIN_ID=15
PY=/home/choi-chun-hwan/venv/yolo-venv/bin/python
```

## HOME 이동

먼저 현재 자세와 목표 자세만 확인한다.

```bash
$PY tools/measurement/00_move_to_recorded_pose.py --target home
```

DRY RUN 출력에서 다음을 확인한다.

- 현재 `posj/posx`
- 목표 HOME `posj/posx`
- 현재 TCP와 기록 TCP가 같은지
- 속도와 가속도가 10/10인지
- 관절 이동 중 주변과 충돌하지 않는지

경로가 안전할 때만 실제 실행한다.

```bash
$PY tools/measurement/00_move_to_recorded_pose.py \
  --target home \
  --vel 10 \
  --acc 10 \
  --live
```

다음 문구를 정확히 입력해야 이동한다.

```text
MOVE HOME
```

## safe_wait 이동

```bash
# 현재/목표 자세만 확인
$PY tools/measurement/00_move_to_recorded_pose.py --target safe_wait

# 실제 이동
$PY tools/measurement/00_move_to_recorded_pose.py \
  --target safe_wait \
  --vel 10 \
  --acc 10 \
  --live
```

실제 이동 확인 문구:

```text
MOVE SAFE_WAIT
```

## 안전 동작

- `--live`가 없으면 로봇을 움직이지 않는다.
- 현재 TCP와 기록 당시 TCP가 다르면 이동을 거부한다.
- `vel/acc`는 1~20 범위만 허용한다.
- 목표는 `home`, `safe_wait`만 허용한다.
- 확인 문구가 정확하지 않으면 이동하지 않는다.
- 오류나 `Ctrl+C` 발생 시 추가 복귀 동작을 하지 않는다.

현재 자세가 작업대 가까이 있거나 관절 경로가 불확실하면 이 도구를 바로 실행하지 않는다. 먼저 수동 모드에서 안전한 높이와 장애물이 없는 자세로 이동한 뒤 DRY RUN 결과를 다시 확인한다.

## Hover 시험 전에 사용하는 순서

```bash
# 1. HOME 목표 확인
$PY tools/measurement/00_move_to_recorded_pose.py --target home

# 2. HOME 실제 이동
$PY tools/measurement/00_move_to_recorded_pose.py --target home --live

# 3. Hover DRY RUN
$PY tools/measurement/04_hover_test.py --class-name tomato --camera 6

# 4. Hover 실제 시험
$PY tools/measurement/04_hover_test.py \
  --class-name tomato \
  --camera 6 \
  --hover-height-mm 100 \
  --vel 10 \
  --acc 10 \
  --live
```

`04_hover_test.py`는 자체적으로 `safe_wait`로 이동한다. 이 도구를 먼저 실행했더라도 Hover 화면에서 현재→safe_wait 경로를 다시 확인한 뒤 `MOVE`를 입력한다.
