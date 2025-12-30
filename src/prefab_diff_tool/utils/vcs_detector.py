"""
VCS (Version Control System) workspace detection for Git and Perforce.

When using difftool/mergetool, the actual files are temporary copies outside
the project structure. This module detects the original workspace root from
VCS environment variables, enabling GUID resolution for temp files.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

from prefab_diff_tool.utils.guid_resolver import GuidResolver


def detect_vcs_workspace() -> Optional[Path]:
    """
    Detect VCS workspace root from environment variables and commands.

    Tries multiple detection methods in order:
    1. Git environment variables (GIT_WORK_TREE, GIT_DIR)
    2. Git command (git rev-parse --show-toplevel)
    3. Perforce (p4 info with P4CLIENT env var)

    Returns:
        Path to workspace root, or None if not detected
    """
    # Try Git first
    workspace = _detect_git_workspace()
    if workspace:
        return workspace

    # Try Perforce
    workspace = _detect_perforce_workspace()
    if workspace:
        return workspace

    return None


def _detect_git_workspace() -> Optional[Path]:
    """Detect Git workspace root."""
    # Method 1: GIT_WORK_TREE environment variable (set by git difftool/mergetool)
    git_work_tree = os.environ.get("GIT_WORK_TREE")
    if git_work_tree:
        path = Path(git_work_tree)
        if path.is_dir():
            return path

    # Method 2: GIT_DIR environment variable (derive work tree from .git location)
    git_dir = os.environ.get("GIT_DIR")
    if git_dir:
        git_path = Path(git_dir)
        # If GIT_DIR is ".git", parent is work tree
        if git_path.name == ".git" and git_path.parent.is_dir():
            return git_path.parent
        # If GIT_DIR is absolute path to .git folder
        if git_path.is_dir() and git_path.name == ".git":
            return git_path.parent

    # Method 3: Run git command (works if we're in any git context)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            toplevel = result.stdout.strip()
            if toplevel:
                path = Path(toplevel)
                if path.is_dir():
                    return path
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


def _detect_perforce_workspace() -> Optional[Path]:
    """Detect Perforce workspace root."""
    # Method 1: P4ROOT environment variable
    p4root = os.environ.get("P4ROOT")
    if p4root:
        path = Path(p4root)
        if path.is_dir():
            return path

    # Method 2: Run p4 info command
    # P4V exports P4CLIENT env var when calling external tools
    try:
        cmd = ["p4"]
        p4client = os.environ.get("P4CLIENT")
        if p4client:
            cmd.extend(["-c", p4client])
        cmd.append("info")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # Parse "Client root: /path/to/workspace" line
            for line in result.stdout.splitlines():
                if line.startswith("Client root:"):
                    root_path = line.split(":", 1)[1].strip()
                    if root_path and root_path != "*unknown*":
                        path = Path(root_path)
                        if path.is_dir():
                            return path
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


def _find_unity_in_workspace(workspace: Path) -> Optional[Path]:
    """Find Unity project root within a workspace directory."""
    if not workspace.is_dir():
        return None
    # Check if workspace itself is a Unity project
    if (workspace / "Assets").is_dir():
        return workspace
    # Search for Unity project in subdirectories
    for subdir in workspace.iterdir():
        if subdir.is_dir():
            if (subdir / "Assets").is_dir() and (subdir / "ProjectSettings").is_dir():
                return subdir
    return None


def _find_unity_from_depot_path(
    workspace_root: Path,
    depot_path: str,
) -> Optional[Path]:
    """
    Find Unity project from Perforce depot path.

    Args:
        workspace_root: Workspace root path
        depot_path: Depot path like //depot/ProjectB/Assets/Prefabs/Player.prefab

    Returns:
        Path to Unity project root, or None if not found
    """
    if not depot_path or not workspace_root or not workspace_root.is_dir():
        return None

    # Find "Assets" in depot path and get the path before it
    # Example: //depot/ProjectB/Assets/Prefabs/Player.prefab
    #          -> relative_project = ProjectB
    parts = depot_path.replace("\\", "/").split("/")

    # Find Assets folder index
    try:
        assets_idx = parts.index("Assets")
    except ValueError:
        return None

    # Get path components between depot root and Assets
    # Skip empty parts and depot name (first non-empty parts after //)
    non_empty = [p for p in parts if p]
    try:
        assets_idx = non_empty.index("Assets")
    except ValueError:
        return None

    # Parts before Assets (excluding depot root like "depot")
    # Try progressively shorter paths to find the Unity project
    for start_idx in range(1, assets_idx):
        relative_parts = non_empty[start_idx:assets_idx]
        if relative_parts:
            candidate = workspace_root / Path(*relative_parts)
            if candidate.is_dir() and (candidate / "Assets").is_dir():
                return candidate

    return None


def detect_unity_project_root(
    file_paths: list[Path],
    workspace_root: Optional[Path] = None,
    depot_path: Optional[str] = None,
) -> Optional[Path]:
    """
    Detect Unity project root using multiple strategies.

    Priority order:
    1. Depot path + workspace root (most accurate for Perforce)
    2. Workspace root only (search for Unity project)
    3. VCS workspace detection (for temp files from difftool/mergetool)
    4. Auto-detect from file paths (for normal files within project)

    Args:
        file_paths: List of file paths being processed
        workspace_root: Workspace root path (e.g., from P4V's $r)
        depot_path: Perforce depot path (e.g., from P4V's %f)

    Returns:
        Path to Unity project root, or None if not found
    """
    # Priority 1: Depot path + workspace root
    if workspace_root and depot_path:
        found = _find_unity_from_depot_path(workspace_root, depot_path)
        if found:
            return found

    # Priority 2: Workspace root only
    if workspace_root:
        found = _find_unity_in_workspace(workspace_root)
        if found:
            return found

    # Priority 3: VCS workspace detection
    vcs_workspace = detect_vcs_workspace()
    if vcs_workspace:
        found = _find_unity_in_workspace(vcs_workspace)
        if found:
            return found

    # Priority 4: Auto-detect from file paths
    for file_path in file_paths:
        if file_path and file_path.exists():
            found = GuidResolver.find_project_root(file_path)
            if found:
                return found

    return None


def get_vcs_info() -> dict:
    """
    Get information about detected VCS environment.

    Returns:
        Dictionary with VCS detection info (for debugging)
    """
    info = {
        "git": {
            "GIT_WORK_TREE": os.environ.get("GIT_WORK_TREE"),
            "GIT_DIR": os.environ.get("GIT_DIR"),
            "detected_workspace": None,
        },
        "perforce": {
            "P4ROOT": os.environ.get("P4ROOT"),
            "P4CLIENT": os.environ.get("P4CLIENT"),
            "detected_workspace": None,
        },
    }

    git_ws = _detect_git_workspace()
    if git_ws:
        info["git"]["detected_workspace"] = str(git_ws)

    p4_ws = _detect_perforce_workspace()
    if p4_ws:
        info["perforce"]["detected_workspace"] = str(p4_ws)

    return info
