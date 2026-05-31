"""Backup and restore helpers for managed Nginx config files."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from loguru import logger

from nam.models import ManagerConfig
from nam.utils.validators import safe_domain_filename


@dataclass(frozen=True)
class BackupRecord:
    """A file backup plus sidecar metadata."""

    backup_path: Path
    metadata_path: Path
    original_path: Path
    created_at: str
    reason: str


class BackupService:
    """Create and restore backups under the configured backup directory."""

    def __init__(self, config: ManagerConfig) -> None:
        self.config = config

    def backup_file(self, path: Path, *, reason: str = "pre-change") -> BackupRecord | None:
        """Back up a file if it exists. Returns ``None`` for absent paths."""
        if not path.exists() and not path.is_symlink():
            return None

        self.config.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        clean_reason = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in reason)
        backup_path = self.config.backup_dir / f"{path.name}.{timestamp}.{clean_reason}.bak"
        metadata_path = backup_path.with_suffix(backup_path.suffix + ".yaml")

        backup_type = "symlink" if path.is_symlink() else "file"
        if path.is_symlink():
            backup_path.write_text(str(path.readlink()), encoding="utf-8")
        else:
            shutil.copy2(path, backup_path)

        created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        metadata = {
            "original_path": str(path),
            "backup_path": str(backup_path),
            "created_at": created_at,
            "reason": reason,
            "backup_type": backup_type,
        }
        metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
        logger.info("Backed up {} to {}", path, backup_path)
        return BackupRecord(
            backup_path=backup_path,
            metadata_path=metadata_path,
            original_path=path,
            created_at=created_at,
            reason=reason,
        )

    def latest_backup(self, *, domain: str | None = None) -> BackupRecord | None:
        """Return the newest backup, optionally limited to one domain config filename."""
        if not self.config.backup_dir.exists():
            return None
        prefix = safe_domain_filename(domain) if domain else ""
        candidates = sorted(self.config.backup_dir.glob(f"{prefix}*.bak"), reverse=True)
        for backup_path in candidates:
            metadata_path = backup_path.with_suffix(backup_path.suffix + ".yaml")
            if not metadata_path.exists():
                continue
            metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
            return BackupRecord(
                backup_path=backup_path,
                metadata_path=metadata_path,
                original_path=Path(metadata["original_path"]),
                created_at=str(metadata.get("created_at", "")),
                reason=str(metadata.get("reason", "")),
            )
        return None

    def restore_backup(self, record: BackupRecord) -> Path:
        """Restore a backup to its original path."""
        metadata = yaml.safe_load(record.metadata_path.read_text(encoding="utf-8")) or {}
        original_path = Path(metadata["original_path"])
        backup_type = metadata.get("backup_type", "file")
        original_path.parent.mkdir(parents=True, exist_ok=True)

        if original_path.exists() or original_path.is_symlink():
            original_path.unlink()
        if backup_type == "symlink":
            original_path.symlink_to(record.backup_path.read_text(encoding="utf-8"))
        else:
            shutil.copy2(record.backup_path, original_path)
        logger.info("Restored backup {} to {}", record.backup_path, original_path)
        return original_path
