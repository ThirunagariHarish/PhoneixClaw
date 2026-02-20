"""Load test suite for the Phoenix Trade Bot.
Run: locust -f tests/load/locustfile.py --host http://localhost:8011
"""
from locust import HttpUser, between, task


class TradingPlatformUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        resp = self.client.post("/auth/register", json={
            "email": f"loadtest+{id(self)}@test.com",
            "password": "TestPass123!",
            "name": "Load Test User",
        })
        if resp.status_code in (201, 409):
            login_resp = self.client.post("/auth/login", json={
                "email": f"loadtest+{id(self)}@test.com",
                "password": "TestPass123!",
            })
            if login_resp.status_code == 200:
                token = login_resp.json()["access_token"]
                self.client.headers["Authorization"] = f"Bearer {token}"

    @task(10)
    def get_trades(self):
        self.client.get("/api/v1/trades?limit=20")

    @task(5)
    def get_accounts(self):
        self.client.get("/api/v1/accounts")

    @task(5)
    def get_sources(self):
        self.client.get("/api/v1/sources")

    @task(3)
    def get_metrics(self):
        self.client.get("/api/v1/metrics/daily?days=7")

    @task(2)
    def get_notifications(self):
        self.client.get("/api/v1/notifications?limit=10")

    @task(1)
    def system_health(self):
        self.client.get("/api/v1/system/health")

    @task(1)
    def health_check(self):
        self.client.get("/health")
