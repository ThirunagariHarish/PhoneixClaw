from shared.db.models import (
    Agent,
    AgentBacktest,
    AgentLog,
    AgentMessage,
    AgentSkill,
    ApiKeyEntry,
    AuditLog,
    Automation,
    Base,
    Connector,
    ConnectorAgent,
    DevIncident,
    Position,
    Skill,
    Task,
    TradeIntent,
    TradingAccount,
    User,
)

_EXPECTED_TABLES = {
    User: "users",
    Agent: "agents",
    AgentBacktest: "agent_backtests",
    AgentLog: "agent_logs",
    TradeIntent: "trade_intents",
    Position: "positions",
    Connector: "connectors",
    ConnectorAgent: "connector_agents",
    Skill: "skills",
    AgentSkill: "agent_skills",
    Task: "tasks",
    Automation: "automations",
    DevIncident: "dev_incidents",
    AuditLog: "audit_logs",
    ApiKeyEntry: "api_keys",
    TradingAccount: "trading_accounts",
    AgentMessage: "agent_messages",
}


class TestModelTableNames:
    def test_all_models_importable(self):
        for model_cls in _EXPECTED_TABLES:
            assert hasattr(model_cls, "__tablename__")

    def test_tablename_correctness(self):
        for model_cls, expected_name in _EXPECTED_TABLES.items():
            assert model_cls.__tablename__ == expected_name, (
                f"{model_cls.__name__}.__tablename__ = {model_cls.__tablename__!r}, expected {expected_name!r}"
            )

    def test_models_inherit_from_base(self):
        for model_cls in _EXPECTED_TABLES:
            assert issubclass(model_cls, Base)


class TestUserModelColumns:
    def test_user_has_email_column(self):
        cols = {c.name for c in User.__table__.columns}
        assert "email" in cols

    def test_user_has_role_column(self):
        cols = {c.name for c in User.__table__.columns}
        assert "role" in cols

    def test_user_has_id_column(self):
        cols = {c.name for c in User.__table__.columns}
        assert "id" in cols


class TestAgentModelColumns:
    def test_agent_has_name(self):
        cols = {c.name for c in Agent.__table__.columns}
        assert "name" in cols

    def test_agent_has_status(self):
        cols = {c.name for c in Agent.__table__.columns}
        assert "status" in cols
