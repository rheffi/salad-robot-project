# 박스 회전 검출과 집기 시험

기존 `best.pt`를 그대로 사용한다. YOLO 영역 안의 외곽선을 찾아 XY 보정행렬로
로봇 평면에 옮긴 뒤 OpenCV `minAreaRect()`로 70mm 정사각형 방향을 계산한다.
검출 대상은 tomato/cheese/berry이며 보울 방향은 사용하지 않는다.

기본 실행은 기존 고정 방향이다. 05의 `--angles`는 카메라 검출만 활성화하고,
07~09의 `--rotate`는 실제 집기 방향에 적용한다. 이전 snapshot은 고정 방향으로
계속 사용할 수 있지만 회전 실행에는 새 각도 데이터가 필요하다.

## 1. 카메라만으로 외곽선 확인

프로젝트 루트에서 기존 yolo-venv로 실행한다.

```bash
cd ~/dev_ws/salad_robot_project
PY=/home/choi-chun-hwan/venv/yolo-venv/bin/python
$PY tools/measurement/05_scene_capture.py --camera 6 --angles
```

- 각 재료는 하나씩, 서로 떨어뜨려 둔다. 보울도 보여야 한다.
- 청록 사각형이 **사진 속 무늬가 아니라 실제 폼 박스 바깥 변**에 맞아야 한다.
- 표시되는 `base deg`는 로봇 XY 기준 변의 각도다. 이미지 각도가 아니다.
- 0°·15°·30°·45°로 놓아 관찰한다. 정사각형은 90° 대칭이므로 표시값은
  -45° 이상 45° 미만이며 +45° 부근에서 -45°로 바뀔 수 있다.
- 세 박스 외곽선과 네 대상 중심을 확인한 후 `stable 4/4`에서 C로 저장한다.
  저장된 사진과 JSON은 기존 `records/scene_snapshot.*`를 갱신한다.

ROI 잘림, 영역 밖 꼭짓점, 70mm와 크게 다른 크기, 비정사각형, 모호한 외곽선,
기본적으로 최근 유효한 5개 외곽선을 평균내며, 한두 프레임 외곽선 누락은 허용한다.
표시되는 크기·각도·점수가 안정적인지 확인한다. `quality`는 기하학적 점수이며
올바른 물체를 잡았다는 확률이 아니다. 그림 속 사각형이나 그림자가 통과할 수
있으므로 시각 확인은 필요하다. 흰 폼/흰 작업대에서 실패하면 조명과 배경 대비를
개선한다. 필터를 무조건 낮추지 않는다.

## 2. 기준각 한 번 확인

`pick_reference`의 고정 방향으로 이미 잘 집혔던 방향으로 토마토를 놓고 05를
실행한다. 그 상태의 출력 `tomato` 아래 `base yaw=...deg` 숫자를 기준값으로 쓴다.
기존에 잘 잡힌 방향을 재현할 수 없다면 기준값부터 실측해야 한다.
화면 수평을 임의로 0으로 입력하지 않는다.

```bash
read -r -p '정방향 토마토의 실측 base yaw 숫자: ' REF_YAW
```

새 터미널에서도 이 값을 다시 설정한다. 카메라·XY 보정·TCP·그리퍼 장착·기준 집기
자세를 변경하면 기준각도 다시 검증한다. 세 상자의 윗면 높이는 XY 보정 평면과
맞아야 한다. 깊이나 높이를 이 알고리즘이 보정해 주지는 않는다.

## 3. 회전한 박스로 Hover만 검증

박스를 회전시킨 다음 **05 --angles로 다시 촬영**한다. 아래 첫 명령은 계획만 출력한다.

```bash
$PY tools/measurement/07_single_pick_test.py --class-name tomato \
  --rotate --reference-yaw-deg "$REF_YAW" --hover-only
```

좌표·각도·주변 경로 확인 후 실제 Hover 시험:

```bash
$PY tools/measurement/07_single_pick_test.py --class-name tomato \
  --rotate --reference-yaw-deg "$REF_YAW" --hover-only \
  --hover-height-mm 100 --vel 10 --acc 10 --live
```

`HOVER TOMATO`를 입력하면 safe_wait → 같은 높이에서 제자리 방향 정렬 → 목표 XY
→ Hover로 이동한다. 그리퍼 명령 및 집기 Z 하강은 없다. 자동 복귀하지 않는다.
기존 `00_move_to_recorded_pose.py` 안내에 따라 복귀한 뒤 다음 시험을 준비한다.

회전은 기준과의 최단 차이(-45~45°)를 Doosan ZYZ 자세의 **A**에 더한다.
J6만 돌리는 명령도, 일반 RPY의 Z값을 바꾸는 명령도 아니다. 원래 자세의 기울기는
유지하되 base Z 중심으로 방향을 바꾼다. 기본 플랜지 TCP이므로 그리퍼 중심에
편심이 있으면 회전 후 집기 중심도 달라질 수 있다. Hover에서 방향과 XY 모두 확인한다.
이동 경로 충돌 회피나 박스 크기에 따른 그리퍼 간격 계산은 하지 않는다.

## 4. 단일 집기 → 보울 투입 → 세 재료

Hover 검증 후 `--hover-only`를 빼면 07 집기 시험이다. `--live` 없이 계획 확인을
먼저 하고, 실제 시험할 때 붙인다. 그리퍼 무반응 문제가 남아 있으면 집기를 진행하지 않는다.

```bash
$PY tools/measurement/07_single_pick_test.py --class-name tomato \
  --rotate --reference-yaw-deg "$REF_YAW" --live

$PY tools/measurement/08_single_pick_place.py --class-name tomato \
  --rotate --reference-yaw-deg "$REF_YAW" --live

$PY tools/measurement/09_salad_sequence.py --camera 6 \
  --rotate --reference-yaw-deg "$REF_YAW" --live
```

07은 `PICK TOMATO`, 08은 `RUN ONE`, 09는 `PREPARE SCENE`과 `RUN SALAD` 확인을
유지한다. 09의 `--rotate`는 최초 촬영 때 각도 검출도 켠다. 세 재료 각도를 모두
검사한 뒤 집기를 시작한다. 보울에서는 기존 `place_reference` 방향으로 돌아간다.
중간 실패 시 자동 복구·그리퍼 열기를 하지 않는다.

기존 정방향 방식으로 돌아가려면 05에서 `--angles`, 07~09에서 `--rotate`를
생략한다. 이는 회전 박스를 자동 처리하는 대체 수단이 아니다. 박스를 검증한
고정 방향으로 직접 배치해야 한다.

## 검증 범위

합성 영상의 각도·원근 변환, 검출 실패, 90° 경계 평균, 가짜 로봇의 회전/XY/하강
순서와 Hover의 무그리퍼 동작을 자동 검사한다. 실카메라 외곽선 성능, 실제 회전
경로와 집기 성공은 별도 실측 검증 대상이다.
