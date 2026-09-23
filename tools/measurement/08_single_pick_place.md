# 08 단일 재료 집기·보울 놓기

대상 파일: [`08_single_pick_place.py`](08_single_pick_place.py)

저장된 재료 하나를 집어 저장된 보울 X/Y에 놓고 HOME으로 복귀하는 첫 완전 동작이다.

## DRY RUN

```bash
$PY tools/measurement/08_single_pick_place.py --class-name tomato
```

재료 X/Y·pick Z, 보울 X/Y·place Z, 그리퍼 값과 종료 자세를 확인한다.

## 실제 시험

```bash
$PY tools/measurement/08_single_pick_place.py \
  --class-name tomato \
  --hover-height-mm 100 --vel 10 --acc 10 --live
```

전체 경로가 안전할 때만 입력한다.

```text
RUN ONE
```

동작:

```text
safe_wait → 토마토 Hover → 집기 Z → 430/200으로 집기
→ 안전 높이 → 보울 Hover → place_reference Z
→ 그리퍼 750으로 열기 → 안전 높이 → safe_wait → HOME
```

보울 테두리 충돌, 놓기 높이, 박스가 보울 안에 들어가는지 확인한다. 오류 시 자동 복귀하지 않는다.

단일 집기·놓기를 3회 성공한 후 [`09_salad_sequence.md`](09_salad_sequence.md)를 진행한다.
