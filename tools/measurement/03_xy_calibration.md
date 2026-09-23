# 03 카메라 픽셀 → 로봇 XY 보정 사용법

대상 파일: [`03_xy_calibration.py`](03_xy_calibration.py)

YOLO가 찾은 화면 좌표 `(u, v)`와 사람이 직접 맞춘 로봇 좌표 `(X, Y)`를 여러 점에서 수집한다. 수집한 대응점으로 평면 Homography를 계산해 `config/xy_correction.json`을 만든다.

이 스크립트는 로봇 이동 명령을 보내지 않는다. 사용자가 수동 모드에서 직접 로봇을 움직인다.

## 전제 조건

- 카메라가 최종 위치에 단단히 고정되어 있어야 한다.
- 카메라 해상도는 모든 측정에서 640×480으로 유지한다.
- 기본 플랜지/0 오프셋 TCP를 유지한다.
- `best.pt`가 `ml/models/best.pt`에 있어야 한다.
- E0509 bringup이 실행 중이어야 한다.
- 로봇을 수동 조그할 수 있어야 한다.
- 한 점을 저장하는 동안 박스를 움직이면 안 된다.

카메라 위치나 작업대 높이, 카메라 해상도가 바뀌면 이 보정을 다시 해야 한다.

## 권장 보정점 배치

최소 5점이 필요하지만 3×3 형태의 9점을 권장한다.

```text
left_top       center_top       right_top
left_center    center           right_center
left_bottom    center_bottom    right_bottom
```

점이 한 줄에 몰리면 계산할 수 없다. 실제 재료를 놓을 작업영역의 가장자리와 중앙에 넓게 배치한다. 같은 `tomato` 박스 하나를 위치만 바꿔가며 사용해도 된다.

## 보정점 한 개 수집


python3 03_xy_calibration.py collect \
  --class-name tomato \
  --point-name left_top \
  --camera 6

예를 들어 토마토 박스를 작업영역 왼쪽 위에 놓고 다음을 실행한다.

```bash
$PY tools/measurement/03_xy_calibration.py collect \
  --class-name tomato \
  --point-name left_top \
  --camera 6
```

### 화면에서 할 일

1. 로봇은 HOME처럼 카메라 화면을 가리지 않는 자세에 둔다.
2. 빨간 십자 표시가 실제 박스 중앙에 있는지 확인한다.
3. `stable 10/10`이 된 뒤 `C`를 누른다.
4. 창이 닫히고 픽셀 좌표가 고정된다.

검출을 취소하려면 `Q` 또는 `Esc`를 누른다.

### 로봇에서 할 일

픽셀 좌표를 고정한 후에도 박스는 움직이지 않는다.

1. 로봇을 수동 모드로 둔다.
2. `pick_reference`와 같은 손목 방향을 유지한다.
3. 그리퍼 중심을 박스의 실제 중심 바로 위에 맞춘다.
4. 박스를 건드리지 않는 안전한 Z를 유지한다.
5. 정확히 맞으면 터미널에 `READ`를 입력한다.
6. 출력된 실제 `posx`를 확인한 뒤 `SAVE`를 입력한다.

이 보정에서는 실제 Z보다 X/Y 중심 일치가 중요하다. 매 점에서 같은 손목 방향을 유지해야 플랜지와 그리퍼 중심의 관계가 바뀌지 않는다.

## 나머지 점 수집

로봇을 다시 화면 밖의 안전 자세로 옮기고 박스를 다음 위치에 놓은 뒤 반복한다.

```bash
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name center_top --camera 6
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name right_top --camera 6
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name left_center --camera 6
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name center --camera 6
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name right_center --camera 6
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name left_bottom --camera 6
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name center_bottom --camera 6
$PY tools/measurement/03_xy_calibration.py collect --class-name tomato --point-name right_bottom --camera 6
```

수집 결과는 다음 파일에 누적된다.

```text
records/xy_calibration.csv
```

## 수집 결과 확인

```bash
$PY tools/measurement/03_xy_calibration.py list
```

각 점의 이름, 클래스, 픽셀 좌표와 실제 로봇 X/Y가 표시된다. 다음을 확인한다.

- 점 개수가 5개 이상인가
- 같은 이름을 실수로 중복 저장하지 않았는가
- 픽셀 좌표가 작업영역 전체에 넓게 퍼져 있는가
- 로봇 X/Y가 비정상적으로 튀는 점이 없는가

잘못 저장한 점이 있으면 보정식을 만들기 전에 `records/xy_calibration.csv`를 백업하고 해당 행을 정정하거나 전체를 다시 수집한다.

## 보정식 생성

```bash
$PY tools/measurement/03_xy_calibration.py fit
```

정상적으로 계산되면 다음 파일이 생성된다.

```text
config/xy_correction.json
```

출력 예시는 다음과 같다.

```text
샘플: 9점 / RMS 오차: ... mm / 최대 오차: ... mm
```

- RMS 오차: 전체 측정점의 평균적인 오차 크기
- 최대 오차: 가장 나쁜 측정점의 오차
- 최대 오차가 20mm를 넘으면 스크립트가 경고한다.
- 최대 오차가 30mm를 넘으면 `04_hover_test.py`가 실제 시험을 거부한다.

권장 목표는 최대 오차 20mm 이하이며, 가능하면 RMS 10mm 안팎으로 맞춘다. 오차가 크면 한 점의 중심을 잘못 맞췄는지, 카메라나 박스가 움직였는지 확인하고 다시 측정한다.

## 다음 단계

`config/xy_correction.json` 생성과 오차 확인이 끝나면 [`04_hover_test.md`](04_hover_test.md)로 이동한다.
