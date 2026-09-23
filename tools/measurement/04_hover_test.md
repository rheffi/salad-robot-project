# 04 물체 위 Hover 시험 사용법

대상 파일: [`04_hover_test.py`](04_hover_test.py)

YOLO로 70mm 재료 박스를 찾고 `xy_correction.json`으로 로봇 X/Y를 계산한다. DRY RUN에서는 계산만 하며, `--live`를 붙인 경우에도 물체 위 Hover 위치까지만 이동한다.

이 스크립트는 다음 동작을 하지 않는다.

- 집기 Z까지 하강
- 그리퍼 닫기
- 박스 들어 올리기
- HOME 자동 복귀

## 전제 조건

- `config/robot_measurements.yaml`에 `safe_wait`, `pick_reference`가 있어야 한다.
- `config/xy_correction.json`이 생성되어 있어야 한다.
- 카메라 위치와 640×480 해상도가 XY 보정 당시와 같아야 한다.
- 기본 플랜지 TCP 상태가 유지되어야 한다.
- 시험 박스가 XY 보정점으로 둘러싸인 영역 안에 있어야 한다.

기본 Hover Z는 다음과 같이 계산된다.

```text
hover Z = pick_reference Z + 100mm
```

현재 측정값 기준으로는 약 `247.9 + 100 = 347.9mm`다.

현재 `xy_correction.json`에는 1차 Hover 결과에 따른 수동 보정 `X +0mm, Y +10mm`가 적용되어 있다. 출력되는 `robot XY`는 이 오프셋까지 더한 최종 이동 좌표다.

## 1단계: DRY RUN

먼저 로봇 이동 없이 계산 결과를 확인한다.

```bash
$PY tools/measurement/04_hover_test.py \
  --class-name tomato \
  --camera 6
```

카메라 창에서 다음을 확인한다.

1. 지정한 클래스 박스에 바운딩 박스가 표시되는지 확인한다.
2. `stable 10/10`이 될 때까지 기다린다.
3. 빨간 십자가 박스 중앙에 있으면 `C`를 누른다.
4. 취소는 `Q` 또는 `Esc`다.

정상 출력에는 다음 값이 포함된다.

```text
pixel=(u, v)
manual offset=(+0.0, +10.0) mm
robot XY=(X, Y) mm
pick Z=...
hover Z=...
orientation=[...]
DRY RUN 완료. 로봇은 움직이지 않았습니다.
```

`tomato` 대신 `cheese` 또는 `berry`도 시험한다.

```bash
$PY tools/measurement/04_hover_test.py --class-name cheese --camera 6
$PY tools/measurement/04_hover_test.py --class-name berry --camera 6
```

같은 클래스 박스가 여러 개 보이면 가장 신뢰도가 높은 하나를 선택하므로, Hover 검증 때는 선택할 박스 하나만 놓는 것이 안전하다.

## 자동 안전 검사

스크립트는 이동 전에 다음을 검사한다.

- XY 보정 최대 오차가 30mm 이하인가
- 물체 픽셀이 보정점들의 convex hull 안에 있는가
- 계산된 X/Y가 실제 측정 범위 안에 있는가
- 베이스에서 목표까지 수평거리가 150~850mm 안인가
- 현재 TCP가 `pick_reference` 기록 당시와 같은가
- `safe_wait`, `pick_reference`가 같은 TCP로 기록됐는가
- `safe_wait` Z가 목표 Hover Z보다 높은가

한 조건이라도 맞지 않으면 실제 이동을 거부한다.

## 2단계: 실제 Hover 이동 전 자세

실제 시험 전에 다음을 확인한다.

- 현재 자세에서 기록된 `safe_wait`까지의 관절 이동 경로에 장애물이 없음
- 작업영역에서 사람과 물건을 제거
- 비상정지 버튼을 즉시 누를 수 있는 상태

현재 자세가 HOME이나 `safe_wait`가 아니어도 실행할 수 있다. `MOVE` 확인 후 스크립트가 먼저 기록된 `safe_wait`로 이동하고, 그 안전 높이에서 `pick_reference` 방향으로 정렬한다. 사용자가 손목 방향을 수동으로 맞출 필요는 없다.

단, 현재 자세에서 `safe_wait`까지의 `movej` 경로는 충돌 회피를 계산하지 않는다. 화면에 표시된 현재 `posj/posx`와 목표 `safe_wait posj`를 확인하고 경로가 안전할 때만 `MOVE`를 입력한다.

준비 자세만 별도로 확인하거나 이동하고 싶을 때는 선택적으로 [`00_move_to_recorded_pose.md`](00_move_to_recorded_pose.md)를 사용한다. Hover 실행에 필수는 아니다.

## 3단계: 실제 Hover 시험

```bash
$PY tools/measurement/04_hover_test.py \
  --class-name tomato \
  --camera 6 \
  --hover-height-mm 100 \
  --vel 10 \
  --acc 10 \
  --live
```

카메라에서 목표를 고정하면 계산 결과와 이동 순서가 표시된다. 주변과 비상정지를 다시 확인하고 정확할 때만 다음을 입력한다.

```text
MOVE
```

로봇은 자동 모드로 전환한 뒤 다음 순서로 움직인다.

1. 기록된 `safe_wait.posj_deg`로 저속 관절 이동
2. `safe_wait` Z를 유지하면서 `pick_reference` 방향으로 정렬하고 목표 X/Y로 이동
3. 목표 X/Y에서 Hover Z까지 수직 이동
4. 그 위치에서 정지

자동 복귀하지 않으므로 시험 후 수동 모드로 전환하고 위치를 확인한다.

## 결과 확인

위에서 내려다봤을 때 그리퍼 중심이 박스 중심과 얼마나 어긋났는지 확인한다.

- X 방향 오차
- Y 방향 오차
- 반복 실행 시 오차 방향이 일정한지
- 화면 중앙과 가장자리에서 오차가 달라지는지

한 번의 오차만 보고 즉시 보정하지 말고, 중앙과 가장자리에서 3점 이상 시험한다. 오차가 항상 같은 방향이면 고정 오프셋 후보이고, 위치마다 달라지면 XY 보정점을 다시 측정해야 한다.

Hover 위치가 확인되면 다음 단계는 낮은 속도로 집기 Z까지 하강하는 단일 박스 집기 시험이다.

## 자주 발생하는 오류

### `검출점이 XY 보정점 영역 밖입니다`

박스를 보정점들이 둘러싼 영역 안으로 옮기거나 더 넓은 범위에서 보정점을 다시 수집한다.

### `카메라 해상도가 보정값과 다릅니다`

보정 때와 같은 640×480 RGB 장치를 사용한다. 현재 환경에서는 `--camera 6`을 붙인다.

### `safe_wait Z가 hover Z보다 높아야 합니다`

`safe_wait` 자세 또는 `--hover-height-mm` 값이 잘못된 상태다. 측정값을 확인하고 임의로 실행하지 않는다.
