# Feature Request: Internal Batch GUID Resolution

## 배경

대규모 프로젝트에서 `build_hierarchy(guid_index=...)` 사용 시 성능 문제:
- MonoBehaviour 컴포넌트마다 `guid_index.resolve_name()` 개별 호출
- N개 컴포넌트 → N개 SQLite 쿼리 → 1200ms+

## 현재 우회 방법 (prefab-merge-tool)

```python
class PathOnlyGUIDIndex:
    """스크립트 해석 건너뛰고 경로 해석만 허용하는 래퍼"""
    def resolve_name(self, guid): return None  # 스크립트 해석 건너뛰기
    def get_path(self, guid): return self._guid_index.get_path(guid)  # 경로는 허용

# 배치 쿼리로 스크립트 이름 해석
def batch_resolve(guids):
    placeholders = ",".join("?" * len(guids))
    cursor.execute(f"SELECT guid, path FROM guid_cache WHERE guid IN ({placeholders})", list(guids))
```

**결과: 1600ms → 80ms (20배 개선)**

---

## 제안: build_hierarchy 내부에서 자동 배치 처리

### 현재 동작 (느림)
```python
# build_hierarchy 내부에서 컴포넌트마다 개별 호출
for comp in components:
    if comp.script_guid:
        comp.script_name = guid_index.resolve_name(comp.script_guid)  # N번 SQLite 쿼리
```

### 제안 동작 (빠름)
```python
# build_hierarchy 내부에서 자동으로 배치 처리
def build_hierarchy(doc, guid_index=None, ...):
    # 1. 먼저 hierarchy 구조만 빌드 (스크립트 이름 없이)
    hierarchy = _build_structure(doc)

    # 2. 모든 스크립트 GUID 수집
    all_script_guids = {
        comp.script_guid
        for node in hierarchy.iter_all()
        for comp in node.components
        if comp.script_guid
    }

    # 3. 한 번에 배치 해석 (내부적으로 WHERE IN 쿼리)
    if guid_index and all_script_guids:
        script_names = guid_index._batch_resolve(all_script_guids)  # 1번 SQLite 쿼리

        # 4. 결과 적용
        for node in hierarchy.iter_all():
            for comp in node.components:
                if comp.script_guid:
                    comp.script_name = script_names.get(comp.script_guid)

    return hierarchy
```

### LazyGUIDIndex에 내부 배치 메서드 추가

```python
class LazyGUIDIndex:
    def _batch_resolve(self, guids: set[str]) -> dict[str, str]:
        """내부용 배치 해석 - build_hierarchy에서 자동 호출됨"""
        if not guids:
            return {}

        placeholders = ",".join("?" * len(guids))
        cursor = self._conn.execute(
            f"SELECT guid, path FROM guid_cache WHERE guid IN ({placeholders})",
            list(guids),
        )
        return {row[0]: Path(row[1]).stem for row in cursor}
```

---

## 장점

1. **API 변경 없음**: 기존 `build_hierarchy()` 호출 그대로 사용
2. **자동 최적화**: 사용자가 배치 처리를 신경 쓸 필요 없음
3. **하위 호환성**: 기존 코드 수정 불필요
4. **성능**: N개 쿼리 → 1개 쿼리

## 기대 효과

| 시나리오 | Before | After |
|---------|--------|-------|
| 프리팹 로드 (100개 MonoBehaviour) | N×SQLite 쿼리 | 1×배치 쿼리 |
| 대규모 프로젝트 hierarchy 빌드 | 1200ms+ | ~30ms |

## 구현 난이도

- `LazyGUIDIndex`에 `_batch_resolve()` 메서드 추가: 간단
- `build_hierarchy` 내부 로직 수정: 중간 (수집 → 배치해석 → 적용)
- 테스트: 기존 테스트 통과 확인

---

## 요약

새로운 파라미터나 API 추가 없이, `build_hierarchy` 내부에서 자동으로 배치 처리하여 성능 개선. 사용자 입장에서는 기존과 동일하게 사용하면서 20배 빠른 성능을 얻음.
