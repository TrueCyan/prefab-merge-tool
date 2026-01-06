"""
Entry point for prefab-diff-tool.

Usage:
    prefab-diff [FILE]                          # View single file
    prefab-diff --diff FILE1 FILE2              # Compare two files
    prefab-diff --merge BASE OURS THEIRS -o OUT # 3-way merge
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Redirect stdout/stderr on Windows GUI to prevent console window flash
# This must be done BEFORE any imports that might write to stdout/stderr
if sys.platform == "win32" and getattr(sys, 'frozen', False):
    # Running as frozen EXE on Windows - redirect to devnull
    try:
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
    except Exception:
        pass

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
        "--workspace-root", "-w",
        type=Path,
        help="VCS workspace root for GUID resolution (P4V: $r)",
    )

    parser.add_argument(
        "--depot-path",
        type=str,
        help="Perforce depot path for Unity project detection (P4V: %%f)",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug info (detected paths) to stderr",
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

    # Setup logging early so detection logs are captured
    from prefab_diff_tool.utils.log_handler import setup_logging
    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)

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
    # 1. Explicit workspace root (--workspace-root)
    # 2. VCS workspace detection (Git/Perforce) - for temp files
    # 3. Auto-detect from file paths
    from prefab_diff_tool.utils.vcs_detector import detect_unity_project_root

    logger.debug(f"CLI --workspace-root: {args.workspace_root}")
    logger.debug(f"CLI --depot-path: {args.depot_path}")
    logger.debug(f"CLI files: {files}")

    unity_root = detect_unity_project_root(
        files,
        workspace_root=args.workspace_root,
        depot_path=args.depot_path,
    )

    logger.info(f"Detected unity_root: {unity_root}")

    if args.debug:
        print(f"[DEBUG] --workspace-root: {args.workspace_root}", file=sys.stderr)
        print(f"[DEBUG] --depot-path: {args.depot_path}", file=sys.stderr)
        print(f"[DEBUG] detected unity_root: {unity_root}", file=sys.stderr)
        print(f"[DEBUG] input files: {files}", file=sys.stderr)

    # Start GUI
    from prefab_diff_tool.app import run_app

    return run_app(
        mode=mode,
        files=files,
        output=args.output,
        unity_root=unity_root,
        workspace_root=args.workspace_root,
        depot_path=args.depot_path,
    )


if __name__ == "__main__":
    sys.exit(main())
