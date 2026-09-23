# 09 세 재료 샐러드 순차 실행

회전 집기는 `--rotate --reference-yaw-deg 실측값`으로 켠다. 이때 최초 장면 촬영에
각도 검출도 적용된다. 07 Hover 및 08 단일 투입 검증을 먼저 진행한다.
기준각과 외곽선 확인 방법은 [박스 회전 시험 안내](box_orientation.md)를 참고한다.

대상 파일: [`09_salad_sequence.py`](09_salad_sequence.py)

HOME에서 최초 장면을 한 번 촬영하고 저장한 좌표만 사용해 `tomato → cheese → berry` 순서로 보울에 넣는다. 첫 투입 후 보울이 가려져도 다시 인식하지 않는다.

## DRY RUN

로봇이 카메라를 가리지 않는 상태에서 실행한다.

```bash
$PY tools/measurement/09_salad_sequence.py --camera 6
```

네 대상을 검출해 snapshot을 저장하고 전체 순서를 출력하지만 로봇과 그리퍼는 움직이지 않는다.

## 실제 실행

```bash
$PY tools/measurement/09_salad_sequence.py \
  --camera 6 \
  --hover-height-mm 100 --vel 10 --acc 10 --live
```

첫 확인 문구:

```text
PREPARE SCENE
```

로봇이 `safe_wait → HOME`으로 이동한 뒤 카메라 창이 열린다. 네 대상이 모두 안정적으로 검출되면 중심을 확인하고 `C`를 누른다.

저장된 네 좌표와 순서를 확인한 후 실제 전체 작업을 시작하려면 다음을 입력한다.

```text
RUN SALAD
```

전체 동작:

```text
HOME 최초 촬영 및 좌표 저장
→ tomato 집기·보울 기준 Z에 투입
→ cheese 집기·보울 기준 Z + 40mm에 투입
→ berry 집기·보울 기준 Z + 80mm에 투입
→ safe_wait → HOME
```

박스 높이 30mm와 쌓임 오차를 고려해 뒤 재료의 놓기 Z를 40mm씩 높인다.
XY는 세 재료 모두 촬영한 보울 중심을 사용한다. 이는 힘/높이 센서로 실제 쌓임을
측정하는 기능이 아니므로 08에서 첫 놓기 Z를 확인하고, 09 전에 빈 보울에서 경로를
검증해야 한다. 박스가 기울거나 보울 밖으로 밀리면 다음 재료를 실행하지 않는다.

각 재료는 집기 전에 safe_wait를 거친다. 중간에 오류나 `Ctrl+C`가 발생하면 자동으로 그리퍼를 열거나 HOME으로 복귀하지 않는다. 현재 로봇과 그리퍼 상태를 확인한 뒤 수동으로 복구한다.

세 재료 순차 실행이 안정되면 터미널 동작을 Web UI 작업 큐에 연결한다. 소스병 동작은 그 이후의 선택 확장이다.
