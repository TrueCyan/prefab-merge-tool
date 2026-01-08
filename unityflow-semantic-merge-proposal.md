# Unityflow 시맨틱 Diff/Merge 기능 제안

## 현재 상황 분석

### unityflow의 현재 상태
- **diff 기능**: 없음 (텍스트 diff만 가능)
- **merge 기능**: `merge.py`에 텍스트 라인 기반 구현

### unityflow의 현재 merge.py
- **텍스트 라인 기반** diff3 알고리즘
- `SequenceMatcher`를 사용해 라인 단위 변경 감지
- 충돌 시 `<<<<<<< ours` / `=======` / `>>>>>>> theirs` 마커 삽입

```python
# 현재 방식
def three_way_merge(base: str, ours: str, theirs: str) -> tuple[str, bool]:
    """라인 단위 텍스트 머지"""
    base_lines = base.splitlines()
    ours_lines = ours.splitlines()
    theirs_lines = theirs.splitlines()
    # ... SequenceMatcher로 라인 비교 ...
```

### 문제점
1. **시맨틱 정보 손실**: Unity YAML의 구조적 의미를 무시하고 텍스트로만 처리
2. **불필요한 충돌**: 같은 속성이 다른 라인에 있으면 충돌로 판정
3. **정확한 충돌 위치 파악 불가**: 어떤 GameObject의 어떤 Component의 어떤 속성이 충돌인지 알 수 없음
4. **UI 불일치**: prefab-merge-tool의 시맨틱 충돌 감지와 실제 머지 결과가 다름

---

## 제안 1: 시맨틱 Diff API (2-way 비교)

### PropertyChange 데이터 클래스

```python
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

    # 위치 정보
    game_object_path: str      # "Player/Body/Weapon"
    component_type: str        # "Transform", "MonoBehaviour" 등
    component_file_id: int     # 컴포넌트의 fileID
    property_path: str         # "m_LocalPosition.x"

    # 변경 정보
    change_type: ChangeType
    old_value: Optional[Any]   # left 값 (REMOVED, MODIFIED)
    new_value: Optional[Any]   # right 값 (ADDED, MODIFIED)

    @property
    def full_path(self) -> str:
        return f"{self.game_object_path}.{self.component_type}.{self.property_path}"
```

### SemanticDiffResult 데이터 클래스

```python
@dataclass
class SemanticDiffResult:
    """시맨틱 diff 결과"""

    left_doc: UnityYAMLDocument
    right_doc: UnityYAMLDocument

    # 변경 목록
    changes: list[PropertyChange]

    # 요약
    added_count: int
    removed_count: int
    modified_count: int

    @property
    def total_changes(self) -> int:
        return self.added_count + self.removed_count + self.modified_count

    @property
    def has_changes(self) -> bool:
        return self.total_changes > 0
```

### semantic_diff() 함수

```python
def semantic_diff(
    left_doc: UnityYAMLDocument,
    right_doc: UnityYAMLDocument,
    *,
    ignore_order: bool = True,        # 배열 순서 무시
    flatten_properties: bool = True,  # 중첩 속성 펼치기 (m_LocalPosition.x)
) -> SemanticDiffResult:
    """
    시맨틱 2-way diff 수행

    Args:
        left_doc: 이전 버전 문서
        right_doc: 새 버전 문서
        ignore_order: 배열 순서 변경 무시
        flatten_properties: 중첩 dict를 개별 속성으로 펼침

    Returns:
        SemanticDiffResult: diff 결과
    """
    pass
```

### 사용 예시

```python
from unityflow import UnityYAMLDocument
from unityflow.diff import semantic_diff

# 문서 로드
old_doc = UnityYAMLDocument.load("old_version.prefab")
new_doc = UnityYAMLDocument.load("new_version.prefab")

# 시맨틱 diff 수행
result = semantic_diff(old_doc, new_doc)

print(f"변경사항 {result.total_changes}개:")
print(f"  추가: {result.added_count}")
print(f"  삭제: {result.removed_count}")
print(f"  수정: {result.modified_count}")

for change in result.changes:
    if change.change_type == ChangeType.MODIFIED:
        print(f"  {change.full_path}: {change.old_value} → {change.new_value}")
    elif change.change_type == ChangeType.ADDED:
        print(f"  + {change.full_path}: {change.new_value}")
    elif change.change_type == ChangeType.REMOVED:
        print(f"  - {change.full_path}: {change.old_value}")
```

---

