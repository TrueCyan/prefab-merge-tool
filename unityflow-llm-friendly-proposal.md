# Feature Request: LLM-Friendly Prefab API

## 요약

LLM이 Unity prefab 파일을 자연스럽게 이해하고 수정할 수 있도록:
1. Nested prefab 내용 자동 로드
2. GUID → 에셋 이름 해석

## 배경: LLM과 Unity Prefab

LLM에게 prefab 수정 작업을 요청할 때 현재 문제점:

```
사용자: "board_CoreUpgrade 프리팹 안에 있는 버튼 텍스트를 바꿔줘"

LLM이 알아야 하는 것:
1. board_CoreUpgrade가 PrefabInstance임을 인식
2. source_guid로 원본 prefab 파일 위치 찾기
3. 해당 파일 로드해서 내부 구조 파악
4. m_Modifications를 통해 오버라이드 설정

→ 현재는 이 모든 과정을 LLM이 직접 해야 함
```

## 제안 1: Nested Prefab 내용 자동 로드

### 현재 상황

```python
hierarchy = build_hierarchy(doc)

# PrefabInstance 노드
prefab_node = hierarchy.find("board_CoreUpgrade")
print(prefab_node.children)      # [] - 빈 리스트
print(prefab_node.components)    # [] - 빈 리스트
print(prefab_node.source_guid)   # "fd7fb8936b5b8c840881b3f7fa76a782"

# LLM: "내부에 뭐가 있는지 모르겠어요..."
```

### 제안하는 API

```python
# 방법 1: build_hierarchy에 옵션 추가
hierarchy = build_hierarchy(
    doc,
    project_root="/path/to/unity/project",  # GUID 해석에 필요
    load_nested_prefabs=True,               # nested prefab 내용 로드
)

# 이제 PrefabInstance 내부 구조가 보임
prefab_node = hierarchy.find("board_CoreUpgrade")
print(prefab_node.children)      # [<HierarchyNode: Button>, <HierarchyNode: Text>, ...]
print(prefab_node.components)    # [<ComponentInfo: RectTransform>, ...]

# LLM이 자연스럽게 탐색 가능
button = prefab_node.find("Button")
print(button.get_component("Text").data["m_Text"])  # "Click me"
```

```python
# 방법 2: 별도 메서드로 lazy loading
hierarchy = build_hierarchy(doc)
prefab_node = hierarchy.find("board_CoreUpgrade")

# 필요할 때 로드
prefab_node.load_source_prefab(project_root="/path/to/unity/project")
# 또는
hierarchy.load_all_nested_prefabs(project_root="/path/to/unity/project")
```

### 구현 고려사항

```python
# 순환 참조 방지
loading_prefabs: set[str] = set()

def load_nested_content(node: HierarchyNode, project_root: Path) -> None:
    if not node.is_prefab_instance:
        return

    source_path = resolve_guid_to_path(node.source_guid, project_root)
    if str(source_path) in loading_prefabs:
        return  # 순환 참조 스킵

    loading_prefabs.add(str(source_path))
    try:
        nested_doc = UnityYAMLDocument.load(source_path)
        nested_hierarchy = build_hierarchy(nested_doc)
        # nested_hierarchy의 root 내용을 node에 병합
        node.children = nested_hierarchy.root_objects[0].children
        node.components = nested_hierarchy.root_objects[0].components
    finally:
        loading_prefabs.discard(str(source_path))
```

### 데이터 구조 확장

```python
@dataclass
class HierarchyNode:
    # 기존 필드들...

    # Nested prefab 관련 추가
    is_from_nested_prefab: bool = False  # 이 노드가 nested prefab에서 온 것인지
    nested_prefab_loaded: bool = False   # nested prefab 내용이 로드되었는지

    def load_source_prefab(self, project_root: Path) -> None:
        """PrefabInstance의 소스 prefab 내용을 로드"""
        ...
```

## 제안 2: GUID → 에셋 이름 해석

### 현재 상황

```python
# MonoBehaviour 컴포넌트
comp = node.get_component("MonoBehaviour")
print(comp.class_name)  # "MonoBehaviour" - 구체적인 스크립트 이름을 알 수 없음

# m_Script에서 GUID 추출해야 함
script_ref = comp.data.get("m_Script")
# {'fileID': 11500000, 'guid': 'f4afdcb1cbadf954ba8b1cf465429e17', 'type': 3}

# LLM: "이 GUID가 어떤 스크립트인지 모르겠어요..."
```

### 제안하는 API

```python
# GUIDIndex에 이름 해석 기능 추가
guid_index = build_guid_index("/path/to/unity/project")

# GUID → 에셋 이름
name = guid_index.resolve_name("f4afdcb1cbadf954ba8b1cf465429e17")
print(name)  # "PlayerController"

# GUID → 에셋 경로
path = guid_index.resolve_path("f4afdcb1cbadf954ba8b1cf465429e17")
print(path)  # Path("Assets/Scripts/PlayerController.cs")

# ComponentInfo에 해석된 이름 포함
hierarchy = build_hierarchy(doc, guid_index=guid_index)
comp = node.get_component("MonoBehaviour")
print(comp.script_name)  # "PlayerController" - 해석된 이름!
print(comp.script_guid)  # "f4afdcb1cbadf954ba8b1cf465429e17"
```

