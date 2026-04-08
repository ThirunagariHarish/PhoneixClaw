"""
File system watcher — detects changes in the ``openclaw/skills/`` directory
and queues modified skills for distribution.

M2.9: Skill hot-reload pipeline.
"""

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue

logger = logging.getLogger(__name__)


@dataclass
class SkillChange:
    path: str
    action: str  # "created" | "modified" | "deleted"
    content_hash: str
    timestamp: float


class SkillWatcher:
    """Monitors the skills directory for file changes using content hashing."""

    def __init__(
        self,
        skills_dir: str = "openclaw/skills",
        poll_interval: float = 2.0,
    ):
        self._skills_dir = Path(skills_dir)
        self._poll_interval = poll_interval
        self._hashes: dict[str, str] = {}
        self._change_queue: Queue[SkillChange] = Queue()
        self._running = False

    @staticmethod
    def _hash_file(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _scan(self) -> list[SkillChange]:
        """Compare current state against cached hashes."""
        changes: list[SkillChange] = []
        now = time.time()
        current_files: dict[str, str] = {}

        if not self._skills_dir.exists():
            return changes

        for p in self._skills_dir.rglob("*.py"):
            key = str(p)
            h = self._hash_file(p)
            current_files[key] = h

            if key not in self._hashes:
                changes.append(SkillChange(key, "created", h, now))
            elif self._hashes[key] != h:
                changes.append(SkillChange(key, "modified", h, now))

        for key in set(self._hashes) - set(current_files):
            changes.append(SkillChange(key, "deleted", "", now))

        self._hashes = current_files
        return changes

    def poll_once(self) -> list[SkillChange]:
        """Run a single scan cycle and enqueue any changes."""
        changes = self._scan()
        for c in changes:
            self._change_queue.put(c)
            logger.info("Skill %s: %s", c.action, c.path)
        return changes

    def run(self) -> None:
        """Blocking poll loop. Call from a dedicated thread."""
        self._running = True
        logger.info("SkillWatcher started on %s", self._skills_dir)
        while self._running:
            self.poll_once()
            time.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    def get_pending_changes(self) -> list[SkillChange]:
        """Drain the change queue."""
        items: list[SkillChange] = []
        while not self._change_queue.empty():
            items.append(self._change_queue.get_nowait())
        return items

    @property
    def known_skills(self) -> dict[str, str]:
        return dict(self._hashes)
