# 06 보울 Hover 시험

대상 파일: [`06_bowl_hover_test.py`](06_bowl_hover_test.py)

`scene_snapshot.json`의 보울 X/Y와 `place_reference`의 Z·방향을 결합해 보울 위 100mm까지만 이동한다. 놓기 Z 하강과 그리퍼 동작은 하지 않는다.

## DRY RUN

```bash
$PY tools/measurement/06_bowl_hover_test.py
```

보울 X/Y, place Z, Hover Z, safe_wait Z와 이동 순서를 확인한다.

## 실제 시험

```bash
$PY tools/measurement/06_bowl_hover_test.py \
  --hover-height-mm 100 --vel 10 --acc 10 --live
```

현재 좌표와 `safe_wait` 목표를 보고 경로가 안전할 때만 다음을 입력한다.

```text
MOVE BOWL
```

동작:

```text
현재 자세 → safe_wait → 보울 X/Y 안전 높이
→ place_reference Z + 100mm → 정지
```

자동 복귀하지 않는다. 그리퍼 중심이 보울 중심과 맞는지 확인한다. 물체나 보울이 snapshot 저장 후 움직였다면 실행하지 않는다.

보울 Hover가 맞으면 [`07_single_pick_test.md`](07_single_pick_test.md)로 이동한다.
