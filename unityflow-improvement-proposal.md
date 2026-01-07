# unityflow 개선 제안서

## 핵심 원칙

1. **단순함 우선**: AI 도구가 명령어 목록만 보고 올바른 명령을 선택할 수 있어야 함
2. **이름 기반 작업**: fileID, GUID 같은 내부 구현을 숨기고 Unity Editor처럼 이름/경로로 작업
3. **내부 최적화**: API 변경 없이 성능 개선

---

## 1. 내부 최적화 (API 변경 없음)

### 1.1 배치 GUID 해석

**문제**: `build_hierarchy(guid_index=...)` 호출 시 MonoBehaviour마다 개별 SQLite 쿼리
- N개 컴포넌트 → N개 쿼리 → 1200ms+

**해결**: `build_hierarchy` 내부에서 자동 배치 처리

```python
# 현재 (느림)
for comp in components:
    comp.script_name = guid_index.resolve_name(comp.script_guid)  # N번 쿼리

# 개선 (빠름) - 내부적으로 자동 적용
def build_hierarchy(doc, guid_index=None, ...):
    hierarchy = _build_structure(doc)

    # 모든 스크립트 GUID 수집 후 한 번에 해석
    all_guids = {comp.script_guid for node in hierarchy.iter_all()
                 for comp in node.components if comp.script_guid}
    script_names = guid_index._batch_resolve(all_guids)  # 1번 쿼리

    # 결과 적용
    for node in hierarchy.iter_all():
        for comp in node.components:
            comp.script_name = script_names.get(comp.script_guid)

    return hierarchy
```

**효과**: 1600ms → 80ms (20배 개선)

### 1.2 패키지 GUID 인덱싱 확장

**현재 인덱싱 범위**: `Assets/` 폴더만 (173,551개)

**미인덱싱으로 인한 unresolved**:

| 소스 | 예시 | 원인 |
|------|------|------|
| Unity 패키지 | Image, Button, VerticalLayoutGroup | `Library/PackageCache/` 미인덱싱 |
| 로컬 패키지 | CommentaryComponent (MyBox) | `NK.Packages/` (file: 참조) 미인덱싱 |

**해결 - 인덱싱 대상 추가**:

1. `Library/PackageCache/` ← Unity Registry 패키지
2. `Packages/` ← Packages 폴더 내 로컬 패키지
3. `manifest.json` file: 참조 경로 ← `../../NK.Packages/` 같은 상대 경로

```python
def build_guid_index(project_root: Path) -> GUIDIndex:
    index = GUIDIndex()

    # 1. Assets 폴더 (기존)
    index.scan_directory(project_root / "Assets")

    # 2. Library/PackageCache (Unity 패키지)
    package_cache = project_root / "Library" / "PackageCache"
    if package_cache.exists():
        index.scan_directory(package_cache)

    # 3. manifest.json의 file: 참조 (로컬 패키지)
    manifest = project_root / "Packages" / "manifest.json"
    for dep_name, dep_value in load_manifest(manifest).get("dependencies", {}).items():
        if dep_value.startswith("file:"):
            # file:../../NK.Packages/com.domybest.mybox@1.7.0 같은 경로 해석
            relative_path = dep_value[5:]  # "file:" 제거
            package_path = (project_root / "Packages" / relative_path).resolve()
            if package_path.exists():
                index.scan_directory(package_path)

    return index
```

**해결되는 unresolved 목록**:

| GUID | 컴포넌트 | 패키지 |
|------|----------|--------|
| `ee85920dbe024568b894f71d5bb75c1e` | CommentaryComponent | MyBox |
| `59f8146938fff824cb5fd77236b75775` | VerticalLayoutGroup | Unity UI |
| `fe87c0e1cc204ed48ad3b37840f39efc` | Image | Unity UI |
| `306cc8c2b49d7114eaa3623786fc2126` | LayoutElement | Unity UI |
| `4e29b1a8efbd4b44bb3f3716e73f07ff` | Button | Unity UI |
| `30649d3a9faa99c48a7b1166b86bf2a0` | HorizontalLayoutGroup | Unity UI |
| `3245ec927659c4140ac4f8d17403cc18` | ContentSizeFitter | Unity UI |
| ... | 나머지 3개 | Unity UI / 기타 |

**효과**: 42개 의존성 중 10개 unresolved → 0개 (100% 해석)

---

## 2. CLI 단순화

### 현재 문제

- 명령어가 너무 많음: `query`, `get`, `set`, `export`, `import`, `find-name`, ...
- 일부만 이름 기반, 나머지는 fileID 필요
- AI가 잘못된 명령을 선택하기 쉬움

### 제안: 4개 핵심 명령어로 통합

| 명령어 | 용도 | 예시 |
|--------|------|------|
| `hierarchy` | 구조 탐색 | `unityflow hierarchy file.prefab` |
| `inspect` | 상세 조회 | `unityflow inspect file.prefab "Player/Body"` |
| `get` | 값 읽기 | `unityflow get file.prefab "Player/Transform/position"` |
| `set` | 값 쓰기 | `unityflow set file.prefab "Player/Transform/position" "{...}"` |

### 2.1 hierarchy - 구조 탐색

