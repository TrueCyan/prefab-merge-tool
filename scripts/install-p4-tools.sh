#!/bin/bash
# install-p4-tools.sh
# Perforce difftool/mergetool 설정 스크립트
#
# 역할 분리:
# - unityflow: CLI 자동 병합
# - prefab-diff-tool: GUI difftool/mergetool
#
# GUID 추적:
# prefab-diff는 Perforce 환경변수(P4CONFIG, P4ROOT)와 p4 info를
# 자동 감지하여 임시파일에서도 Unity 프로젝트 루트를 찾아 GUID를 해결합니다.

set -e

echo "=== prefab-diff-tool Perforce 통합 설정 ==="
echo
echo "이 스크립트는 Perforce에서 prefab-diff를 사용할 수 있도록 설정합니다:"
echo "  • P4MERGE  - 3-way merge tool"
echo "  • P4DIFF   - 2-way diff tool"
echo
echo "GUID 추적: P4 환경변수를 자동 감지하여 임시파일에서도 동작합니다."
echo

# Check if tools are installed
if ! command -v prefab-diff &> /dev/null; then
    echo "오류: prefab-diff가 설치되어 있지 않습니다."
    echo "먼저 다음 명령으로 설치하세요:"
    echo "  pip install prefab-diff-tool"
    exit 1
fi

# Check if p4 is available
if ! command -v p4 &> /dev/null; then
    echo "경고: p4 명령을 찾을 수 없습니다."
    echo "Perforce 클라이언트가 설치되어 있는지 확인하세요."
fi

# Get the full path to prefab-diff
PREFAB_DIFF_PATH=$(which prefab-diff)

echo "prefab-diff 경로: $PREFAB_DIFF_PATH"
echo

# === P4MERGE 설정 안내 ===
echo "=== P4MERGE 설정 (3-way merge) ==="
echo
echo "Perforce에서 merge tool로 사용하려면 다음 환경변수를 설정하세요:"
echo
echo "  export P4MERGE='$PREFAB_DIFF_PATH --merge \$base \$theirs \$yours -o \$result'"
echo
echo "또는 P4V (Perforce Visual Client) 설정에서:"
echo "  Edit → Preferences → Merge"
echo "  Application: $PREFAB_DIFF_PATH"
echo "  Arguments: --merge %b %t %s -o %r"
echo
echo "파라미터 설명:"
echo "  %b = base (공통 조상)"
echo "  %t = theirs (서버 버전)"
echo "  %s = yours (로컬 버전)"
echo "  %r = result (병합 결과)"
echo

# === P4DIFF 설정 안내 ===
echo "=== P4DIFF 설정 (2-way diff) ==="
echo
echo "Perforce에서 diff tool로 사용하려면 다음 환경변수를 설정하세요:"
echo
echo "  export P4DIFF='$PREFAB_DIFF_PATH --diff \$1 \$2'"
echo
echo "또는 P4V 설정에서:"
echo "  Edit → Preferences → Diff"
echo "  Application: $PREFAB_DIFF_PATH"
echo "  Arguments: --diff %1 %2"
echo

# === GUID 추적 ===
echo "=== GUID 추적 (자동) ==="
echo
echo "prefab-diff는 다음 순서로 Unity 프로젝트를 자동 감지합니다:"
echo "  1. P4ROOT 환경변수"
echo "  2. 'p4 info'의 Client root (P4CLIENT 설정 시)"
echo "  3. .p4config 파일 위치 (선택사항)"
echo
echo "대부분의 경우 Perforce 환경변수가 설정되어 있으면"
echo "추가 설정 없이 GUID 추적이 동작합니다."
echo

# === 파일 타입 설정 ===
echo "=== Unity 파일 타입 설정 (p4 typemap) ==="
echo
echo "Unity YAML 파일을 text로 처리하려면 서버 관리자가 다음을 설정해야 합니다:"
echo
cat << 'TYPEMAP'
p4 typemap 예시:
  text //depot/.../*.prefab
  text //depot/.../*.unity
  text //depot/.../*.asset
  text //depot/.../*.anim
  text //depot/.../*.controller
  text //depot/.../*.mat
  text //depot/.../*.meta
TYPEMAP
echo

# === 자동 설정 옵션 ===
read -p "P4MERGE와 P4DIFF 환경변수를 ~/.bashrc에 추가하시겠습니까? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    BASHRC="$HOME/.bashrc"

    # Backup
    cp "$BASHRC" "$BASHRC.backup.$(date +%Y%m%d%H%M%S)" 2>/dev/null || true

    # Add P4MERGE
    if ! grep -q "P4MERGE=.*prefab-diff" "$BASHRC" 2>/dev/null; then
        echo "" >> "$BASHRC"
        echo "# prefab-diff-tool Perforce integration" >> "$BASHRC"
        echo "export P4MERGE='$PREFAB_DIFF_PATH --merge \"\$base\" \"\$theirs\" \"\$yours\" -o \"\$result\"'" >> "$BASHRC"
        echo "   ✓ P4MERGE 추가됨"
    else
        echo "   ⓘ P4MERGE 이미 설정됨"
    fi

    # Add P4DIFF
    if ! grep -q "P4DIFF=.*prefab-diff" "$BASHRC" 2>/dev/null; then
        echo "export P4DIFF='$PREFAB_DIFF_PATH --diff \"\$1\" \"\$2\"'" >> "$BASHRC"
        echo "   ✓ P4DIFF 추가됨"
    else
        echo "   ⓘ P4DIFF 이미 설정됨"
    fi

    echo
    echo "적용하려면 터미널을 재시작하거나 다음 명령을 실행하세요:"
    echo "  source ~/.bashrc"
fi

echo
echo "=== 설정 완료 ==="
echo
echo "사용 방법:"
echo "  # Perforce에서 파일 diff"
echo "  p4 diff -du path/to/file.prefab"
echo
echo "  # 충돌 해결"
echo "  p4 resolve -am  # 자동 병합 시도"
echo "  p4 resolve -at  # GUI merge tool 사용"
echo
