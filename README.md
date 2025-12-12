# prefab-diff-tool

Unity 프리팹 파일을 위한 시각적 Diff/Merge 도구

![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

## 개요

Unity YAML 파일(프리팹, 씬, 에셋)의 변경사항을 Unity 에디터처럼 직관적으로 시각화합니다.

- 🟢 **추가** / 🔴 **삭제** / 🟡 **수정** 을 색상으로 구분
- 계층 구조 트리뷰로 GameObject 표시
- Inspector 스타일 속성 비교
- 3-way merge로 Git 충돌 해결

## 설치

### 요구 사항

- Python 3.9 이상
- [prefab-tool](https://github.com/TrueCyan/prefab-tool)

### pip로 설치

```bash
pip install prefab-diff-tool
```

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

### Git 통합

Git difftool/mergetool로 등록:

```bash
# difftool 설정
git config --global difftool.prefab-diff.cmd 'prefab-diff --diff "$LOCAL" "$REMOTE"'
git config --global difftool.prefab-diff.trustExitCode true

# mergetool 설정
git config --global mergetool.prefab-diff.cmd 'prefab-diff --merge "$BASE" "$LOCAL" "$REMOTE" -o "$MERGED"'
git config --global mergetool.prefab-diff.trustExitCode true
```

사용:

```bash
# prefab 파일 diff 보기
git difftool -t prefab-diff -- *.prefab

# 충돌 해결
git mergetool -t prefab-diff
```

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

- [prefab-tool](https://github.com/TrueCyan/prefab-tool) - Unity YAML 파일 정규화 및 병합 CLI
