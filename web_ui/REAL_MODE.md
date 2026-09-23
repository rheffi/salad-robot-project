# 실장비 웹 사용법 — 05부터 09까지

## 현재 범위

웹에서 카메라/YOLO 촬영 → 좌표 확인 → 보울 Hover → 단일 집기/반환 → 단일 투입 → 세 재료 투입을 실행합니다.
토마토(`tomato`), 치즈(`cheese`), 블루베리(`berry`) 각 1개, 보울 1개가 대상입니다. 소스병 동작은 포함하지 않습니다.

**코드 연동과 장비 없는 자동 테스트까지 완료한 상태입니다. 실제 로봇·카메라 통합 검증은 별도로 필요합니다.**

기본 서버는 기존 Mock입니다. `SALAD_CORE=real`로 실행해야 실제 장비를 연결합니다.
REAL에서도 기본 동작은 DRY RUN입니다. 실제 이동 체크와 작업별 확인 문구를 모두 입력해야 움직입니다.

## 1. 준비

- 로봇 bringup은 기존 방식으로 별도 터미널에서 실행합니다. 도메인은 모두 `15`입니다.
- 현재 설치된 그리퍼 구현 기준으로 아래 `gripper_service_a` **하나만** 실행합니다. 기존 `gripper_service`가 있으면 그 터미널에서 먼저 종료합니다. 두 서비스 동시 실행은 금지합니다.
- CLI 04~09, 노트북 커널의 로봇 코드, 다른 웹 서버를 동시에 조작하지 않습니다. 웹 내부 잠금은 별도 CLI를 차단하지 못합니다.
- 카메라를 사용하는 다른 프로그램은 닫습니다. 카메라/작업대/박스 위치를 확인합니다.
- `config/robot_measurements.yaml`, `config/xy_correction.json`, `ml/models/best.pt`가 현재 장비 배치에 맞아야 합니다. Z는 기록값, XY는 보정 파일을 사용합니다. HandEye 파일을 웹에서 별도로 다시 적용하지 않습니다.

그리퍼 서비스 터미널:

```bash
source /opt/ros/jazzy/setup.bash
source ~/doosan_ws/install/setup.bash
export ROS_DOMAIN_ID=15
ros2 run dsr_gripper gripper_service_a
```

현재 `yolo-venv`에는 웹 패키지가 없으므로 최초 한 번 다음을 실행합니다. ROS/카메라/YOLO 환경은 기존 환경 그대로 씁니다.

```bash
cd ~/dev_ws/salad_robot_project
/home/choi-chun-hwan/venv/yolo-venv/bin/python -m pip install -r requirements.txt
```

이 설치는 이번 코드 작성 중 자동으로 실행하지 않았습니다. 기존 NumPy/OpenCV/YOLO를 재설치할 필요는 없습니다.

## 2. 웹 서버 실행

새 터미널에서:

```bash
cd ~/dev_ws/salad_robot_project
source /opt/ros/jazzy/setup.bash
source ~/doosan_ws/install/setup.bash
export ROS_DOMAIN_ID=15
export SALAD_CORE=real
export SALAD_CAMERA=6
/home/choi-chun-hwan/venv/yolo-venv/bin/python -m uvicorn web_ui.app:app \
  --host 127.0.0.1 --port 8000 --workers 1
```

브라우저: <http://127.0.0.1:8000>

- `--reload`와 다중 worker는 사용하지 않습니다. ROS 노드는 한 프로세스의 전용 스레드에서 한 번만 생성하고 유지합니다.
- 카메라 번호가 바뀌면 확인 후 `SALAD_CAMERA`를 바꿉니다. `auto`도 지원합니다.
- `0.0.0.0`으로 공개하지 마세요. 인증 없는 로컬 제어용입니다.
- 초기화 실패나 설정/모델 변경 후에는 서버를 종료하고 재시작합니다. 실행 중 설정 파일을 수정하지 마세요.
- 연결 표시의 ‘점검 통과’는 마지막 점검 결과이며 상시 장비 생존 감시는 아닙니다.