```bash
unityflow hierarchy icon_slot_item.prefab

icon_slot_item
├── board_base [Image, NKIconBase, CanvasGroup]
│   ├── board_addon [LazyPrefabImageBoard]
│   ├── board_Lock (inactive)
│   │   ├── img_dim [Image]
│   │   └── img_lock [Image]
│   └── board_Info
│       ├── lazy_like [LazyPrefabGameObject]
│       └── lazy_bonus [LazyPrefabGameObject]
└── ...

# 옵션
--depth N         # 깊이 제한
--root "path"     # 특정 오브젝트부터
--components      # 컴포넌트 표시 (기본값)
--no-components   # 컴포넌트 숨김
```

**핵심**:
- MonoBehaviour 대신 실제 스크립트 이름 표시
- 비활성 오브젝트 `(inactive)` 표시
- fileID 노출하지 않음

### 2.2 inspect - 상세 조회

```bash
unityflow inspect icon_slot_item.prefab "board_base/board_Info/lazy_like"

GameObject: lazy_like
Path: icon_slot_item/board_base/board_Info/lazy_like
Active: true
Layer: UI

[RectTransform]
  anchoredPosition: (0, 0)
  sizeDelta: (100, 100)
  anchorMin: (0.5, 0.5)
  anchorMax: (0.5, 0.5)

[LazyPrefabGameObject]  # ← 스크립트 이름
  _target: None
  _hasBeenLoaded: false
```

**핵심**:
- Unity Editor Inspector와 유사한 출력
- 이름 기반 경로로 접근
- 스크립트 이름 해석

### 2.3 get/set - 값 읽기/쓰기

```bash
# 읽기
unityflow get file.prefab "lazy_like/RectTransform/anchoredPosition"
# 출력: {"x": 0, "y": 0}

# 쓰기
unityflow set file.prefab "lazy_like/RectTransform/anchoredPosition" '{"x": 10, "y": 20}'
```

**핵심**:
- 전체 계층 경로 지원 (현재는 루트만 작동)
- `query` 명령어와 통합 (별도 명령 불필요)

### 2.4 제거 대상 명령어

| 제거 | 대체 방법 |
|------|-----------|
| `query --path "gameObjects/123..."` | `get "Player/Transform/..."` |
| `export` + 수동 편집 + `import` | `get` + `set` 직접 사용 |
| `find-name` | `hierarchy --root "name"` 또는 `inspect "name"` |

---

## 3. Python API (변경 없음)

prefab-merge-tool에서 사용하는 API는 모두 유지:

```python
# 현재 사용 중 - 변경 없음
from unityflow import (
    UnityYAMLDocument,
    build_hierarchy,
    HierarchyNode,
    ComponentInfo,
    get_lazy_guid_index,
    find_unity_project_root,
    GUIDIndex,
    LazyGUIDIndex,
    get_prefab_instance_for_stripped,
)

from unityflow.merge import three_way_merge
from unityflow.normalizer import UnityPrefabNormalizer
from unityflow.asset_tracker import CachedGUIDIndex, CACHE_DIR_NAME, CACHE_DB_NAME
```

**변경 사항**:
- `build_hierarchy()` 내부에서 자동 배치 해석 (호출 방식 동일)
- `GUIDIndex` 생성 시 패키지 경로 자동 포함 (호출 방식 동일)

---

## 4. 구현 우선순위

| 순위 | 항목 | 영향 | 난이도 | 비고 |
|------|------|------|--------|------|
| 1 | 배치 GUID 해석 | 높음 | 낮음 | API 변경 없음, 내부 최적화 |
| 2 | 패키지 GUID 인덱싱 | 높음 | 중간 | Unity UI 등 해석 가능 |
| 3 | 계층 경로 완전 지원 | 높음 | 중간 | set이 전체 경로 작동 |
| 4 | hierarchy 명령어 | 중간 | 낮음 | 구조 탐색 필수 |
| 5 | inspect 명령어 | 중간 | 낮음 | 상세 조회 |
| 6 | get/set 통합 | 중간 | 낮음 | query 대체 |

---

## 5. 요약

### 사용자 관점 변화

**Before (복잡)**:
```bash
# fileID를 알아야 함
unityflow query file.prefab --path "gameObjects/324666875729751919/components/..."
unityflow export file.prefab -o temp.json
# temp.json 수동 편집
unityflow import temp.json -o file.prefab
```

**After (단순)**:
```bash
# 이름만 알면 됨
unityflow hierarchy file.prefab                    # 구조 확인
unityflow inspect file.prefab "Player/Body"        # 상세 보기
unityflow get file.prefab "Player/Transform/pos"   # 값 읽기
unityflow set file.prefab "Player/Transform/pos" "{...}"  # 값 쓰기
```

### AI 도구 관점

4개 명령어만 기억하면 됨:
1. **구조 모르면** → `hierarchy`
2. **오브젝트 정보 필요** → `inspect`
3. **특정 값 읽기** → `get`
4. **특정 값 변경** → `set`

### 성능 관점

- 프리팹 로드: 1600ms → 80ms
- Unity 패키지 스크립트: unresolved → 100% 해석
