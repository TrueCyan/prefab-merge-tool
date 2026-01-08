# unityflow 개선 제안: Children 정렬 순서

## 문제

현재 `HierarchyNode.children`이 Unity Editor와 다른 순서로 정렬됩니다.

Unity에서 자식 순서는 Transform의 `m_Children` 배열 순서로 결정되는데, unityflow는 이를 무시하고 문서 순회 순서대로 children을 추가합니다:

```python
# hierarchy.py line 1134
parent_node.children.append(node)  # 순서 고려 없이 단순 append
```

## 현재 동작

```
Unity Editor 순서:     unityflow 순서:
- Canvas               - Canvas
  - Header               - Footer      (잘못된 순서)
  - Content              - Header
  - Footer               - Content
```

## 제안

`_link_hierarchy()` 에서 parent-child 관계 설정 후, `m_Children` 순서에 따라 정렬:

```python
def _link_hierarchy(self, doc: UnityYAMLDocument) -> None:
    # ... existing parent-child linking code ...

    # Sort children based on Transform's m_Children order
    for node in self._nodes_by_file_id.values():
        if node.children and node.transform_id:
            transform_obj = doc.get_by_file_id(node.transform_id)
            if transform_obj:
                content = transform_obj.get_content() or {}
                m_children = content.get("m_Children", [])

                if m_children:
                    # Build order map
                    order_map = {}
                    for idx, child_ref in enumerate(m_children):
                        if isinstance(child_ref, dict):
                            child_id = child_ref.get("fileID", 0)
                            if child_id:
                                order_map[child_id] = idx

                    # Sort children
                    node.children.sort(
                        key=lambda c: order_map.get(c.transform_id, len(m_children))
                    )

    # Also sort root_objects if needed
    # ...
```

## 영향

- Unity Editor와 동일한 계층 구조 순서 표시
- prefab-diff-tool 등 도구에서 workaround 코드 제거 가능

## 우선순위

중간 - UI/UX 일관성 문제