## 3. 권장 시험 순서

| 순서 | 웹 버튼 | 실제 동작/확인 문구 |
|---|---|---|
| 초기화 | 시스템 초기화 | 모델·보정·카메라·ROS·TCP·그리퍼 서비스 확인. 이동 없음 |
| 준비 | 준비자세 복귀 | 현재 → safe_wait → HOME. `MOVE HOME` |
| 05 | 장면 인식 | 네 대상 검출이 안정되면 자동 저장. 이동 없음 |
| 06 | 보울 Hover | safe_wait → 보울 안전 높이 → 놓기 Z+Hover. `MOVE BOWL` |
| 07a | 재료 Hover | 선택 재료 위로 접근만. 그리퍼/집기 Z 하강 없음. `HOVER TOMATO` 등 |
| 07b | 집기 · 들고 대기 | 열기 → 하강 → 닫기 → 상승 → 안전 높이 대기. `PICK TOMATO` 등 |
| 반환 | 원위치 반환 | 07에서 집었던 위치에 놓고 safe_wait. `RETURN` |
| 08 | 한 개 집고 담기 | 선택 재료 1개 → 보울 → HOME. `RUN ONE` |
| 09 | 전체 순서 실행 | tomato(Z+0) → cheese(Z+40mm) → berry(Z+80mm) → HOME. `RUN SALAD` |

1. 먼저 **실제 이동 체크 해제** 상태에서 계획/로그를 확인합니다. DRY RUN은 실제 이동, 모드 전환, 그리퍼 명령을 보내지 않습니다. 장비 초기화와 05 촬영은 필요합니다.
2. 초기 촬영을 가리는 자세라면 현장에서 경로를 확인하고 준비자세 복귀를 실제 실행합니다. **현재→safe_wait의 관절 이동은 충돌 회피가 자동 계산되지 않습니다.**
3. 05 사진의 대상, 빨간 중심점, 좌표가 실제 배치와 맞는지 확인합니다. 표시 영상은 실시간 스트리밍이 아닌 마지막 촬영본입니다.
4. 실제 이동을 체크하고 06 → 07a → 07b → RETURN 순서로 확인합니다. Hover 완료 후 자동 HOME 복귀는 없습니다.
5. 집은 동안은 원위치 반환만 허용합니다. 서버를 끄거나 다른 프로그램으로 움직이지 마세요. RETURN은 저장된 경로를 사용하므로 원위치에 다른 물건을 두면 안 됩니다.
6. 반환/투입/실제 HOME 이후에는 05를 다시 실행합니다. 08 후 재료를 원래 작업대에 되돌려 두고 **다시 05**, 그다음 09를 실행합니다.

08/09는 첫 장면의 보울/재료 좌표를 끝까지 사용하므로 보울 위에 박스가 올라가 재검출되지 않아도 동작합니다. 09는 30mm 박스 쌓임을 고려해 놓기 Z를 `0/+40/+80mm`로 올리지만 실제 쌓임을 센서로 확인하지는 않습니다. 도중에 박스가 기울거나 사람이나 물체가 배치를 바꾸면 안 됩니다.
그리퍼 값은 닫기 **430 / current 200**, 열기 **750 / current 200**이고 명령 후 2초 대기합니다. 서비스 성공은 **실제 파지 성공 판정이 아닙니다**. 미끄러짐/빈 집기는 사람이 확인합니다.

## 4. 회전 집기

