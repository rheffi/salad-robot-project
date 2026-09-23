# 05 최초 장면 좌표 저장

대상 파일: [`05_scene_capture.py`](05_scene_capture.py)

HOME처럼 로봇이 화면을 가리지 않는 상태에서 `tomato`, `cheese`, `berry`, `bowl`을 한 번에 검출하고 로봇 X/Y로 변환해 저장한다. 이 스크립트는 로봇을 움직이지 않는다.

## 실행

```bash
$PY tools/measurement/05_scene_capture.py --camera 6
```

네 대상이 모두 `stable 10/10`이면 빨간 십자가가 각 물체 중앙인지 확인하고 `C`를 누른다. 취소는 `Q` 또는 `Esc`다.

생성 파일:

```text
records/scene_snapshot.json
records/scene_snapshot.jpg
```

JSON에는 각 대상의 픽셀, confidence, 보정된 로봇 X/Y가 들어간다. 현재 `xy_correction.json`의 Y `+10mm` 오프셋도 기록된다.

## 중요 조건

- 저장 후 재료나 보울을 움직이면 snapshot을 폐기하고 다시 촬영한다.
- 카메라나 XY 보정값이 바뀌어도 다시 촬영한다.
- 같은 클래스가 여러 개면 confidence가 가장 높은 하나만 선택하므로 각 대상은 하나씩 놓는다.
- 네 대상 중 하나라도 안정적으로 검출되지 않으면 저장하지 않는다.

저장 후에는 [`06_bowl_hover_test.md`](06_bowl_hover_test.md)로 보울 좌표를 검증한다.
