# unityflow 개선 제안: get_property/set_property 일관성

## 문제

현재 `HierarchyNode.get_property()`와 `set_property()`가 서로 다른 데이터를 참조합니다:

```python
# PrefabInstance 노드에서
node.set_property("m_LocalPosition.x", 10)  # m_Modifications에 추가
value = node.get_property("m_LocalPosition.x")  # 원본 값 반환 (10이 아님!)
```

Unity 에디터에서는 PrefabInstance가 하나의 오브젝트로 보이고 수정된 값이 표시되지만,
unityflow에서는 get/set이 다른 데이터를 참조해서 혼란을 줍니다.

## 제안

### 1. `get_property()`가 effective value 반환

```python
def get_property(self, property_path: str) -> Any | None:
    """Get property value. For PrefabInstance, returns modified value if exists."""
    # PrefabInstance면 modifications 먼저 확인
    if self.is_prefab_instance and self.modifications:
        for mod in self.modifications:
            if mod.get("propertyPath") == property_path:
                obj_ref = mod.get("objectReference", {})
                if obj_ref.get("fileID", 0) != 0:
                    return obj_ref
                return mod.get("value")

    # 원본 데이터에서 조회
    # ... existing logic ...
```

### 2. `ComponentInfo`에 modifications 연결

`_merge_nested_node()`에서 컴포넌트에 해당 modifications 전달:

```python
@dataclass
class ComponentInfo:
    file_id: int
    class_name: str
    data: dict[str, Any]
    script_guid: str | None = None
    script_name: str | None = None
    is_on_stripped_object: bool = False
    modifications: list[dict] | None = None  # 추가

    @property
    def effective_data(self) -> dict[str, Any]:
        """Return data with modifications applied."""
        if not self.modifications:
            return self.data

        result = copy.deepcopy(self.data)
        for mod in self.modifications:
            _apply_property_path(result, mod["propertyPath"], mod.get("value"), mod.get("objectReference"))
        return result
```

### 3. `_merge_nested_node()` 수정

```python
def _merge_nested_node(self, source_node, guid_index, loading_prefabs):
    # modifications를 target fileID별로 그룹화
    mods_by_target = {}
    for mod in self.modifications:
        target_id = mod.get("target", {}).get("fileID", 0)
        if target_id:
            mods_by_target.setdefault(target_id, []).append(mod)

    # 컴포넌트에 modifications 연결
    merged_components = []
    for comp in source_node.components:
        merged_components.append(ComponentInfo(
            file_id=comp.file_id,
            class_name=comp.class_name,
            data=comp.data,
            script_guid=comp.script_guid,
            script_name=comp.script_name,
            modifications=mods_by_target.get(comp.file_id),
        ))

    merged_node = HierarchyNode(
        # ...
        components=merged_components,
        # ...
    )
```

## 기대 효과

1. **API 일관성**: get/set이 같은 데이터를 참조
2. **Unity 에디터와 동일한 동작**: effective value 표시
3. **소비자 코드 단순화**: prefab-diff-tool 등에서 workaround 불필요

## 우선순위

높음 - API 일관성 문제
