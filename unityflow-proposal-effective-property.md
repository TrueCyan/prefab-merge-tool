# unityflow 개선 제안: Effective Property Value API

## 문제

현재 `HierarchyNode.get_property()`와 `set_property()`가 서로 다른 데이터를 참조합니다:

```python
# PrefabInstance 노드에서
node.set_property("m_LocalPosition.x", 10)  # m_Modifications에 추가
value = node.get_property("m_LocalPosition.x")  # 원본 값 반환 (10이 아님!)
```

Unity 에디터에서는 PrefabInstance가 하나의 오브젝트로 보이고, 수정된 값이 표시됩니다.
하지만 unityflow에서는:
- `get_property()` → 원본 prefab 데이터만 읽음
- `set_property()` → m_Modifications에 추가

이로 인해 사용자가 혼란을 겪을 수 있습니다.

## 제안

### 1. `get_property()`가 effective value 반환

PrefabInstance 노드에서 `get_property()` 호출 시, modifications를 먼저 확인하여 "effective value"를 반환:

```python
def get_property(self, property_path: str) -> Any | None:
    """Get effective property value (considering modifications for PrefabInstance)."""
    # For PrefabInstance, check modifications first
    if self.is_prefab_instance and self.modifications:
        for mod in self.modifications:
            if mod.get("propertyPath") == property_path:
                obj_ref = mod.get("objectReference", {})
                if obj_ref.get("fileID", 0) != 0:
                    return obj_ref
                return mod.get("value")

    # Fall back to original data
    if self._document is None:
        return None

    obj = self._document.get_by_file_id(self.file_id)
    # ... existing logic ...
```

### 2. `ComponentInfo.get_effective_data()` 메서드 추가

컴포넌트 데이터에 modifications가 적용된 버전을 반환:

```python
@dataclass
class ComponentInfo:
    file_id: int
    class_name: str
    data: dict[str, Any]
    script_guid: str | None = None
    script_name: str | None = None
    is_on_stripped_object: bool = False
    _modifications: list[dict] | None = field(default=None, repr=False)

    def get_effective_data(self) -> dict[str, Any]:
        """Return data with modifications applied."""
        if not self._modifications:
            return self.data

        result = copy.deepcopy(self.data)
        for mod in self._modifications:
            _apply_modification(result, mod)
        return result
```

### 3. `HierarchyNode`에 modifications 전달

`load_source_prefab()` 또는 `_merge_nested_node()`에서 nested prefab의 컴포넌트에 해당 modifications를 연결:

```python
def _merge_nested_node(self, source_node, guid_index, loading_prefabs):
    # ... existing code ...

    # Group modifications by target fileID
    mods_by_target = {}
    for mod in self.modifications:
        target_id = mod.get("target", {}).get("fileID", 0)
        if target_id:
            mods_by_target.setdefault(target_id, []).append(mod)

    # Apply modifications to merged components
    merged_components = []
    for comp in source_node.components:
        comp_copy = ComponentInfo(
            file_id=comp.file_id,
            class_name=comp.class_name,
            data=comp.data,
            script_guid=comp.script_guid,
            script_name=comp.script_name,
            _modifications=mods_by_target.get(comp.file_id),
        )
        merged_components.append(comp_copy)

    merged_node = HierarchyNode(
        # ...
        components=merged_components,
        # ...
    )
```

## 대안: 명시적 API 분리

원본 값과 effective 값을 명시적으로 구분하는 API:

```python
class HierarchyNode:
    def get_property(self, path: str) -> Any:
        """Get original property value (ignores modifications)."""
        ...

    def get_effective_property(self, path: str) -> Any:
        """Get effective property value (with modifications applied)."""
        ...

class ComponentInfo:
    @property
    def data(self) -> dict:
        """Original data from source prefab."""
        ...

    @property
    def effective_data(self) -> dict:
        """Data with modifications applied."""
        ...
```

이 방식은 하위 호환성을 유지하면서 새로운 기능을 추가합니다.

## 영향

이 변경으로 prefab-diff-tool 같은 도구에서 workaround 코드를 제거할 수 있습니다:
- `_apply_modifications()` 메서드
- `_set_nested_value()` 메서드
- modifications 그룹화 로직

## 우선순위

높음 - API 일관성과 사용자 경험에 직접적인 영향