- 기본은 기록된 고정 방향입니다. 박스를 정방향으로 두면 회전을 꺼둡니다.
- 회전 사용 시 체크 → 기준각 입력 → **05 다시 촬영** → 사진의 청록 외곽선 확인 → 07a부터 시험합니다.
- 기준각은 `pick_reference` 기록 당시 박스의 robot-base 기준 외곽각입니다. 카메라 픽셀 각도나 로봇 C값을 그대로 넣는 값이 아닙니다. [상세 설명](../tools/measurement/box_orientation.md)을 참고합니다.
- 불안정한 외곽선, 중복 대상, 인식 누락은 저장하지 않습니다. 인식은 약 45초 내 안정화되지 않으면 실패합니다. 카메라/추론 호출 자체가 멈추는 경우 이 제한보다 길어질 수 있습니다.
- 픽셀 XY는 보정값, 집기 Z는 기록값, 집기 회전은 박스 외곽각으로 계산합니다. 실제 깊이를 측정했다는 의미가 아닙니다.

## 5. 정지와 오류

**웹 정지는 즉시 정지가 아닙니다. 현재의 동기식 이동/그리퍼 호출이 반환된 뒤 다음 명령을 차단합니다. 긴급 상황에는 물리 E-STOP을 사용합니다.**

- 실제 동작 중 정지/오류가 나면 후속 명령을 차단합니다. 자동 HOME이나 자동 그리퍼 열기를 하지 않습니다.
- 박스를 들고 있는지, 로봇 위치와 주변 경로를 현장에서 확인하고 안전하게 복구한 후 서버를 재시작합니다. 재시작만으로 복구된 것은 아닙니다.
- 브라우저 닫기/새로고침/통신 끊김은 로봇 정지 명령이 아닙니다. 브라우저는 다시 열어 상태를 확인할 수 있습니다.
- 서버 종료도 진행 중 호출 완료를 기다립니다. 통신 장애로 호출이 반환되지 않으면 서버 종료도 지연될 수 있습니다.
- 여러 브라우저가 같은 서버를 볼 수 있지만 조작 담당자는 한 명으로 정합니다.

## 6. 저장 파일과 코드 위치

- 웹 사진/좌표: `records/web_scene_snapshot.jpg`, `records/web_scene_snapshot.json` (촬영할 때 갱신)
- CLI의 `scene_snapshot.*`는 웹에서 덮어쓰지 않습니다. 웹 서버 재시작 후에는 기존 파일로 자동 재개하지 않고 다시 촬영합니다.
- 브라우저가 보는 장면 ID와 서버 ID가 다르면 실행을 거부합니다. 보정/측정/모델 파일 변경도 실행 전에 확인합니다. 실제 물체 이동은 파일 검사로 감지할 수 없습니다.
- API: `web_ui/app.py`, 상태/작업 큐: `web_ui/real_core.py`
- 카메라/ROS 연결: `web_ui/hardware_backend.py`
- 공통 집기/놓기 순서: `tools/measurement/salad_workflow.py` — CLI 07/08/09와 웹이 공유합니다.
- UI: `web_ui/static/index.html`, `app.js`, `styles.css`

화면의 진행률은 명령 순서 기준의 근사치이고, ‘명령 순서 완료’는 투입 성공을 영상으로 검증한 결과가 아닙니다.

## 7. 장비 없이 실행하는 검사

```bash
cd ~/dev_ws/salad_robot_project
.venv/bin/python -m pytest tests/test_api.py tests/test_real_core.py
/home/choi-chun-hwan/venv/yolo-venv/bin/python tests/test_box_orientation.py
/home/choi-chun-hwan/venv/yolo-venv/bin/python tests/test_hardware_workflow.py
```

Mock과 FakeBackend로 05~09 API, DRY 무명령, 확인 문구, 중복 명령 거부, 단일 ROS 소유 스레드, 장면 ID, HOLDING/RETURN, 중단 후 복구 요구를 확인합니다. 실제 연결 어댑터의 09 순서와 창 없는 촬영도 가짜 장비로 검사합니다. 총 26개 테스트가 통과했습니다. 실제 카메라나 로봇을 연결하지 않았으며, 실제 브라우저의 화면/클릭 검증은 아직 하지 않았습니다.
