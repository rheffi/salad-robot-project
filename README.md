# Salad Robot Project

E0509 샐러드 제조 로봇 프로젝트입니다. Web UI는 기본 **Mock** 모드와, 별도로 활성화하는 **실장비 05~09 연동**을 제공합니다. 실장비 웹 실행·설치·시험 순서는 [웹 실장비 사용법](web_ui/REAL_MODE.md)을 먼저 확인하세요. 실제 장비 통합 시험은 별도로 필요합니다.

## 현재 제공 기능

- FastAPI 기반 REST API와 WebSocket
- 한국어 단일 대시보드
- 초기화, 장면 인식, DRY RUN, 정지 요청, 준비자세 복귀
- 단일 작업 큐를 통한 중복 실행 차단
- Mock 재료 검출과 샐러드 작업 상태 전이
- 기본 Mock / REAL에서도 기본 DRY RUN, 실제 이동은 작업별 확인 후 실행
- REAL 장면 촬영, 보울/재료 Hover, 단일 집기·반환, 단일/세 재료 투입

## 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn web_ui.app:app --host 127.0.0.1 --port 8000
```

브라우저에서 <http://127.0.0.1:8000>을 엽니다. API 문서는 <http://127.0.0.1:8000/docs>에서 확인할 수 있습니다.

## 테스트

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_real_core.py
# 비전/동작 순서 테스트는 OpenCV/YOLO가 있는 환경에서 실행 (장비 호출 없음)
/home/choi-chun-hwan/venv/yolo-venv/bin/python tests/test_box_orientation.py
/home/choi-chun-hwan/venv/yolo-venv/bin/python tests/test_hardware_workflow.py
```

## 폼 박스 그리퍼 시험

`tools/gripper_cube_test.py`는 현재 로봇 자세를 집기점으로 기록한 뒤, XY나 자세를 바꾸지 않고 다음 동작만 반복합니다.

```text
집기점 위로 상승 → 수직 하강 → 그리퍼 닫기 → 수직 상승
→ 관찰 → 수직 하강 → 그리퍼 열기 → 수직 후퇴
```

먼저 기존 방식으로 로봇 bringup을 실행하고, 별도 터미널에서 그리퍼 서비스를 실행합니다.

```bash
source /opt/ros/jazzy/setup.bash
source ~/doosan_ws/install/setup.bash
export ROS_DOMAIN_ID=15
ros2 run dsr_gripper gripper_service
```

새 터미널에서 같은 환경을 불러온 뒤 실행합니다. `--live`가 없으면 로봇을 움직이지 않고 동작 계획만 출력합니다.

```bash
cd ~/dev_ws/salad_robot_project
source /opt/ros/jazzy/setup.bash
source ~/doosan_ws/install/setup.bash
export ROS_DOMAIN_ID=15

# 먼저 동작 순서 확인
python3 tools/gripper_cube_test.py --size-mm 40

# 현재 로봇 자세를 정확한 집기점으로 맞춘 다음 실물 시험
python3 tools/gripper_cube_test.py --size-mm 40 --live
```

실행 중 각 시험의 `close position`과 `current`를 입력합니다. `position`은 0이 완전 닫힘, 750이 완전 열림이며, 이 시험 도구는 `current`를 1~400으로 제한합니다. 설치된 그리퍼 문서의 파지 권장값은 200~400이므로 처음에는 약한 쪽부터 조금씩 올립니다. 40/50/60 mm 박스별 결과는 `results/gripper_trials.csv`에 누적됩니다.

시험 전 활성 TCP가 맞는지 화면에서 확인하고 비상정지 버튼을 바로 누를 수 있게 준비합니다. `RUN`을 입력하기 전에는 움직이지 않으며, `Ctrl+C`나 오류 발생 시 추가 복귀 동작을 자동 실행하지 않습니다.

## YOLO 학습

`print_phone` 데이터의 클래스 변환, train/val 재분할 및 CPU 학습 방법은 [`ml/README.md`](ml/README.md)를 참고합니다. 학습 완료 모델은 `ml/models/best.pt`에 생성됩니다.

## 안전 범위

Mock은 실제 로봇을 제어하지 않습니다. REAL 모드는 실제 이동 체크와 확인 문구 입력 후 로봇을 움직입니다. 화면의 정지는 현재 호출 종료 후 후속 명령을 막는 요청이며 물리 비상정지가 아닙니다. 경로 충돌 회피와 파지 성공 자동 판정은 제공하지 않습니다. 자세한 제한은 [실장비 사용법](web_ui/REAL_MODE.md)을 확인하세요.
# salad-robot-project