### 구현 제안

```python
class GUIDIndex:
    def __init__(self, project_root: Path):
        self._guid_to_path: dict[str, Path] = {}
        self._guid_to_name: dict[str, str] = {}
        self._build_index(project_root)

    def _build_index(self, project_root: Path) -> None:
        """프로젝트의 모든 .meta 파일을 스캔하여 인덱스 구축"""
        for meta_path in project_root.rglob("*.meta"):
            guid = self._extract_guid_from_meta(meta_path)
            if guid:
                asset_path = meta_path.with_suffix("")  # .meta 제거
                self._guid_to_path[guid] = asset_path
                self._guid_to_name[guid] = asset_path.stem  # 파일명 (확장자 제외)

    def resolve_name(self, guid: str) -> Optional[str]:
        """GUID를 에셋 이름으로 해석"""
        return self._guid_to_name.get(guid)

    def resolve_path(self, guid: str) -> Optional[Path]:
        """GUID를 에셋 경로로 해석"""
        return self._guid_to_path.get(guid)
```

```python
@dataclass
class ComponentInfo:
    file_id: int
    class_id: int
    class_name: str
    data: dict[str, Any]
    is_on_stripped_object: bool = False

    # 추가 필드
    script_guid: Optional[str] = None   # MonoBehaviour의 스크립트 GUID
    script_name: Optional[str] = None   # 해석된 스크립트 이름
```

## 통합 API 예시

```python
from unityflow import (
    UnityYAMLDocument,
    build_hierarchy,
    build_guid_index,
)

# 1. 프로젝트 인덱스 구축 (한 번만)
guid_index = build_guid_index("/path/to/unity/project")

# 2. Prefab 로드 - 모든 nested prefab과 스크립트 이름 자동 해석
doc = UnityYAMLDocument.load("MyUI.prefab")
hierarchy = build_hierarchy(
    doc,
    guid_index=guid_index,
    load_nested_prefabs=True,
)

# 3. LLM이 자연스럽게 작업 가능
for node in hierarchy.iter_all():
    print(f"{node.name}:")
    for comp in node.components:
        # MonoBehaviour도 구체적인 이름으로 표시
        name = comp.script_name or comp.class_name
        print(f"  - {name}")

    if node.is_prefab_instance:
        # nested prefab 내부도 탐색 가능
        print(f"  (nested prefab with {len(node.children)} children)")
```

## LLM 사용 시나리오

### Before (현재)

```
사용자: "PlayerController 스크립트가 붙은 오브젝트를 찾아줘"

LLM 작업:
1. 모든 MonoBehaviour 컴포넌트 순회
2. m_Script.guid 추출
3. 프로젝트에서 .meta 파일 검색
4. GUID 매칭하여 스크립트 이름 확인
5. "PlayerController"인 것 찾기

→ 복잡하고 오류 가능성 높음
```

### After (제안)

```
사용자: "PlayerController 스크립트가 붙은 오브젝트를 찾아줘"

LLM 작업:
1. hierarchy.iter_all()로 순회
2. comp.script_name == "PlayerController" 확인

→ 단순하고 직관적
```

### Before (현재)

```
사용자: "board_Upgrade 프리팹 안에 있는 Image 컴포넌트 색상을 빨간색으로 바꿔줘"

LLM 작업:
1. board_Upgrade가 PrefabInstance임을 확인
2. source_guid에서 원본 prefab 경로 찾기
3. 원본 prefab 파일 로드
4. 내부 구조 파악
5. Image 컴포넌트 찾기
6. m_Modifications에 색상 오버라이드 추가

→ 매우 복잡
```

### After (제안)

```
사용자: "board_Upgrade 프리팹 안에 있는 Image 컴포넌트 색상을 빨간색으로 바꿔줘"

LLM 작업:
1. hierarchy.find("board_Upgrade") - 내부 구조 이미 로드됨
2. node.get_component("Image") 또는 자식에서 검색
3. 색상 속성 수정

→ 단순하고 직관적
```

## 기대 효과

1. **LLM 작업 효율성 향상**
   - 복잡한 GUID 해석 로직 불필요
   - Nested prefab 탐색이 자연스러움
   - 에러 가능성 감소

2. **코드 간소화**
   - prefab-merge-tool의 GuidResolver, nested prefab 로딩 로직이 불필요해짐
   - 다른 프로젝트에서도 재사용 가능

3. **일관된 API**
   - build_hierarchy() 하나로 완전한 prefab 구조 파악
   - 추가 작업 없이 바로 사용 가능

## 구현 우선순위 제안

1. **Phase 1**: GUIDIndex에 이름 해석 기능 추가
   - 비교적 단순한 구현
   - 즉시 효용성 있음

2. **Phase 2**: build_hierarchy에 nested prefab 로드 옵션 추가
   - 순환 참조 처리 필요
   - project_root 파라미터 추가 필요

3. **Phase 3**: 수정 API (선택적)
   - m_Modifications 자동 관리
   - set_value와의 통합
