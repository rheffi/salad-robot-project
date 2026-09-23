# 07 단일 재료 집기·반환 시험

대상 파일: [`07_single_pick_test.py`](07_single_pick_test.py)

저장된 재료 좌표에서 박스 하나를 집어 안전 높이까지 올리고, 확인 후 원래 위치에 반환한다. 보울로 이동하지 않는다.

## DRY RUN

```bash
$PY tools/measurement/07_single_pick_test.py --class-name tomato
```

출력에서 다음을 확인한다.

- 재료 X/Y와 pick Z
- 그리퍼 `close=430`, `current=200`, `open=750`
- Hover 높이 100mm
- 최종 위치 safe_wait

## 실제 시험

```bash
$PY tools/measurement/07_single_pick_test.py \
  --class-name tomato \
  --hover-height-mm 100 --vel 10 --acc 10 --live
```

실제 시작 확인:

```text
PICK TOMATO
```

동작:

```text
safe_wait → 재료 Hover → pick_reference Z
→ 그리퍼 430/200 → Hover → 안전 높이 → 확인
```

안정적으로 잡힌 것을 확인한 뒤 다음을 입력하면 원래 위치로 반환한다.

```text
RETURN
```

`RETURN`을 입력하지 않으면 로봇은 박스를 든 안전 높이에 남으므로 그리퍼 상태를 직접 확인해야 한다. `Ctrl+C`나 오류 발생 시 자동 복귀하지 않는다.

토마토를 3회 연속 안정적으로 집고 반환한 뒤 [`08_single_pick_place.md`](08_single_pick_place.md)를 진행한다.
