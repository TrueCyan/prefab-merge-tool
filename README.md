# prefab-diff-tool

Unity 프리팹 파일을 위한 **시각적** Diff/Merge GUI 도구

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

## 개요

Unity YAML 파일(프리팹, 씬, 에셋)의 변경사항을 Unity 에디터처럼 직관적으로 시각화합니다.

**주요 기능:**
- 🎨 **시각적 Diff 뷰어** - 추가/삭제/수정을 색상으로 구분
- 🌳 **계층 구조 트리뷰** - GameObject 구조를 Unity처럼 표시
- 🔀 **3-way Merge UI** - BASE/OURS/THEIRS 동시 비교
- ⚡ **충돌 해결** - 클릭으로 Ours/Theirs 선택

## unityflow와의 관계

| 도구 | 역할 | 유형 |
|------|------|------|
| [unityflow](https://github.com/TrueCyan/unityflow) | 자동 병합, 정규화, Git merge driver | CLI |
| **prefab-diff-tool** | 시각적 diff/merge, 충돌 해결 | GUI |

**함께 사용하면:**
1. `git merge` 시 → `unityflow`가 자동 병합 시도
2. 자동 병합 실패 시 → `git mergetool`로 **prefab-diff-tool** GUI 해결

## 설치

### 요구 사항

- Python 3.9 이상
- [unityflow](https://github.com/TrueCyan/unityflow) (권장)

### 소스에서 설치

```bash
git clone https://github.com/TrueCyan/prefab-diff-tool.git
cd prefab-diff-tool
pip install -e .
```

## 사용법

### GUI 실행

```bash
# 빈 상태로 시작
prefab-diff

# 두 파일 비교
prefab-diff --diff old.prefab new.prefab

# 3-way 병합
prefab-diff --merge base.prefab ours.prefab theirs.prefab -o merged.prefab
```

### Git 설정

```bash
# 1. unityflow merge driver (자동 병합)
git config merge.unity.name "Unity YAML Merge Driver"
git config merge.unity.driver 'unityflow merge %O %A %B -o %A --path %P'

# 2. prefab-diff difftool (GUI diff)
git config difftool.prefab-diff.cmd 'prefab-diff --diff "$LOCAL" "$REMOTE"'

# 3. prefab-diff mergetool (GUI merge)
git config mergetool.prefab-diff.cmd 'prefab-diff --merge "$BASE" "$LOCAL" "$REMOTE" -o "$MERGED"'
```

`.gitattributes` (Unity 프로젝트 루트):

```gitattributes
*.prefab merge=unity
*.unity merge=unity
*.asset merge=unity
```

사용:

```bash
git difftool -t prefab-diff -- *.prefab   # diff
git mergetool -t prefab-diff              # merge
```

### Perforce 설정

**P4V (Edit → Preferences):**

1. **Diff** 탭에서 도구 추가:
   - Name: `prefab-diff`
   - Application: `prefab-diff`
   - Arguments: `--diff %1 %2 -w $r`
   - Extension: `.prefab`, `.unity`, `.asset`

2. **Merge** 탭에서 도구 추가:
   - Name: `prefab-diff`
   - Application: `prefab-diff`
   - Arguments: `--merge %b %t %s -o %r -w $r`
   - Extension: `.prefab`, `.unity`, `.asset`

*`$r`: 워크스페이스 루트 경로*

### GUID 추적

임시파일(difftool/mergetool)에서도 GUID가 해결됩니다:

- **Git**: `GIT_WORK_TREE` 환경변수에서 프로젝트 감지
- **Perforce**: 임시파일 경로에서 프로젝트명 추출 (`.../p4v/.../NIKKE/Assets/...` → NIKKE)

## 스크린샷

(TODO: 스크린샷 추가)

## 단축키

| 단축키 | 동작 |
|--------|------|
| `Ctrl+O` | 파일 열기 |
| `Ctrl+D` | Diff 열기 |
| `Ctrl+M` | Merge 열기 |
| `Ctrl+S` | 저장 (Merge 모드) |
| `N` | 다음 변경사항 |
| `P` | 이전 변경사항 |
| `Ctrl+E` | 모두 펼치기 |
| `Ctrl+Shift+E` | 모두 접기 |

## 개발

```bash
# 개발 환경 설치
pip install -e ".[dev]"

# 테스트 실행
pytest

# 코드 포맷팅
black src/ tests/
ruff check src/ tests/
```

## 라이선스

MIT License

## 관련 프로젝트

- [unityflow](https://github.com/TrueCyan/unityflow) - Unity 워크플로우 자동화 도구 (정규화, 병합, Git 통합)
