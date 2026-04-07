"""Unit tests for critical bug fixes (Phase 2 bug-fix batch).

Covers:
- FIX 1: discord_redis_consumer — stream key selection, cursor persistence
- FIX 3: heartbeat endpoint updates last_activity_at
- FIX 5: inference.py falls back to .pkl when .pt is present
- M1/M3/S3: live_pipeline guards + cursor isolation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers for path manipulation so we can import agent tools without the full
# live-trader-v1 being on sys.path.
# ---------------------------------------------------------------------------
LIVE_TRADER_TOOLS = (
    Path(__file__).parents[2] / "agents" / "templates" / "live-trader-v1" / "tools"
)


# ---------------------------------------------------------------------------
# FIX 1: discord_redis_consumer — stream key + cursor
# ---------------------------------------------------------------------------
class TestRedisConsumerStreamKey:
    """Stream key resolution: connector_id key preferred over channel_id key."""

    def _import_module(self):
        """Import discord_redis_consumer from agent tools dir."""
        if str(LIVE_TRADER_TOOLS) not in sys.path:
            sys.path.insert(0, str(LIVE_TRADER_TOOLS))
        import importlib

        import discord_redis_consumer as m

        importlib.reload(m)  # ensure fresh state
        return m

    def test_config_loads_connector_id(self, tmp_path, monkeypatch):
        """_config() returns connector_id when present in config.json."""
        monkeypatch.chdir(tmp_path)
        cfg = {"channel_id": "CH1", "connector_id": "CONN1"}
        (tmp_path / "config.json").write_text(json.dumps(cfg))

        m = self._import_module()
        result = m._config()
        assert result["connector_id"] == "CONN1"
        assert result["channel_id"] == "CH1"

    def test_config_missing_file_returns_empty(self, tmp_path, monkeypatch):
        """_config() returns empty dict when config.json is absent."""
        monkeypatch.chdir(tmp_path)
        m = self._import_module()
        result = m._config()
        assert result == {}

    def test_cursor_round_trip(self, tmp_path, monkeypatch):
        """_save_cursor / _load_cursor persist and reload the cursor value."""
        monkeypatch.chdir(tmp_path)
        m = self._import_module()
        monkeypatch.setattr(m, "CURSOR_FILE", tmp_path / "stream_cursor.json")

        stream_key = "stream:channel:CONN1"
        # Default when no file
        assert m._load_cursor(stream_key) == "0-0"

        m._save_cursor(stream_key, "1234-0", 10)
        assert m._load_cursor(stream_key) == "1234-0"

        m._save_cursor(stream_key, "9999-5", 25)
        assert m._load_cursor(stream_key) == "9999-5"

    def test_cursor_default_is_zero(self, tmp_path, monkeypatch):
        """_load_cursor() defaults to '0-0' when no cursor file exists."""
        monkeypatch.chdir(tmp_path)
        m = self._import_module()
        monkeypatch.setattr(m, "CURSOR_FILE", tmp_path / "stream_cursor_missing.json")
        assert m._load_cursor("stream:channel:ANY") == "0-0"

    def test_cursor_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """Saving a cursor and loading it returns the same last_id."""
        monkeypatch.chdir(tmp_path)
        m = self._import_module()
        monkeypatch.setattr(m, "CURSOR_FILE", tmp_path / "stream_cursor.json")

        key = "stream:channel:CONN1"
        m._save_cursor(key, "100-0", 5)
        assert m._load_cursor(key) == "100-0"

        # Overwriting with a newer id returns the new value
        m._save_cursor(key, "200-0", 6)
        assert m._load_cursor(key) == "200-0"

        # A different stream_key falls back to 0-0 (flat file, single stream per agent)
        assert m._load_cursor("stream:channel:OTHER") == "0-0"

    @pytest.mark.asyncio
    async def test_consume_uses_connector_id_as_stream_key(self, tmp_path, monkeypatch):
        """consume() subscribes to stream:channel:{connector_id}."""
        monkeypatch.chdir(tmp_path)
        m = self._import_module()
        monkeypatch.setattr(m, "CURSOR_FILE", tmp_path / "stream_cursor.json")
        monkeypatch.setattr(m, "_shutdown", False)

        msg_data = {
            "channel_id": "CH1",
            "channel": "spx-trades",
            "author": "Vinod",
            "content": "BUY SPY 450C",
            "timestamp": "2024-01-01T10:00:00Z",
            "message_id": "MSG1",
        }
        call_count = 0

        async def fake_xread(streams, count, block):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [("stream:channel:CONN1", [("1-0", msg_data)])]
            # Signal shutdown so the loop exits cleanly.
            monkeypatch.setattr(m, "_shutdown", True)
            return []

        mock_redis = AsyncMock()
        mock_redis.xread = fake_xread
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            count = await m.consume("CONN1", str(tmp_path / "out.json"))

        assert count == 1
        out = json.loads((tmp_path / "out.json").read_text())
        assert out[0]["content"] == "BUY SPY 450C"
        assert out[0]["author"] == "Vinod"

    @pytest.mark.asyncio
    async def test_consume_resumes_from_persisted_cursor(self, tmp_path, monkeypatch):
        """consume() starts from persisted cursor so backlog is not replayed."""
        monkeypatch.chdir(tmp_path)
        m = self._import_module()
        cursor_file = tmp_path / "stream_cursor.json"
        monkeypatch.setattr(m, "CURSOR_FILE", cursor_file)

        stream_key = "stream:channel:CONN1"
        m._save_cursor(stream_key, "500-0", 10)  # simulate previous run

        xread_calls: list = []

        async def fake_xread(streams, count, block):
            last_id_used = list(streams.values())[0]
            xread_calls.append(last_id_used)
            monkeypatch.setattr(m, "_shutdown", True)
            return []

        mock_redis = AsyncMock()
        mock_redis.xread = fake_xread
        mock_redis.aclose = AsyncMock()

        with patch("redis.asyncio.from_url", return_value=mock_redis):
            await m.consume("CONN1", str(tmp_path / "out.json"))

        assert xread_calls, "xread should have been called at least once"
        assert xread_calls[0] == "500-0", f"Expected cursor 500-0, got {xread_calls[0]}"

    def test_main_no_connector_id_exits(self, tmp_path, monkeypatch):
        """main() exits with code 1 when no connector_id or channel_id is configured."""
        monkeypatch.chdir(tmp_path)
        m = self._import_module()
        # Patch sys.argv so argparse doesn't pick up pytest arguments
        monkeypatch.setattr(sys, "argv", ["discord_redis_consumer"])
        with pytest.raises(SystemExit) as exc_info:
            m.main()
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# M1: live_pipeline._redis_signal_stream — guard against missing ids
# ---------------------------------------------------------------------------
class TestLivePipelineGuards:
    """live_pipeline._redis_signal_stream returns immediately when both
    connector_id and channel_id are absent from config."""

    def _import_pipeline(self):
        import importlib

        if str(LIVE_TRADER_TOOLS) not in sys.path:
            sys.path.insert(0, str(LIVE_TRADER_TOOLS))
        import live_pipeline as m
        importlib.reload(m)
        return m

    @pytest.mark.asyncio
    async def test_redis_stream_returns_on_missing_ids(self, tmp_path, monkeypatch):
        """_redis_signal_stream yields nothing and returns when config has no ids."""
        monkeypatch.chdir(tmp_path)
        m = self._import_pipeline()

        results = []
        async for item in m._redis_signal_stream({}):
            results.append(item)

        assert results == [], "Should yield nothing when connector_id and channel_id are both absent"

    @pytest.mark.asyncio
    async def test_redis_stream_returns_on_none_connector_and_channel(self, tmp_path, monkeypatch):
        """_redis_signal_stream returns when both ids are None."""
        monkeypatch.chdir(tmp_path)
        m = self._import_pipeline()

        results = []
        async for item in m._redis_signal_stream({"connector_id": None, "channel_id": None}):
            results.append(item)

        assert results == []


# ---------------------------------------------------------------------------
# S3: message_ingestion._db_write_failures increments on DB error
# ---------------------------------------------------------------------------
class TestDbWriteFailuresCounter:
    """_db_write_failures counter must increment each time a DB persist fails."""

    @pytest.mark.asyncio
    async def test_db_write_failures_increments_on_error(self):
        """_persist_message increments _db_write_failures when DB raises."""
        # Import fresh to get a clean counter state
        import importlib
        import sys

        api_services = Path(__file__).parents[2] / "apps" / "api" / "src"
        if str(api_services.parent) not in sys.path:
            sys.path.insert(0, str(api_services.parent))

        # We need to mock out the DB session so it raises
        async def failing_session():
            raise RuntimeError("DB connection refused")
            yield  # make it an async generator

        mock_msg = MagicMock()
        mock_msg.channel = "test"
        mock_msg.author = "bot"
        mock_msg.content = "hello"
        mock_msg.message_type = "info"
        mock_msg.tickers = []
        mock_msg.raw_data = {}
        mock_msg.metadata = {}
        mock_msg.timestamp = None

        with patch.dict("sys.modules", {
            "shared.db.engine": MagicMock(get_session=lambda: failing_session()),
            "shared.db.models.channel_message": MagicMock(),
        }):
            import apps.api.src.services.message_ingestion as mi
            importlib.reload(mi)
            before = mi._db_write_failures

            result = await mi._persist_message("connector-uuid-1234", mock_msg)

            assert result is False
            assert mi._db_write_failures == before + 1


# ---------------------------------------------------------------------------
# FIX 3: Heartbeat endpoint — agents_sprint.py updates last_activity_at
# ---------------------------------------------------------------------------
class TestHeartbeatEndpoint:
    """Verify agents.py no longer has a /{agent_id}/heartbeat route and
    agents_sprint.py's implementation updates last_activity_at."""

    def test_agents_py_has_no_heartbeat_route(self):
        """agents.py must NOT define a heartbeat endpoint (removed in fix 3)."""
        agents_py = Path(__file__).parents[2] / "apps" / "api" / "src" / "routes" / "agents.py"
        content = agents_py.read_text()
        assert "async def agent_heartbeat" not in content

    def test_agents_sprint_has_heartbeat_route(self):
        """agents_sprint.py must define the authoritative heartbeat endpoint."""
        sprint_py = Path(__file__).parents[2] / "apps" / "api" / "src" / "routes" / "agents_sprint.py"
        content = sprint_py.read_text()
        assert "async def post_heartbeat" in content
        assert "last_activity_at" in content
        assert "runtime_status" in content

    def test_heartbeat_body_accepts_pipeline_fields(self):
        """HeartbeatBody must accept signals_processed, trades_today, timestamp."""
        sprint_py = Path(__file__).parents[2] / "apps" / "api" / "src" / "routes" / "agents_sprint.py"
        content = sprint_py.read_text()
        assert "signals_processed" in content
        assert "trades_today" in content
        assert "timestamp" in content

    @pytest.mark.asyncio
    async def test_heartbeat_updates_last_activity_at(self):
        """post_heartbeat sets agent.last_activity_at and runtime_status='alive'."""
        import uuid

        agent_id = uuid.uuid4()

        mock_agent = MagicMock()
        mock_agent.id = agent_id
        mock_agent.last_activity_at = None
        mock_agent.runtime_status = None

        call_count = 0

        def make_result(val):
            r = MagicMock()
            r.scalar_one_or_none = MagicMock(return_value=val)
            return r

        async def fake_execute(query, *a, **kw):
            nonlocal call_count
            call_count += 1
            # First call: AgentSession lookup → None; second: Agent lookup → mock_agent
            return make_result(None if call_count == 1 else mock_agent)

        mock_session_obj = MagicMock()
        mock_session_obj.execute = fake_execute
        mock_session_obj.commit = AsyncMock()

        sys.path.insert(0, str(Path(__file__).parents[2]))
        from apps.api.src.routes.agents_sprint import HeartbeatBody, post_heartbeat

        body = HeartbeatBody(status="listening", signals_processed=5, trades_today=1)
        await post_heartbeat(agent_id=agent_id, body=body, session=mock_session_obj)

        assert mock_agent.last_activity_at is not None
        assert mock_agent.runtime_status == "alive"


