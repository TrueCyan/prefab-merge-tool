# Feature Request: Performance Improvements

## 문제 1: GUIDIndex가 전체 인덱스를 메모리에 로드

### 현재 구현

```python
@dataclass
class GUIDIndex:
    guid_to_path: dict[str, Path] = field(default_factory=dict)  # 전부 메모리
    path_to_guid: dict[Path, str] = field(default_factory=dict)  # 전부 메모리
```

`get_cached_guid_index()` 호출 시 SQLite에서 **모든 엔트리**를 메모리로 로드합니다.
170k 에셋 프로젝트 → 340k dict 엔트리 → 느린 초기 로딩

### 제안: Lazy SQLite Query

```python
@dataclass
class LazyGUIDIndex:
    """SQLite를 직접 쿼리하는 lazy GUIDIndex."""
    _db_path: Path
    _conn: sqlite3.Connection | None = None
    _cache: dict[str, Path] = field(default_factory=dict)  # LRU 캐시 (선택적)

    def get_path(self, guid: str) -> Path | None:
        # 먼저 캐시 확인
        if guid in self._cache:
            return self._cache[guid]

        # DB 직접 쿼리
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT path FROM guid_cache WHERE guid = ?", (guid,)
        )
        row = cursor.fetchone()
        if row:
            path = Path(row[0])
            self._cache[guid] = path  # 캐시에 저장
            return path
        return None
```

### 기대 효과

- 초기 로딩: O(N) → O(1)
- 메모리 사용: 전체 인덱스 → 필요한 것만
- SQLite 인덱스로 O(log N) 조회 (충분히 빠름)

---

## 문제 2: Nested Prefab 캐싱 없음

`load_source_prefab()` 호출 시 같은 소스 프리팹이 여러 번 사용되어도 매번 새로 로드합니다:

```python
# unityflow/hierarchy.py - HierarchyNode.load_source_prefab()
source_doc = UnityYAMLDocument.load_auto(source_path)  # 매번 파일 읽기
source_hierarchy = Hierarchy.build(source_doc, guid_index=guid_index)  # 매번 파싱
```

### 성능 영향

같은 프리팹이 N번 참조되면 N번 로드/파싱:
- `board_Upgrade` 10회 사용 → 10번 파싱
- `board_CoreUpgrade` 5회 사용 → 5번 파싱

실제 프로젝트에서 nested prefab이 많으면 로딩 시간이 기하급수적으로 증가합니다.

## 제안: Hierarchy 레벨 캐싱

```python
class Hierarchy:
    def __init__(self):
        # ...existing code...
        self._nested_prefab_cache: dict[str, Hierarchy] = {}  # guid -> Hierarchy

    def _get_or_load_nested_hierarchy(
        self,
        source_guid: str,
        source_path: Path,
        guid_index: GUIDIndex,
    ) -> Optional[Hierarchy]:
        """Get cached hierarchy or load and cache."""
        if source_guid in self._nested_prefab_cache:
            return self._nested_prefab_cache[source_guid]

        source_doc = UnityYAMLDocument.load_auto(source_path)
        source_hierarchy = Hierarchy.build(source_doc, guid_index=guid_index)
        self._nested_prefab_cache[source_guid] = source_hierarchy
        return source_hierarchy
```

```python
# HierarchyNode.load_source_prefab() 수정
def load_source_prefab(self, ...):
    # ...existing validation code...

    # 캐시 사용
    source_hierarchy = self._hierarchy._get_or_load_nested_hierarchy(
        self.source_guid,
        source_path,
        guid_index,
    )

    if source_hierarchy is None:
        return False

    # 캐시된 hierarchy의 노드들을 복사하여 merge
    for source_root in source_hierarchy.root_objects:
        self._merge_nested_node(source_root.copy(), guid_index, _loading_prefabs)

    self.nested_prefab_loaded = True
    return True
```

### 고려사항

1. **노드 복사**: 캐시된 hierarchy를 직접 사용하면 안 되고, 노드들을 복사해서 merge해야 함 (각 PrefabInstance마다 별도의 수정/상태가 있을 수 있음)

2. **메모리 vs 속도 트레이드오프**:
   - 캐시를 사용하면 메모리 사용량 증가
   - 하지만 같은 프리팹 10번 로드보다 1번 로드 + 9번 복사가 훨씬 빠름

3. **캐시 무효화**:
   - 단일 build_hierarchy() 호출 범위 내에서만 캐시 유지
   - 새로운 Hierarchy 인스턴스는 빈 캐시로 시작

## 기대 효과

- 같은 프리팹 N번 참조 시: N번 로드 → 1번 로드 + (N-1)번 shallow copy
- I/O 감소, 파싱 시간 감소
- 실제 프로젝트에서 로딩 시간 대폭 개선

## 대안: UnityYAMLDocument 레벨 캐싱

더 낮은 레벨에서 캐싱할 수도 있습니다:

```python
_document_cache: dict[Path, UnityYAMLDocument] = {}

def load_auto_cached(path: Path) -> UnityYAMLDocument:
    if path not in _document_cache:
        _document_cache[path] = UnityYAMLDocument.load_auto(path)
    return _document_cache[path]
```

이 방식은:
- 장점: 더 낮은 레벨에서 캐싱, 다른 용도로도 재사용 가능
- 단점: 모듈 레벨 전역 상태, 메모리 관리가 어려움

Hierarchy 레벨 캐싱이 더 깔끔한 해결책이라고 생각합니다.
