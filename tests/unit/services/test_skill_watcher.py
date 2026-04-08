import os
import tempfile
from pathlib import Path

from services.skill_sync.src.watcher import SkillWatcher


class TestSkillWatcherHash:
    def test_hash_file_returns_hex_string(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"print('hello')")
            f.flush()
            h = SkillWatcher._hash_file(Path(f.name))
        os.unlink(f.name)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_hash_file_deterministic(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"x = 42")
            f.flush()
            h1 = SkillWatcher._hash_file(Path(f.name))
            h2 = SkillWatcher._hash_file(Path(f.name))
        os.unlink(f.name)
        assert h1 == h2

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f1:
            f1.write(b"a = 1")
            f1.flush()
            h1 = SkillWatcher._hash_file(Path(f1.name))
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f2:
            f2.write(b"a = 2")
            f2.flush()
            h2 = SkillWatcher._hash_file(Path(f2.name))
        os.unlink(f1.name)
        os.unlink(f2.name)
        assert h1 != h2


class TestSkillWatcherChangeDetection:
    def test_detects_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            watcher = SkillWatcher(skills_dir=tmpdir)
            Path(tmpdir, "skill_a.py").write_text("pass")
            changes = watcher.poll_once()
            assert len(changes) == 1
            assert changes[0].action == "created"

    def test_detects_modified_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = Path(tmpdir, "skill_b.py")
            skill_path.write_text("v1")
            watcher = SkillWatcher(skills_dir=tmpdir)
            watcher.poll_once()
            skill_path.write_text("v2")
            changes = watcher.poll_once()
            assert any(c.action == "modified" for c in changes)

    def test_detects_deleted_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_path = Path(tmpdir, "skill_c.py")
            skill_path.write_text("content")
            watcher = SkillWatcher(skills_dir=tmpdir)
            watcher.poll_once()
            skill_path.unlink()
            changes = watcher.poll_once()
            assert any(c.action == "deleted" for c in changes)

    def test_no_changes_on_unchanged_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "stable.py").write_text("ok")
            watcher = SkillWatcher(skills_dir=tmpdir)
            watcher.poll_once()
            changes = watcher.poll_once()
            assert len(changes) == 0

    def test_known_skills_property(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "s.py").write_text("x")
            watcher = SkillWatcher(skills_dir=tmpdir)
            watcher.poll_once()
            assert len(watcher.known_skills) == 1
