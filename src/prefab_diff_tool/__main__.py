"""
Entry point for prefab-diff-tool.

Usage:
    prefab-diff [FILE]                          # View single file
    prefab-diff --diff FILE1 FILE2              # Compare two files
    prefab-diff --merge BASE OURS THEIRS -o OUT # 3-way merge
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from prefab_diff_tool import __version__


def find_p4_workspace_root() -> Path | None:
    """
    Find Unity project root from current Perforce workspace.

    Uses `p4 info` to get client root, then searches for Unity project structure.
    """
    try:
        result = subprocess.run(
            ["p4", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None

        # Parse "Client root: /path/to/workspace"
        for line in result.stdout.splitlines():
            if line.startswith("Client root:"):
                client_root = Path(line.split(":", 1)[1].strip())
                if client_root.exists():
                    # Search for Unity project in client root
                    return find_unity_project_in_path(client_root)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def find_unity_project_in_path(root: Path) -> Path | None:
    """
    Find Unity project root within a directory.

    Searches up to 3 levels deep for Assets + ProjectSettings folders.
    """
    # Check if root itself is a Unity project
    if (root / "Assets").is_dir() and (root / "ProjectSettings").is_dir():
        return root

    # Search subdirectories (common patterns: root/ProjectName, root/Unity, etc.)
    search_patterns = ["*", "*/*", "*/*/*"]
    for pattern in search_patterns:
        for path in root.glob(pattern):
            if path.is_dir():
                assets = path / "Assets"
                project_settings = path / "ProjectSettings"
                if assets.is_dir() and project_settings.is_dir():
                    return path
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="prefab-diff",
        description="Visual diff and merge tool for Unity prefab files",
    )
    
    parser.add_argument(
        "file",
        nargs="?",
        type=Path,
        help="Unity file to view (prefab, unity, asset)",
    )
    
    parser.add_argument(
        "--diff", "-d",
        nargs=2,
        type=Path,
        metavar=("LEFT", "RIGHT"),
        help="Compare two files",
    )
    
    parser.add_argument(
        "--merge", "-m",
        nargs=3,
        type=Path,
        metavar=("BASE", "OURS", "THEIRS"),
        help="3-way merge",
    )
    
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output file for merge result",
    )

    parser.add_argument(
        "--unity-root", "-u",
        type=Path,
        help="Unity project root path (folder containing Assets/). "
             "Auto-detection order: 1) this argument, 2) UNITY_PROJECT_ROOT env var, "
             "3) P4 workspace root, 4) file location.",
    )

    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    
    return parser.parse_args()


def validate_files(paths: list[Path]) -> bool:
    """Validate that all files exist and are Unity files."""
    valid_extensions = {
        ".prefab", ".unity", ".asset", ".anim", ".controller",
        ".mat", ".physicMaterial", ".mixer", ".preset",
    }
    
    for path in paths:
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            return False
        if path.suffix.lower() not in valid_extensions:
            print(f"Warning: Unknown file type: {path.suffix}", file=sys.stderr)
    
    return True


def main() -> int:
    args = parse_args()
    
    # Determine mode
    if args.merge:
        mode = "merge"
        files = args.merge
        if not args.output:
            print("Error: --output is required for merge mode", file=sys.stderr)
            return 1
    elif args.diff:
        mode = "diff"
        files = args.diff
    elif args.file:
        mode = "view"
        files = [args.file]
    else:
        mode = "empty"
        files = []
    
    # Validate files
    if files and not validate_files(files):
        return 1

    # Get unity root from argument, environment variable, or auto-detect from P4
    unity_root = args.unity_root
    if not unity_root:
        env_root = os.environ.get("UNITY_PROJECT_ROOT")
        if env_root:
            unity_root = Path(env_root)

    # Try to auto-detect from Perforce workspace if still not found
    if not unity_root:
        unity_root = find_p4_workspace_root()
        if unity_root:
            print(f"Auto-detected Unity project from P4 workspace: {unity_root}", file=sys.stderr)

    # Validate unity root if provided
    if unity_root:
        if not unity_root.exists():
            print(f"Error: Unity root path not found: {unity_root}", file=sys.stderr)
            return 1
        assets_path = unity_root / "Assets"
        if not assets_path.is_dir():
            print(f"Error: Invalid Unity project (no Assets folder): {unity_root}", file=sys.stderr)
            return 1

    # Start GUI
    from prefab_diff_tool.app import run_app

    return run_app(
        mode=mode,
        files=files,
        output=args.output,
        unity_root=unity_root,
    )


if __name__ == "__main__":
    sys.exit(main())
