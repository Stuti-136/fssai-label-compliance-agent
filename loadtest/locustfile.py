"""D6 load test. Measures a RUN from submission to final result (submit + poll), not the submit call alone.
Run with the LLM stub (default config). Cache busting is ON by default so every run does real work:
  LOCUST_CACHE_BUST=0 makes requests identical (measures the whole-run cache instead).
Headless example:  locust -f loadtest/locustfile.py --host http://localhost:8000 -u 20 -r 5 -t 3m --headless --csv out/run
Every simulated user has its own X-Client-Id so rate limiting (D7) does not distort the result; raise RATE_LIMIT_PER_MIN."""
import json, os, random, time, uuid
from locust import HttpUser, task, between, events

BUST = os.environ.get("LOCUST_CACHE_BUST", "1") == "1"
SAMPLES = [json.load(open(f"scripts/samples/{n}.json")) for n in ("protein_low", "protein_ok")]


class Analyst(HttpUser):
    wait_time = between(0.5, 2)

    def on_start(self):
        self.cid = f"locust-{uuid.uuid4().hex[:8]}"

    @task
    def full_run(self):
        body = dict(random.choice(SAMPLES))
        if BUST:
            body["brand_name"] = "Brand " + uuid.uuid4().hex[:8]
        t0 = time.perf_counter()
        r = self.client.post("/v1/runs", json=body, headers={"X-Client-Id": self.cid}, name="POST /v1/runs")
        if r.status_code != 202:
            return
        rid, status = r.json()["run_id"], None
        while time.perf_counter() - t0 < 120:
            g = self.client.get(f"/v1/runs/{rid}", name="GET /v1/runs/{id}")
            status = g.json().get("status")
            if status in ("completed", "failed"):
                break
            time.sleep(0.5)
        dt = (time.perf_counter() - t0) * 1000
        events.request.fire(request_type="RUN", name="end-to-end run", response_time=dt, response_length=0,
                            exception=None if status == "completed" else Exception(f"run {status}"), context={})
