# XY 보정 파일 설명

대상 파일: [`xy_correction.json`](xy_correction.json)  
원본 측정값: [`../records/xy_calibration.csv`](../records/xy_calibration.csv)

## 1. 파일의 역할

`xy_correction.json`은 YOLO가 찾은 카메라 픽셀 좌표 `(u, v)`를 E0509 베이스 좌표계의 로봇 좌표 `(X, Y)`mm로 변환하는 보정 파일이다.

```text
YOLO 바운딩 박스
→ 물체 중심 픽셀 (u, v)
→ xy_correction.json의 3×3 행렬 적용
→ 로봇 베이스 기준 (X, Y)
```

이 파일은 X/Y만 계산한다. 집기 Z와 손목 방향은 `robot_measurements.yaml`의 `pick_reference`, 보울에 놓을 Z와 방향은 `place_reference`에서 가져온다.

```text
재료 X/Y             → xy_correction.json
집기 Z와 방향         → pick_reference
보울 놓기 Z와 방향    → place_reference
그리퍼 닫힘           → position=430, current=200
```

## 2. 현재 보정 결과 요약

```text
생성 시각: 2026-09-22 18:28:53 KST
카메라 해상도: 640×480
보정점: 9개
대상 클래스: tomato, cheese, berry
기준 박스: 70×70×30mm
로봇 X 범위: 293.4~709.1mm
로봇 Y 범위: -238.9~195.2mm
RMS 오차: 8.70mm
최대 오차: 18.95mm
실물 Y 보정: +10.0mm
```

형식, 측정점 분포와 행렬은 정상이다. 현재 코드의 권장 최대 오차 20mm와 Hover 시험 제한 30mm를 통과한다.

RMS와 최대 오차는 9점 Homography의 계산상 오차다. 1차 실물 Hover에서 X는 대체로 맞고 Y가 일정하게 약 10mm 어긋나 `manual_offset_mm.y=+10.0`을 추가했다. 현재 결과를 공유할 때는 **1차 Hover 보정 적용, +10mm 재검증 필요**라고 표시한다.

## 3. JSON 필드 설명

### `created_at`

```json
"created_at": "2026-09-22T18:28:53+09:00"
```

보정식을 생성한 시각이다.

### `method`

```json
"method": "pixel_to_robot_xy_homography"
```

평면 Homography 방식으로 픽셀을 로봇 X/Y로 변환한다는 뜻이다.

### `camera`

```json
"camera": {
  "width": 640,
  "height": 480
}
```

보정에 사용한 영상 해상도다. 이 파일은 640×480 영상에서만 사용한다. 다른 해상도에서는 픽셀 위치가 달라지므로 그대로 사용할 수 없다.

### `pick_classes`

```json
"pick_classes": [
  "tomato",
  "cheese",
  "berry"
]
```

이 프로젝트에서 실제로 집을 대상이다. Homography 행렬은 클래스와 관계없이 좌표를 변환하지만, 코드가 예상하지 않은 클래스를 집지 않도록 적용 대상을 기록한다.

### `box_size_mm`

```json
"box_size_mm": 70
```

보정에 사용한 재료 박스의 가로·세로 기준 크기다. 실제 박스 높이는 30mm다.

### `sample_count`

```json
"sample_count": 9
```

작업영역의 좌·중·우와 상·중·하 총 9개 위치에서 픽셀과 로봇 X/Y 대응점을 측정했다는 뜻이다.

### `matrix_3x3`

```json
"matrix_3x3": [
  [0.3160437421, 3.3270376543, -170.1205179935],
  [2.7259249939, -0.1402818503, -862.3732153088],
  [0.0003333522, 0.0010525941, 1.0]
]
```

픽셀 `(u, v)`를 로봇 `(X, Y)`로 변환하는 핵심 행렬이다.

```text
d = 0.0003333522×u + 0.0010525941×v + 1

X = (0.3160437421×u + 3.3270376543×v - 170.1205179935) / d
Y = (2.7259249939×u - 0.1402818503×v - 862.3732153088) / d
```

예를 들어 물체 중심이 `(u, v)=(313.0, 224.5)`라면 다음과 같이 계산된다.

```text
로봇 X ≈ 504mm
로봇 Y ≈ -30mm
```

현재 카메라 배치에서는 대체로 영상 아래쪽으로 갈수록 로봇 X가 증가하고, 영상 오른쪽으로 갈수록 로봇 Y가 증가한다.

### `manual_offset_mm`

```json
"manual_offset_mm": {
  "x": 0.0,
  "y": 10.0
}
```

Homography 계산 후 추가하는 실물 Hover 보정값이다. 여러 위치에서 X는 맞고 Y가 일정하게 약 10mm 어긋난 결과를 반영했다.

```text
최종 X = Homography X + 0mm
최종 Y = Homography Y + 10mm
```

예를 들어 행렬 계산 결과가 `(504, -30)mm`이면 실제 이동 목표는 `(504, -20)mm`가 된다. 이 값은 원본 9점 측정과 행렬을 유지하면서 현장 편차만 별도로 기록한다.

`03_xy_calibration.py fit`으로 Homography를 새로 생성하면 수동 오프셋은 기본 `0, 0`으로 초기화된다. 카메라나 작업대를 바꿔 재보정한 경우에는 기존 `+10mm`를 무조건 복사하지 말고 Hover 오차를 다시 측정한다.

### `pixel_convex_hull`

```json
"pixel_convex_hull": [ ... ]
```

외곽 보정점을 연결한 카메라 영상의 유효 다각형이다. 물체 중심 픽셀이 이 다각형 안에 있을 때만 보정값을 사용한다.

현재 보정점의 전체 픽셀 범위는 대략 다음과 같다.

