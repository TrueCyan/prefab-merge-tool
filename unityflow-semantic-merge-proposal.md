# Unityflow Diff/Merge 시맨틱 구현 제안

## 개요

**기존 API를 유지**하면서 **내부 구현만 시맨틱 기반으로 교체**

```python
# 변경 전
def three_way_merge(base, ours, theirs):  # 텍스트 라인 기반

# 변경 후
def three_way_merge(base, ours, theirs):  # 시맨틱 속성 기반 (API 동일)
```

---

## 현재 상황 분석

### unityflow의 현재 상태
- **diff 기능**: 없음
- **merge 기능**: `merge.py`에 텍스트 라인 기반 구현

### 현재 merge.py 문제점
1. **시맨틱 정보 손실**: Unity YAML의 구조적 의미를 무시하고 텍스트로만 처리
2. **불필요한 충돌**: 같은 속성이 다른 라인에 있으면 충돌로 판정
3. **정확한 충돌 위치 파악 불가**: 어떤 GameObject의 어떤 Component의 어떤 속성이 충돌인지 알 수 없음
4. **UI 불일치**: prefab-merge-tool의 시맨틱 충돌 감지와 실제 머지 결과가 다름

---

## 제안 1: diff() 함수 추가 (2-way 비교)

### 데이터 클래스

```python
# unityflow/diff.py

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

class ChangeType(Enum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"

@dataclass
class PropertyChange:
    """속성 레벨 변경 정보"""
    game_object_path: str      # "Player/Body/Weapon"
    component_type: str        # "Transform", "MonoBehaviour" 등
    component_file_id: int     # 컴포넌트의 fileID
    property_path: str         # "m_LocalPosition.x"
    change_type: ChangeType
    old_value: Optional[Any]
    new_value: Optional[Any]

    @property
    def full_path(self) -> str:
        return f"{self.game_object_path}.{self.component_type}.{self.property_path}"

@dataclass
class DiffResult:
    """diff 결과"""
    changes: list[PropertyChange]
    added_count: int
    removed_count: int
    modified_count: int
```

### diff() 함수

```python
def diff(
    left_doc: UnityYAMLDocument,
    right_doc: UnityYAMLDocument,
) -> DiffResult:
    """
    2-way diff (내부적으로 시맨틱 비교)
    """
    pass
```

### 사용 예시

```python
from unityflow import UnityYAMLDocument
from unityflow.diff import diff

old_doc = UnityYAMLDocument.load("old.prefab")
new_doc = UnityYAMLDocument.load("new.prefab")

result = diff(old_doc, new_doc)

for change in result.changes:
    print(f"{change.change_type.value}: {change.full_path}")
```

---

## 제안 2: three_way_merge() 내부 구현 변경 (3-way 비교)

### PropertyConflict 데이터 클래스

```python
from dataclasses import dataclass
from typing import Any, Optional

@dataclass
class PropertyConflict:
    """속성 레벨 충돌 정보"""

    # 위치 정보
    game_object_path: str      # "Player/Body/Weapon"
    component_type: str        # "Transform", "MonoBehaviour" 등
    component_file_id: int     # 컴포넌트의 fileID
    property_path: str         # "m_LocalPosition.x"

    # 값 정보
    base_value: Optional[Any]
    ours_value: Optional[Any]
    theirs_value: Optional[Any]

    # 충돌 유형
    conflict_type: str         # "both_modified", "delete_modify", "both_added"

    @property
    def full_path(self) -> str:
        return f"{self.game_object_path}.{self.component_type}.{self.property_path}"
```

### MergeResult 데이터 클래스

```python
# unityflow/merge.py

@dataclass
class MergeResult:
    """머지 결과"""
    merged_document: UnityYAMLDocument
    conflicts: list[PropertyConflict]
    auto_merged: list[PropertyChange]
    has_conflicts: bool
    conflict_count: int
```

### three_way_merge() 함수 (기존 API 유지, 내부만 변경)

```python
def three_way_merge(
    base_doc: UnityYAMLDocument,
    ours_doc: UnityYAMLDocument,
    theirs_doc: UnityYAMLDocument,
) -> MergeResult:
    """
    3-way 머지 (내부적으로 시맨틱 비교)

    - 기존 텍스트 기반 → 시맨틱 기반으로 교체
    - API 시그니처 유지
    """
    pass
```

---

## 구현 상세

### Phase 1: 객체/컴포넌트 레벨 매칭

```python
def _match_objects(
    base_doc: UnityYAMLDocument,
    ours_doc: UnityYAMLDocument,
    theirs_doc: UnityYAMLDocument
) -> dict[int, tuple[Optional[obj], Optional[obj], Optional[obj]]]:
    """
    fileID 기준으로 세 문서의 객체를 매칭

    Returns:
        {file_id: (base_obj, ours_obj, theirs_obj)}
        None은 해당 문서에 객체가 없음을 의미
    """
    all_ids = set()
    all_ids.update(obj.file_id for obj in base_doc.objects)
    all_ids.update(obj.file_id for obj in ours_doc.objects)
    all_ids.update(obj.file_id for obj in theirs_doc.objects)

    result = {}
    for file_id in all_ids:
        result[file_id] = (
            base_doc.get_by_file_id(file_id),
            ours_doc.get_by_file_id(file_id),
            theirs_doc.get_by_file_id(file_id),
        )
    return result
```

### Phase 2: 속성 레벨 비교

