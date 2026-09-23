# 01 시스템 점검 사용법

대상 파일: [`01_system_check.py`](01_system_check.py)

로봇, 그리퍼, RealSense, YOLO 모델, HandEye 파일과 ROS 설정을 읽기 전용으로 점검한다. 로봇은 움직이지 않는다.

## 실행

```bash
cd ~/dev_ws/salad_robot_project
source /opt/ros/jazzy/setup.bash
source ~/doosan_ws/install/setup.bash
export ROS_DOMAIN_ID=15
PY=/home/choi-chun-hwan/venv/yolo-venv/bin/python

$PY tools/measurement/01_system_check.py --camera 6
```

다음 항목이 모두 `[OK]`이면 통과다.

- `ROS_DOMAIN_ID: '15'`
- YOLO 모델과 필수 클래스
- HandEye 4×4 행렬
- RealSense RGB 640×480
- E0509 연결
- 그리퍼 서비스

`Active TCP:` 뒤가 비어 있는 것은 현재 프로젝트에서 사용하는 기본 플랜지/0 오프셋 상태다. 이후 측정 중 다른 TCP로 바꾸지 않는다.

점검이 끝나면 [`02_pose_recorder.md`](02_pose_recorder.md) 또는 아직 하지 않은 실측 단계로 이동한다.
