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


def detect_vcs_workspace(p4_client: Optional[str] = None) -> Optional[Path]:
    """
    Detect VCS workspace root from environment variables and commands.

    Tries multiple detection methods in order:
    1. Git environment variables (GIT_WORK_TREE, GIT_DIR)
    2. Git command (git rev-parse --show-toplevel)
    3. Perforce (p4 info, with optional client specification)

    Args:
        p4_client: Perforce client name for accurate multi-client detection

    Returns:
        Path to workspace root, or None if not detected
    """
    # Try Git first (most common)
    workspace = _detect_git_workspace()
    if workspace:
        return workspace

    # Try Perforce
    workspace = _detect_perforce_workspace(client=p4_client)
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


def _detect_perforce_workspace(client: Optional[str] = None) -> Optional[Path]:
    """Detect Perforce workspace root.

    Args:
        client: Specific Perforce client name (from P4V's %P variable).
                If provided, uses 'p4 -c <client> info' for accurate detection.
    """
    # Method 1: P4ROOT environment variable (explicit root, fastest)
    p4root = os.environ.get("P4ROOT")
    if p4root:
        path = Path(p4root)
        if path.is_dir():
            return path

    # Method 2: Run p4 info command
    # If client is specified, use -c flag for accurate multi-client support
    try:
        cmd = ["p4"]
        if client:
            cmd.extend(["-c", client])
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


def detect_unity_project_root(
    file_paths: list[Path],
    p4_client: Optional[str] = None,
) -> Optional[Path]:
    """
    Detect Unity project root using multiple strategies.

    Priority order:
    1. VCS workspace detection (for temp files from difftool/mergetool)
    2. Auto-detect from file paths (for normal files within project)

    Args:
        file_paths: List of file paths being processed
        p4_client: Perforce client name for accurate workspace detection

    Returns:
        Path to Unity project root, or None if not found
    """
    # Priority 1: VCS workspace detection
    vcs_workspace = detect_vcs_workspace(p4_client=p4_client)
    if vcs_workspace:
        # Check if VCS workspace is a Unity project
        assets = vcs_workspace / "Assets"
        if assets.is_dir():
            return vcs_workspace
        # Search for Unity project within VCS workspace
        # (Unity project might be in a subdirectory)
        for subdir in vcs_workspace.iterdir():
            if subdir.is_dir():
                assets = subdir / "Assets"
                project_settings = subdir / "ProjectSettings"
                if assets.is_dir() and project_settings.is_dir():
                    return subdir

    # Priority 2: Auto-detect from file paths
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
