"""
Entry point for prefab-diff-tool.

Usage:
    prefab-diff [FILE]                          # View single file
    prefab-diff --diff FILE1 FILE2              # Compare two files
    prefab-diff --merge BASE OURS THEIRS -o OUT # 3-way merge
"""

import argparse
import sys
from pathlib import Path

from prefab_diff_tool import __version__


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

    # Detect Unity project root:
    # 1. VCS workspace detection (Git/Perforce) - for temp files
    # 2. Auto-detect from file paths
    from prefab_diff_tool.utils.vcs_detector import detect_unity_project_root

    unity_root = detect_unity_project_root(files)

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
