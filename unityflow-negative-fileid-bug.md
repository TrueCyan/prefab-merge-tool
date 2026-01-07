# Bug: Negative fileID not parsed correctly

## 문제 현상

음수 fileID를 가진 Unity YAML 엔트리가 파싱되지 않음

```yaml
# 이 엔트리가 무시됨
--- !u!114 &-3742660215815977075
MonoBehaviour:
  m_GameObject: {fileID: 6986153471733748233}
  m_Script: {fileID: 11500000, guid: f4afdcb1cbadf954ba8b1cf465429e17, type: 3}
```

## 원인

`fast_parser.py`의 정규식 패턴이 음수를 지원하지 않음:

```python
# 현재 패턴
DOCUMENT_HEADER_PATTERN = re.compile(
    r"^--- !u!(\d+) &(\d+)(?: stripped)?$", re.MULTILINE
)
```

`&(\d+)` 부분이 `\d+`(숫자만)로 되어 있어 `-` 부호를 매칭하지 못함

## 수정 방안

```python
# 음수 fileID 지원
DOCUMENT_HEADER_PATTERN = re.compile(
    r"^--- !u!(\d+) &(-?\d+)(?: stripped)?$", re.MULTILINE
)
```

`-?`를 추가하여 선택적으로 마이너스 부호 매칭

## 영향 범위

- Unity는 64-bit signed integer를 fileID로 사용
- 음수 fileID는 Unity에서 정상적으로 생성됨 (특히 prefab에서)
- 해당 컴포넌트가 완전히 누락되어 참조 해석 실패

## 재현 방법

음수 fileID가 포함된 prefab 파일 로드 시 해당 엔트리 누락 확인