```python
def _compare_properties(
    base_data: dict,
    ours_data: dict,
    theirs_data: dict,
    path_prefix: str = ""
) -> list[PropertyConflict]:
    """
    재귀적으로 속성을 비교하여 충돌 검출

    Unity 속성 특성:
    - m_LocalPosition: {x: 0, y: 0, z: 0} 형태의 중첩 dict
    - m_Children: [{fileID: 123}, {fileID: 456}] 형태의 배열
    - fileID/guid 참조: {fileID: 123, guid: "abc..."} 형태
    """
    conflicts = []

    all_keys = set(base_data.keys()) | set(ours_data.keys()) | set(theirs_data.keys())

    for key in all_keys:
        full_path = f"{path_prefix}.{key}" if path_prefix else key

        base_val = base_data.get(key)
        ours_val = ours_data.get(key)
        theirs_val = theirs_data.get(key)

        # 중첩 dict는 재귀 비교
        if all(isinstance(v, dict) for v in [base_val, ours_val, theirs_val] if v is not None):
            conflicts.extend(_compare_properties(
                base_val or {}, ours_val or {}, theirs_val or {}, full_path
            ))
            continue

        # 값 변경 확인
        ours_changed = ours_val != base_val
        theirs_changed = theirs_val != base_val

        # 양쪽 모두 변경 + 서로 다른 값 = 충돌
        if ours_changed and theirs_changed and ours_val != theirs_val:
            conflicts.append(PropertyConflict(
                property_path=full_path,
                base_value=base_val,
                ours_value=ours_val,
                theirs_value=theirs_val,
                conflict_type="both_modified"
            ))

    return conflicts
```

### Phase 3: 충돌 해결 적용

```python
def apply_resolution(
    merged_doc: UnityYAMLDocument,
    conflict: PropertyConflict,
    resolution: str,  # "ours", "theirs", "base", or custom value
) -> None:
    """
    충돌 해결을 문서에 적용

    Args:
        merged_doc: 수정할 문서
        conflict: 해결할 충돌
        resolution: 해결 방법
    """
    obj = merged_doc.get_by_file_id(conflict.component_file_id)
    if not obj:
        return

    # 해결할 값 결정
    if resolution == "ours":
        value = conflict.ours_value
    elif resolution == "theirs":
        value = conflict.theirs_value
    elif resolution == "base":
        value = conflict.base_value
    else:
        value = resolution  # custom value

    # 속성 경로를 따라 값 설정
    _set_nested_value(obj.data, conflict.property_path, value)
```

---

## 사용 예시

```python
from unityflow import UnityYAMLDocument
from unityflow.semantic_merge import semantic_three_way_merge

# 문서 로드
base_doc = UnityYAMLDocument.load("base.prefab")
ours_doc = UnityYAMLDocument.load("ours.prefab")
theirs_doc = UnityYAMLDocument.load("theirs.prefab")

# 시맨틱 머지 수행
result = semantic_three_way_merge(base_doc, ours_doc, theirs_doc)

if result.has_conflicts:
    print(f"충돌 {result.conflict_count}개 발견:")
    for conflict in result.conflicts:
        print(f"  - {conflict.full_path}")
        print(f"    BASE:   {conflict.base_value}")
        print(f"    OURS:   {conflict.ours_value}")
        print(f"    THEIRS: {conflict.theirs_value}")

    # UI에서 사용자가 해결 선택 후
    for conflict in result.conflicts:
        apply_resolution(result.merged_document, conflict, "ours")

# 저장
result.merged_document.save("merged.prefab")
```

---

## prefab-merge-tool 통합 방안

### 변경이 필요한 파일

1. **diff_view.py**
   - `_perform_diff()` → `unityflow.diff.diff()` 호출로 대체

2. **merge_view.py**
   - `_perform_merge()` → `unityflow.merge.three_way_merge()` 호출로 대체

3. **writer.py**
   - `write_text_merge()` → 머지된 문서 저장으로 대체

### 통합 코드 예시

```python
# diff_view.py
def _perform_diff(self) -> None:
    from unityflow.diff import diff
    result = diff(self._left_raw_doc, self._right_raw_doc)
    self._changes = result.changes
```

```python
# merge_view.py
def _perform_merge(self) -> None:
    from unityflow.merge import three_way_merge
    result = three_way_merge(
        self._base_raw_doc,
        self._ours_raw_doc,
        self._theirs_raw_doc,
    )
    self._conflicts = result.conflicts
    self._merged_doc = result.merged_document
```

---

## 우선순위

### Phase 1: 기본 구현
1. `PropertyChange`, `PropertyConflict` 데이터 클래스
2. `diff()` 구현 (2-way)
3. `three_way_merge()` 내부를 시맨틱으로 교체 (3-way)

### Phase 2: 개선
4. 배열 순서 무시 (`m_Children` 등)
5. `apply_resolution()` 함수

### Phase 3: 특수 케이스
6. PrefabInstance `m_Modifications` 처리
7. file_id 불일치 시 fallback 매칭

---

## 추가 고려사항

### 1. 중첩 프리팹 (PrefabInstance)
- `m_Modifications` 배열의 충돌 처리 필요
- 같은 속성에 대한 modification이 다르면 충돌

### 2. 배열 속성
- `m_Children`: 순서 변경은 충돌 아님, 추가/삭제만 충돌
- `m_Materials`: 인덱스 기반 비교 필요

### 3. 참조 속성
- `{fileID: X, guid: Y}` 형태
- guid만 같으면 동일 참조로 처리
