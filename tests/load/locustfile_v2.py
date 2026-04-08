"""
Load test for Phoenix v2 API using Locust.

M3.13: Performance and load testing.
"""

from locust import HttpUser, between, task


class PhoenixUser(HttpUser):
    wait_time = between(1, 3)
    host = "http://localhost:8011"

    def on_start(self):
        resp = self.client.post("/auth/login", json={
            "email": "test@phoenix.io",
            "password": "testpassword123",
        })
        if resp.status_code == 200:
            self.token = resp.json().get("access_token", "")
        else:
            self.token = ""

    @property
    def auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(5)
    def get_trades(self):
        self.client.get("/api/v2/trades", headers=self.auth_headers)

    @task(5)
    def get_positions(self):
        self.client.get("/api/v2/positions", headers=self.auth_headers)

    @task(3)
    def get_agents(self):
        self.client.get("/api/v2/agents", headers=self.auth_headers)

    @task(2)
    def get_instances(self):
        self.client.get("/api/v2/instances", headers=self.auth_headers)

    @task(2)
    def get_skills(self):
        self.client.get("/api/v2/skills", headers=self.auth_headers)

    @task(1)
    def get_execution_status(self):
        self.client.get("/api/v2/execution/status", headers=self.auth_headers)

    @task(1)
    def get_trade_stats(self):
        self.client.get("/api/v2/trades/stats", headers=self.auth_headers)

    @task(1)
    def health_check(self):
        self.client.get("/health")
