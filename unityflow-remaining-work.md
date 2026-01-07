# unityflow 남은 작업

> unityflow 0.3.0 기준

## 1. [중간] Library/PackageCache GUID 인덱싱

### 현재 상태

하드코딩된 GUID로 Unity UI 패키지 해석 중:
```python
PACKAGE_COMPONENT_GUIDS = {
    "Image": "fe87c0e1cc204ed48ad3b37840f39efc",
    "Button": "4e29b1a8efbd4b44bb3f3716e73f07ff",
    # ... 17개 정도
}
```

### 문제점

- Unity 버전 업데이트 시 GUID 변경 가능성 (낮지만 존재)
- 커버되지 않는 Unity 패키지 (Animation, Physics 등)
- 서드파티 패키지 미지원

### 제안

`Library/PackageCache/` 스캔을 **선택적 fallback**으로 추가:

```python
def build_guid_index(project_root: Path, include_packages: bool = True) -> GUIDIndex:
    index = GUIDIndex()

    # 1. Assets (기존)
    index.scan_directory(project_root / "Assets")

    # 2. 로컬 패키지 (기존 - manifest.json file: 참조)
    # ...

    # 3. Library/PackageCache (선택적)
    if include_packages:
        package_cache = project_root / "Library" / "PackageCache"
        if package_cache.exists():
            index.scan_directory(package_cache)

    return index
```

### 우선순위: 중간

- 하드코딩으로 대부분 커버됨
- 하지만 장기적 유지보수와 확장성을 위해 필요

---

## 2. [낮음] CLASS_IDS 확장

### 참조

Unity 공식 Class ID Reference:
https://docs.unity3d.com/6000.3/Documentation/Manual/ClassIDReference.html

### unityflow에 누락된 ID (Unity 6.3 LTS 기준)

```python
{
    50: "Rigidbody2D",
    55: "PhysicsManager",
    150: "PreloadData",
    319: "AvatarMask",
    320: "PlayableDirector",
    328: "VideoPlayer",
    329: "VideoClip",
    331: "SpriteMask",
    363: "OcclusionCullingData",
}
```

### 참고: unityflow CLASS_IDS 오류

ID 156이 `TerrainCollider`로 되어있지만 공식 문서에는 `TerrainData`

### 우선순위: 낮음

- prefab-merge-tool에서 `ADDITIONAL_CLASS_IDS`로 보완 중
- unityflow에 추가하면 다른 사용자도 혜택

---

## 요약

| 항목 | 우선순위 | 상태 | 비고 |
|------|----------|------|------|
| Library/PackageCache 스캔 | 중간 | 미구현 | 장기적 유지보수 필요 |
| CLASS_IDS 검토 및 확장 | 낮음 | 미구현 | Unity 공식 문서 참조 필요 |

---

## 참고: 현재 workaround (prefab-merge-tool)

```python
# loader.py
ADDITIONAL_CLASS_IDS = {
    50: "Rigidbody2D",
    # ... 누락된 ID 보완
    1101: "PrefabInstance",
    1102: "PrefabModification",
}

def resolve_class_name(class_name: str) -> str:
    """Unknown(ID) 형식을 실제 이름으로 변환"""
    match = UNKNOWN_PATTERN.match(class_name)
    if match:
        class_id = int(match.group(1))
        return ADDITIONAL_CLASS_IDS.get(class_id, class_name)
    return class_name
```

이 workaround는 unityflow가 업데이트되면 제거 가능.
