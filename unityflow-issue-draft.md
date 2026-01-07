# Feature Request: High-level Hierarchy API for Prefabs

## Summary

Unity의 Nested Prefab 구조(stripped objects, PrefabInstance 관계)를 추상화하여 사용자가 내부 구현을 몰라도 자연스럽게 사용할 수 있는 고수준 API 제안

## 현재 문제점

### 1. Nested Prefab 읽기가 어려움

Unity는 nested prefab을 다음과 같은 구조로 저장:

```yaml
# PrefabInstance - 중첩된 프리팹 참조
--- !u!1001 &7876467245726119373
PrefabInstance:
  m_Modification:
    m_TransformParent: {fileID: 9016256669134947108}
    m_Modifications: [...]
  m_SourcePrefab: {fileID: 100100000, guid: a0bd5a356d4dbf94f80d1eb788a92ca0}

# Stripped Transform - 프리팹 내부 Transform 참조
--- !u!224 &603920067861314518 stripped
RectTransform:
  m_CorrespondingSourceObject: {fileID: 7291146517268352539, guid: a0bd5a356d4dbf94f80d1eb788a92ca0}
  m_PrefabInstance: {fileID: 7876467245726119373}

# Stripped GameObject - 프리팹 내부 오브젝트 참조
--- !u!1 &1160427460518271161 stripped
GameObject:
  m_CorrespondingSourceObject: {fileID: 9030983452208262516, guid: a0bd5a356d4dbf94f80d1eb788a92ca0}
  m_PrefabInstance: {fileID: 7876467245726119373}

# 이 stripped GO에 추가된 컴포넌트
--- !u!222 &2745004045164926116
CanvasRenderer:
  m_GameObject: {fileID: 1160427460518271161}  # stripped GO 참조!
```

**문제:** 사용자가 이 구조를 이해하고 직접 처리해야 함:
- stripped 객체가 어떤 PrefabInstance에 속하는지 추적
- 컴포넌트의 m_GameObject가 stripped GO를 참조하면 PrefabInstance로 리다이렉트
- Transform의 m_Father/m_Children으로 계층 구조 재구성

### 2. Nested Prefab 생성도 어려움

프리팹에 다른 프리팹을 추가하려면:
1. PrefabInstance 엔트리 생성
2. stripped Transform 엔트리 생성
3. stripped GameObject 엔트리 생성 (필요시)
4. m_Modification에 속성 오버라이드 설정
5. 부모 Transform의 m_Children에 stripped Transform 추가

현재 unityflow는 이를 위한 헬퍼가 없음

## 제안하는 API

### 1. 계층 구조 읽기

```python
doc = UnityYAMLDocument.load("file.prefab")

# 방법 1: 해석된 계층 구조 반환
hierarchy = doc.build_hierarchy()
for go in hierarchy.root_objects:
    print(go.name)
    print(go.components)  # stripped GO의 컴포넌트도 포함
    for child in go.children:
        if child.is_prefab_instance:
            print(f"Nested prefab: {child.source_guid}")

# 방법 2: 레퍼런스 자동 해석
component = doc.get_by_file_id("2745004045164926116")
go = doc.resolve_game_object(component)  # stripped GO면 PrefabInstance 반환
```

### 2. Nested Prefab 추가

```python
doc = UnityYAMLDocument.load("file.prefab")
hierarchy = doc.build_hierarchy()

# 고수준 API - stripped 객체 자동 생성
prefab_instance = hierarchy.add_prefab_instance(
    parent=some_game_object,
    source_guid="a0bd5a356d4dbf94f80d1eb788a92ca0",
    name="MyNestedPrefab",  # m_Modifications에 자동 추가
    position=(0, 0, 0),
)

# 저장 시 stripped 객체들 자동 생성
doc.save("file.prefab")
```

### 3. 레퍼런스 해석 유틸리티

```python
# stripped 객체 → PrefabInstance 매핑
doc.get_prefab_instance_for(stripped_file_id)

# PrefabInstance → 소속 stripped 객체들
doc.get_stripped_objects_for(prefab_instance_id)

# 컴포넌트가 실제로 속한 GameObject (stripped 해석 포함)
doc.resolve_game_object_for_component(component)
```

## 구현 참고

[prefab-merge-tool의 loader.py](https://github.com/TrueCyan/prefab-merge-tool)에서 이미 구현한 로직:

- `_stripped_transforms`: Transform fileID → PrefabInstance fileID 매핑
- `_stripped_game_objects`: GameObject fileID → PrefabInstance fileID 매핑
- `_build_hierarchy()`: Transform m_Father/m_Children 기반 계층 구조 빌드
- 컴포넌트 연결 시 stripped GO를 PrefabInstance로 리다이렉트

## 기대 효과

1. **사용자 경험 향상**: Unity 내부 구조를 몰라도 자연스럽게 사용 가능
2. **LLM 친화적**: AI가 prefab 수정 작업을 더 쉽게 수행 가능
3. **버그 감소**: stripped 객체 처리 실수 방지