# ---------------------------------------------------------------------------
# FIX 5: inference.py — fallback to .pkl when .pt is present
# ---------------------------------------------------------------------------
class TestInferenceFallback:
    """inference.predict() should degrade gracefully when best model is .pt."""

    def _import_inference(self):
        if str(LIVE_TRADER_TOOLS) not in sys.path:
            sys.path.insert(0, str(LIVE_TRADER_TOOLS))
        import importlib

        import inference as m

        importlib.reload(m)
        return m

    def _write_model_fixtures(self, models_dir: Path, best_model_name: str):
        """Write minimal fixture files needed by predict()."""
        models_dir.mkdir(exist_ok=True)
        (models_dir / "best_model.json").write_text(json.dumps({"best_model": best_model_name}))
        (models_dir / "meta.json").write_text(json.dumps({"feature_columns": ["rsi", "macd"]}))

    def test_predict_loads_pkl_when_present(self, tmp_path):
        """predict() loads .pkl normally when it exists."""
        import numpy as np

        m = self._import_inference()
        models_dir = tmp_path / "models"
        self._write_model_fixtures(models_dir, "lightgbm")
        # patterns.json required by predict() pattern matching section
        (models_dir / "patterns.json").write_text("[]")

        features_file = tmp_path / "features.json"
        features_file.write_text(json.dumps({"rsi": 55.0, "macd": 0.1}))

        mock_imputer = MagicMock()
        mock_imputer.transform = MagicMock(return_value=np.array([[55.0, 0.1]]))
        mock_scaler = MagicMock()
        mock_scaler.transform = MagicMock(return_value=np.array([[0.5, 0.1]]))
        mock_model = MagicMock()
        mock_model.predict = MagicMock(return_value=np.array([1]))
        mock_model.predict_proba = MagicMock(return_value=np.array([[0.1, 0.85]]))

        def fake_exists(self):
            # All paths exist so the primary .pkl path is taken
            return True

        with (
            patch("joblib.load", side_effect=[mock_imputer, mock_scaler, mock_model]),
            patch.object(Path, "exists", fake_exists),
        ):
            result = m.predict(str(features_file), str(models_dir))

        assert result["prediction"] == "TRADE"
        assert result["confidence"] == 0.85

    def test_predict_falls_back_to_pkl_when_pt_exists(self, tmp_path):
        """predict() uses fallback .pkl when best model is a .pt file."""
        import numpy as np

        m = self._import_inference()
        models_dir = tmp_path / "models"
        self._write_model_fixtures(models_dir, "lstm")

        lgbm_pkl = models_dir / "lightgbm_model.pkl"
        lgbm_pkl.write_bytes(b"placeholder")  # content irrelevant — joblib.load is mocked

        features_file = tmp_path / "features.json"
        features_file.write_text(json.dumps({"rsi": 45.0, "macd": -0.05}))

        mock_imputer = MagicMock()
        mock_imputer.transform = MagicMock(return_value=np.array([[45.0, -0.05]]))
        mock_scaler = MagicMock()
        mock_scaler.transform = MagicMock(return_value=np.array([[0.3, -0.1]]))
        mock_model = MagicMock()
        mock_model.predict = MagicMock(return_value=np.array([0]))
        mock_model.predict_proba = MagicMock(return_value=np.array([[0.7, 0.3]]))

        def fake_exists(self):
            name = str(self)
            if "lstm_model.pkl" in name:
                return False
            if "lstm_model.pt" in name:
                return True
            if "lightgbm_model.pkl" in name:
                return True
            return False

        with (
            patch("joblib.load", side_effect=[mock_imputer, mock_scaler, mock_model]),
            patch.object(Path, "exists", fake_exists),
            patch.object(Path, "glob", return_value=[lgbm_pkl]),
        ):
            result = m.predict(str(features_file), str(models_dir))

        assert result["prediction"] == "SKIP"
        assert result["model"] == "lightgbm"

    def test_predict_raises_when_no_models(self, tmp_path):
        """predict() raises FileNotFoundError when no model files exist at all."""
        import numpy as np

        m = self._import_inference()
        models_dir = tmp_path / "models"
        self._write_model_fixtures(models_dir, "rf")

        features_file = tmp_path / "features.json"
        features_file.write_text(json.dumps({"rsi": 50.0, "macd": 0.0}))

        mock_imputer = MagicMock()
        mock_imputer.transform = MagicMock(return_value=np.array([[50.0, 0.0]]))
        mock_scaler = MagicMock()
        mock_scaler.transform = MagicMock(return_value=np.array([[0.4, 0.0]]))

        def fake_exists_none(self):
            return False

        with (
            patch("joblib.load", side_effect=[mock_imputer, mock_scaler]),
            patch.object(Path, "exists", fake_exists_none),
            patch.object(Path, "glob", return_value=[]),
        ):
            with pytest.raises(FileNotFoundError, match="No model files found"):
                m.predict(str(features_file), str(models_dir))
