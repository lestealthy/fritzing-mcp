"""Central configuration: resolves paths dynamically, never hard-codes users."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _fritzing_install_default() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / "Fritzing"


class Config:
    def __init__(self) -> None:
        env = os.environ
        self.fritzing_dir = Path(env.get("FRITZING_DIR", str(_fritzing_install_default())))
        self.fritzing_exe = Path(env.get("FRITZING_EXE", str(self.fritzing_dir / "Fritzing.exe")))
        self.parts_dir = Path(env.get("FRITZING_PARTS_DIR", str(self.fritzing_dir / "fritzing-parts")))
        self.parts_db = self.parts_dir / "parts.db"
        self.fzp_checker = self.parts_dir / "fzp_checker.py"

        home = Path(env.get("USERPROFILE") or Path.home())
        self.documents_dir = Path(env.get("FRITZING_DOCUMENTS_DIR", str(home / "Documents" / "Fritzing")))
        self.user_parts_dir = self.documents_dir / "parts"

        self.project_root = PROJECT_ROOT
        self.projects_dir = PROJECT_ROOT / "projects"
        self.projects_active = self.projects_dir / "active"
        self.projects_completed = self.projects_dir / "completed"
        self.projects_rejected = self.projects_dir / "rejected"
        self.parts_cache_dir = PROJECT_ROOT / "parts" / "cache"
        self.policy_file = PROJECT_ROOT / "policy" / "policy.json"
        self.render_profile = PROJECT_ROOT / "cache" / "fritzing_profile"
        self.server_version = "1.0.0"
        self.policy_version = "1.0.0"

    def to_dict(self) -> dict:
        return {
            "fritzing_dir": str(self.fritzing_dir),
            "fritzing_exe": str(self.fritzing_exe),
            "parts_dir": str(self.parts_dir),
            "parts_db": str(self.parts_db),
            "fzp_checker": str(self.fzp_checker),
            "documents_dir": str(self.documents_dir),
            "user_parts_dir": str(self.user_parts_dir),
            "project_root": str(self.project_root),
            "projects_dir": str(self.projects_dir),
        }


config = Config()
