#!/bin/bash
# install-git-tools.sh
# Git difftool/mergetool 설정 스크립트
#
# 역할 분리:
# - unityflow: CLI 자동 병합, Git merge driver
# - prefab-diff-tool: GUI difftool/mergetool
#
# GUID 추적:
# prefab-diff는 Git 환경변수(GIT_WORK_TREE)를 자동 감지하여
# 임시파일에서도 Unity 프로젝트 루트를 찾아 GUID를 해결합니다.

set -e

echo "=== prefab-diff-tool Git 통합 설정 ==="
echo
echo "이 스크립트는 두 도구를 함께 설정합니다:"
echo "  • unityflow      - CLI 자동 병합 (merge driver)"
echo "  • prefab-diff    - GUI 시각적 diff/merge (difftool/mergetool)"
echo
echo "GUID 추적: Git 환경변수를 자동 감지하여 임시파일에서도 동작합니다."
echo

# Check if tools are installed
if ! command -v unityflow &> /dev/null; then
    echo "오류: unityflow가 설치되어 있지 않습니다."
    echo "먼저 다음 명령으로 설치하세요:"
    echo "  pip install unityflow"
    exit 1
fi

if ! command -v prefab-diff &> /dev/null; then
    echo "오류: prefab-diff가 설치되어 있지 않습니다."
    echo "먼저 다음 명령으로 설치하세요:"
    echo "  pip install prefab-diff-tool"
    exit 1
fi

# Parse arguments
GLOBAL=""
if [[ "$1" == "--global" ]]; then
    GLOBAL="--global"
    echo "글로벌 설정으로 진행합니다."
else
    echo "로컬 저장소 설정으로 진행합니다."
    echo "(글로벌 설정은 --global 옵션 사용)"
fi
echo

# === 1. unityflow merge driver 설정 ===
echo "1. Git merge driver 설정 (unityflow)..."
git config $GLOBAL merge.unity.name "Unity YAML Merge Driver"
git config $GLOBAL merge.unity.driver 'unityflow merge %O %A %B -o %A --path %P'
echo "   ✓ merge.unity driver 설정 완료"

# === 2. prefab-diff difftool 설정 ===
echo "2. Git difftool 설정 (prefab-diff)..."
git config $GLOBAL difftool.prefab-diff.cmd 'prefab-diff --diff "$LOCAL" "$REMOTE"'
git config $GLOBAL difftool.prefab-diff.trustExitCode true
echo "   ✓ difftool.prefab-diff 설정 완료"

# === 3. prefab-diff mergetool 설정 ===
echo "3. Git mergetool 설정 (prefab-diff)..."
git config $GLOBAL mergetool.prefab-diff.cmd 'prefab-diff --merge "$BASE" "$LOCAL" "$REMOTE" -o "$MERGED"'
git config $GLOBAL mergetool.prefab-diff.trustExitCode true
echo "   ✓ mergetool.prefab-diff 설정 완료"

# === 4. .gitattributes 안내 ===
echo
echo "=== .gitattributes 설정 ==="
echo
echo "Unity 프로젝트 루트의 .gitattributes에 다음을 추가하세요:"
echo
cat << 'GITATTR'
# Unity 파일 자동 병합 (unityflow)
*.prefab merge=unity
*.unity merge=unity
*.asset merge=unity
*.anim merge=unity
*.controller merge=unity
*.mat merge=unity
GITATTR
echo

# Optional: Set defaults
read -p "prefab-diff를 기본 difftool/mergetool로 설정하시겠습니까? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git config $GLOBAL diff.tool prefab-diff
    git config $GLOBAL merge.tool prefab-diff
    echo "   ✓ 기본 difftool/mergetool로 설정됨"
fi

echo
echo "=== 설정 완료 ==="
echo
echo "작동 방식:"
echo "  1. git merge 시 충돌 발생 → unityflow가 자동 병합 시도"
echo "  2. 자동 병합 실패 시 → git mergetool로 GUI 해결"
echo
echo "사용 방법:"
echo "  # prefab 파일 diff 보기 (GUI)"
echo "  git difftool -t prefab-diff -- *.prefab"
echo
echo "  # 충돌 해결 (GUI)"
echo "  git mergetool -t prefab-diff"
echo
echo "  # 또는 기본 도구로 설정한 경우"
echo "  git difftool -- *.prefab"
echo "  git mergetool"
echo