## 제안 2: 시맨틱 Merge API (3-way 비교)

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

### 2. SemanticMergeResult 데이터 클래스

```python
@dataclass
class SemanticMergeResult:
    """시맨틱 머지 결과"""

    # 머지된 문서 (UnityYAMLDocument)
    merged_document: UnityYAMLDocument

    # 충돌 목록
    conflicts: list[PropertyConflict]

    # 자동 머지된 변경사항
    auto_merged: list[PropertyChange]

    # 상태
    has_conflicts: bool
    conflict_count: int

    @property
    def is_clean(self) -> bool:
        return not self.has_conflicts
```

### 3. semantic_three_way_merge() 함수

```python
def semantic_three_way_merge(
    base_doc: UnityYAMLDocument,
    ours_doc: UnityYAMLDocument,
    theirs_doc: UnityYAMLDocument,
    *,
    auto_resolve_identical: bool = True,  # 동일한 변경은 자동 머지
    ignore_order: bool = True,            # 배열 순서 무시 (m_Children 등)
) -> SemanticMergeResult:
    """
    시맨틱 3-way 머지 수행

    Args:
        base_doc: 공통 조상 문서
        ours_doc: 내 변경 문서
        theirs_doc: 상대 변경 문서
        auto_resolve_identical: 양쪽이 같은 값으로 변경했으면 자동 머지
        ignore_order: 배열 순서 변경은 충돌로 처리하지 않음

    Returns:
        SemanticMergeResult: 머지 결과
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
   - `_perform_diff()` → `semantic_diff()` 호출로 대체
   - 반환된 `PropertyChange` 리스트를 UI에 표시

2. **merge_view.py**
   - `_perform_merge()` → `semantic_three_way_merge()` 호출로 대체
   - 반환된 `PropertyConflict` 리스트를 그대로 UI에 표시

3. **writer.py**
   - `write_text_merge()` → `semantic merge` 결과 문서 저장으로 대체
   - `_apply_text_resolutions()` 불필요 (이미 문서에 적용됨)

### 통합 코드 예시

```python
# diff_view.py 수정
def _perform_diff(self) -> None:
    """시맨틱 2-way diff 수행"""
    from unityflow.diff import semantic_diff

    result = semantic_diff(
        self._left_raw_doc,
        self._right_raw_doc,
    )

    # PropertyChange → Change 변환
    self._changes = [
        Change(
            path=c.full_path,
            status=DiffStatus(c.change_type.value),
            left_value=c.old_value,
            right_value=c.new_value,
        )
        for c in result.changes
    ]

    self._diff_result = DiffResult(
        left=self._left_doc,
        right=self._right_doc,
        changes=self._changes,
        summary=DiffSummary(
            added_objects=result.added_count,
            removed_objects=result.removed_count,
            modified_properties=result.modified_count,
        ),
    )
```

```python
# merge_view.py 수정
def _perform_merge(self) -> None:
    """시맨틱 3-way 머지 수행"""
    from unityflow.merge import semantic_three_way_merge

    result = semantic_three_way_merge(
        self._base_raw_doc,
        self._ours_raw_doc,
        self._theirs_raw_doc,
    )

    # PropertyConflict → MergeConflict 변환
    self._conflicts = [
        MergeConflict(
            path=c.full_path,
            base_value=c.base_value,
            ours_value=c.ours_value,
            theirs_value=c.theirs_value,
        )
        for c in result.conflicts
    ]

    # 머지된 문서 저장용으로 보관
    self._merged_doc = result.merged_document

    self._update_conflict_label()
```

---

## 우선순위

### Phase 1: 기본 구현
1. **High**: `PropertyChange`, `PropertyConflict` 데이터 클래스
2. **High**: `semantic_diff()` 기본 구현 (2-way)
3. **High**: `semantic_three_way_merge()` 기본 구현 (3-way)

### Phase 2: 옵션 및 개선
4. **Medium**: 배열 순서 무시 옵션 (`m_Children`, `m_Materials` 등)
5. **Medium**: 속성 펼치기 옵션 (`m_LocalPosition` → `m_LocalPosition.x/y/z`)
6. **Medium**: `apply_resolution()` 함수

### Phase 3: 특수 케이스
7. **Low**: 중첩 프리팹(PrefabInstance) `m_Modifications` 처리
8. **Low**: MonoBehaviour 커스텀 속성 처리
9. **Low**: file_id 불일치 시 fallback 매칭 (type + name)

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
