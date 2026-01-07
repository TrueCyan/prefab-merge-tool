# unityflow 개선 제안서

> **상태**: unityflow 0.3.0에서 대부분 구현 완료

## 핵심 원칙

1. **단순함 우선**: AI 도구가 명령어 목록만 보고 올바른 명령을 선택할 수 있어야 함
2. **이름 기반 작업**: fileID, GUID 같은 내부 구현을 숨기고 Unity Editor처럼 이름/경로로 작업
3. **내부 최적화**: API 변경 없이 성능 개선

---

## 1. 내부 최적화 (API 변경 없음)

### 1.1 배치 GUID 해석 ✅ 구현됨

**문제**: `build_hierarchy(guid_index=...)` 호출 시 MonoBehaviour마다 개별 SQLite 쿼리
- N개 컴포넌트 → N개 쿼리 → 1200ms+

**해결** (unityflow 0.3.0):
- `build_hierarchy()` 내부에서 자동 배치 처리
- `LazyGUIDIndex.batch_resolve_names()` - SQL IN 쿼리 사용
- `GUIDIndex.batch_resolve_names()` - 딕셔너리 룩업

**효과**: 1600ms → 80ms (20배 개선)

### 1.2 패키지 GUID 인덱싱 확장 ✅ 부분 구현

**현재 인덱싱 범위**: `Assets/` 폴더 + `manifest.json` file: 참조

**미인덱싱으로 인한 unresolved**:

| 소스 | 예시 | 상태 |
|------|------|------|
| Unity 패키지 | Image, Button, VerticalLayoutGroup | ⚠️ `Library/PackageCache/` 미구현 |
| 로컬 패키지 | CommentaryComponent (MyBox) | ✅ file: 참조 구현됨 |

**남은 작업**: `Library/PackageCache/` 인덱싱 추가

```python
# 추가 필요
package_cache = project_root / "Library" / "PackageCache"
if package_cache.exists():
    index.scan_directory(package_cache)
```

**해결되면 추가로 해석 가능한 목록**:

| GUID | 컴포넌트 | 패키지 |
|------|----------|--------|
| `59f8146938fff824cb5fd77236b75775` | VerticalLayoutGroup | Unity UI |
| `fe87c0e1cc204ed48ad3b37840f39efc` | Image | Unity UI |
| `306cc8c2b49d7114eaa3623786fc2126` | LayoutElement | Unity UI |
| `4e29b1a8efbd4b44bb3f3716e73f07ff` | Button | Unity UI |
| `30649d3a9faa99c48a7b1166b86bf2a0` | HorizontalLayoutGroup | Unity UI |
| `3245ec927659c4140ac4f8d17403cc18` | ContentSizeFitter | Unity UI |

---

## 2. CLI 단순화 ✅ 구현됨

### 변경 사항 (unityflow 0.3.0)

- 20개 명령어 제거, 10개 핵심 명령어 유지
- CLI 코드 ~5,000줄 감소

### 핵심 명령어

| 명령어 | 용도 | 상태 |
|--------|------|------|
| `hierarchy` | 구조 탐색 (트리 형식) | ✅ 구현됨 |
| `inspect` | 오브젝트/컴포넌트 상세 조회 | ✅ 구현됨 |
| `get` | 이름 기반 경로 쿼리 | ✅ 구현됨 |
| `set` | 값 쓰기 | ✅ 구현됨 |
| `normalize` | 정규화 | ✅ 유지 |
| `diff` | 비교 | ✅ 유지 |
| `validate` | 검증 | ✅ 유지 |
| `merge` | 병합 | ✅ 유지 |
| `git-textconv` | Git 통합 | ✅ 유지 |
| `setup` | 설정 | ✅ 유지 |

### 사용 예시

```bash
# 구조 탐색
unityflow hierarchy icon_slot_item.prefab

# 상세 조회
unityflow inspect icon_slot_item.prefab "board_base/board_Info/lazy_like"

# 값 읽기
unityflow get file.prefab "lazy_like/RectTransform/anchoredPosition"

# 값 쓰기
unityflow set file.prefab "lazy_like/RectTransform/anchoredPosition" '{"x": 10, "y": 20}'
```

---

## 3. Python API (변경 없음) ✅ 호환성 유지

prefab-merge-tool에서 사용하는 API 모두 유지:

```python
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

**추가된 API**:
- `LazyGUIDIndex.batch_resolve_names(guids: set[str]) -> dict[str, str]`
- `GUIDIndex.batch_resolve_names(guids: set[str]) -> dict[str, str]`

---

## 4. 구현 상태 요약

| 항목 | 상태 | 비고 |
|------|------|------|
| 배치 GUID 해석 | ✅ 완료 | `batch_resolve_names()` |
| 로컬 패키지 인덱싱 | ✅ 완료 | manifest.json file: 참조 |
| Unity 패키지 인덱싱 | ⚠️ 미구현 | `Library/PackageCache/` 필요 |
| CLI 단순화 | ✅ 완료 | 20개 → 10개 명령어 |
| hierarchy 명령어 | ✅ 완료 | 트리 형식 출력 |
| inspect 명령어 | ✅ 완료 | 상세 조회 |
| get 명령어 | ✅ 완료 | 이름 기반 경로 |
| set 명령어 | ✅ 완료 | 값 쓰기 |

---

## 5. 남은 작업

### 5.1 Unity 패키지 GUID 인덱싱

`Library/PackageCache/` 폴더 인덱싱 추가 필요:
- Image, Button, LayoutGroup 등 Unity UI 컴포넌트 해석
- 우선순위: 중간 (대부분의 프로젝트에서 Unity 패키지 사용)

### 5.2 .meta 자동 생성

에셋 참조에 대응하는 .meta 파일이 없을 때 자동 생성:
- 상태: ✅ 구현됨 (changelog에 언급)
