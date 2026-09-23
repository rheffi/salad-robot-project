# 02 자세 기록 사용법

대상 파일: [`02_pose_recorder.py`](02_pose_recorder.py)

수동으로 맞춘 현재 로봇 자세를 `config/robot_measurements.yaml`에 저장한다. 스크립트는 로봇을 움직이지 않는다.

## 기록 방법

1. 로봇을 수동 모드(`robot_mode: 0`)로 전환한다.
2. 저속 조그로 원하는 자세를 만든다.
3. 작업영역에서 손을 빼고 아래 명령을 실행한다.
4. 출력된 `posj`, `posx`, TCP를 확인한 뒤 `SAVE`를 입력한다.

```bash
$PY tools/measurement/02_pose_recorder.py --name home
$PY tools/measurement/02_pose_recorder.py --name safe_wait
$PY tools/measurement/02_pose_recorder.py --name pick_reference
$PY tools/measurement/02_pose_recorder.py --name place_reference
```

- `home`: 시작·종료 및 최초 YOLO 촬영
- `safe_wait`: 작업대 위 안전 대기
- `pick_reference`: 재료별 동적 X/Y에 결합할 집기 Z와 방향
- `place_reference`: 동적 보울 X/Y에 결합할 놓기 Z와 방향

같은 이름을 다시 저장할 때만 `--overwrite`를 붙인다.

```bash
$PY tools/measurement/02_pose_recorder.py --name pick_reference --overwrite
```

모든 자세는 동일한 기본 플랜지 TCP 상태에서 기록해야 한다.
