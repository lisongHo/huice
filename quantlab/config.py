from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class AppPaths(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace_root: Path
    local_state_dir: Path
    lake_root: Path
    registry_path: Path
    runs_root: Path

    @classmethod
    def from_workspace(cls, workspace_root: Path | None = None) -> "AppPaths":
        root = (workspace_root or Path.cwd()).resolve()
        state_dir = root / ".quantlab"
        return cls(
            workspace_root=root,
            local_state_dir=state_dir,
            lake_root=state_dir / "lake",
            registry_path=state_dir / "registry.duckdb",
            runs_root=state_dir / "runs",
        )

