#!/usr/bin/env bash
# A7: measure throughput and p95 at researcher=1 and researcher=3 against the stub. Output: loadtest/out/*.csv
set -euo pipefail
mkdir -p loadtest/out
for N in 1 3; do
  docker compose up -d --build --scale researcher=$N
  sleep 20
  docker compose --profile loadtest run --rm -T locust locust -f loadtest/locustfile.py --host http://api:8000 \
     -u ${USERS:-20} -r 5 -t ${DURATION:-3m} --headless --csv loadtest/out/researcher_$N
done
echo "Compare loadtest/out/researcher_1_stats.csv and researcher_3_stats.csv (row 'end-to-end run': Requests/s, 50%, 95%)."
