#!/bin/bash
# install-git-tools.sh
# Git difftool/mergetool 설정 스크립트

set -e

TOOL_NAME="prefab-diff"

echo "=== prefab-diff-tool Git 통합 설정 ==="
echo

# Check if prefab-diff is installed
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

# Configure difftool
echo "1. Git difftool 설정..."
git config $GLOBAL difftool.$TOOL_NAME.cmd 'prefab-diff --diff "$LOCAL" "$REMOTE"'
git config $GLOBAL difftool.$TOOL_NAME.trustExitCode true
echo "   ✓ difftool.$TOOL_NAME 설정 완료"

# Configure mergetool
echo "2. Git mergetool 설정..."
git config $GLOBAL mergetool.$TOOL_NAME.cmd 'prefab-diff --merge "$BASE" "$LOCAL" "$REMOTE" -o "$MERGED"'
git config $GLOBAL mergetool.$TOOL_NAME.trustExitCode true
echo "   ✓ mergetool.$TOOL_NAME 설정 완료"

# Optional: Set as default for Unity files
read -p "Unity 파일에 대해 기본 도구로 설정하시겠습니까? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git config $GLOBAL diff.tool $TOOL_NAME
    git config $GLOBAL merge.tool $TOOL_NAME
    echo "   ✓ 기본 diff/merge 도구로 설정됨"
fi

echo
echo "=== 설정 완료 ==="
echo
echo "사용 방법:"
echo "  # prefab 파일 diff 보기"
echo "  git difftool -t $TOOL_NAME -- *.prefab"
echo
echo "  # 충돌 해결"
echo "  git mergetool -t $TOOL_NAME"
echo
echo "  # 또는 기본 도구로 설정한 경우"
echo "  git difftool -- *.prefab"
echo "  git mergetool"