```text
u: 약 211~431
v: 약 132~331
```

이는 단순 사각형 범위가 아니다. 실제 코드는 JSON의 꼭짓점으로 만들어진 다각형 내부인지 검사한다. 영역 밖의 좌표를 억지로 외삽하면 오차가 커질 수 있으므로 이동을 거부한다.

### `robot_xy_bounds_mm`

```json
"robot_xy_bounds_mm": {
  "x_min": 293.402435,
  "x_max": 709.14093,
  "y_min": -238.883881,
  "y_max": 195.150192
}
```

실제로 보정점을 측정한 로봇 작업영역이다.

```text
X: 약 293~709mm
Y: 약 -239~195mm
```

이 값은 E0509 전체 작업 가능 범위가 아니라 현재 작업대에서 직접 측정하고 허용한 영역이다. 계산된 목표가 이 범위를 벗어나면 이동하지 않는다.

### `fit_error_mm`

```json
"fit_error_mm": {
  "rms": 8.6957688457,
  "max": 18.9461532587
}
```

- RMS 오차 약 8.70mm: 9개 측정점의 전반적인 오차 크기
- 최대 오차 약 18.95mm: 가장 오차가 큰 측정점의 오차

가장 큰 오차는 `center` 측정점에서 발생했다. 실제 Hover 결과에서 중앙 오차가 크게 나타나면 `center` 보정점을 우선 다시 측정한다.

이 오차는 측정점에 대한 계산 오차일 뿐이며 새로운 물체 위치의 실제 오차를 보장하지 않는다.

### `source_csv`

```json
"source_csv": "/home/choi-chun-hwan/dev_ws/salad_robot_project/records/xy_calibration.csv"
```

보정식을 만든 원본 CSV의 위치를 표시하는 추적용 정보다. 실행 시 CSV를 다시 읽지 않으므로 다른 팀원 노트북에 이 절대경로가 없어도 JSON 변환에는 문제가 없다.

## 4. 코드에서 사용하는 예

```python
import json
from pathlib import Path

import numpy as np


correction = json.loads(
    Path("config/xy_correction.json").read_text(encoding="utf-8")
)
matrix = np.asarray(correction["matrix_3x3"], dtype=float)
offset = correction.get("manual_offset_mm", {"x": 0.0, "y": 0.0})


def pixel_to_robot_xy(u: float, v: float) -> tuple[float, float]:
    source = np.array([u, v, 1.0], dtype=float)
    target = matrix @ source
    return (
        float(target[0] / target[2]) + float(offset["x"]),
        float(target[1] / target[2]) + float(offset["y"]),
    )


robot_x, robot_y = pixel_to_robot_xy(313.0, 224.5)
print(robot_x, robot_y)
```

실제 로봇 이동 전에는 행렬 계산만 하면 안 된다. 다음 조건도 함께 검사해야 한다.

- 픽셀이 `pixel_convex_hull` 안에 있는가
- 계산된 X/Y가 `robot_xy_bounds_mm` 안에 있는가
- 현재 TCP가 측정 당시와 같은가
- 현재 로봇이 안전한 높이에 있는가
- 목표 Z와 손목 방향이 기록된 기준과 같은가

이 검사는 [`../tools/measurement/04_hover_test.py`](../tools/measurement/04_hover_test.py)에 구현되어 있다.

## 5. 로봇 이동에 적용하는 방식

재료를 집을 때는 다음과 같이 값을 조합한다.

```text
목표 X/Y = xy_correction.json으로 계산
목표 Z = pick_reference의 Z
목표 방향 = pick_reference의 RX/RY/RZ
```

바로 집기점으로 이동하지 않고 다음 순서를 사용한다.

```text
현재 안전 높이
→ 안전 높이를 유지하며 목표 X/Y로 수평 이동
→ 물체 위 Hover Z로 이동
→ 위치 확인
→ 낮은 속도로 집기 Z까지 하강
→ 그리퍼 position=430, current=200
→ Hover Z까지 상승
```

보울에 놓을 때도 보울 픽셀에서 X/Y를 계산하고, Z와 방향만 `place_reference`에서 가져온다.

## 6. 공유 및 재사용 조건

다음 물리 조건이 같을 때만 팀원과 공유해서 사용할 수 있다.

- 같은 E0509와 로봇 베이스 위치
- 같은 작업대 위치와 높이
- 같은 RealSense 카메라 위치와 각도
- 같은 640×480 RGB 영상
- 같은 기본 플랜지/0 오프셋 TCP
- 같은 그리퍼 설치 상태
- 같은 높이의 작업 평면과 70mm 재료 박스

팀원이 다른 노트북을 사용하더라도 같은 로봇·카메라·작업대를 번갈아 연결하는 것이라면 보정 파일을 공유할 수 있다. `/dev/video6` 같은 카메라 장치 번호는 노트북마다 달라질 수 있으므로 실행 인자로 별도 지정한다.

다음 조건이 바뀌면 9점 보정을 다시 수행한다.

- 카메라가 움직임
- 작업대 위치 또는 높이가 바뀜
- 로봇 베이스가 움직임
- 카메라 해상도가 바뀜
- TCP 또는 그리퍼 장착 상태가 바뀜

## 7. 다음 검증

먼저 로봇 이동 없이 계산 결과를 확인한다.

```bash
$PY tools/measurement/04_hover_test.py \
  --class-name tomato \
  --camera 6
```

그다음 [`../tools/measurement/04_hover_test.md`](../tools/measurement/04_hover_test.md)의 안전 절차에 따라 실제 Hover 시험을 진행한다. 중앙과 작업영역 가장자리에서 오차를 확인한 후에만 집기 Z 하강을 추가한다.
