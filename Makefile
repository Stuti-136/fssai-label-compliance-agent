up:        ; docker compose up --build
scale:     ; docker compose up --build --scale researcher=3
down:      ; docker compose down
test:      ; python -m pytest -q
eval:      ; python eval/run_eval.py --label agentic && python eval/run_eval.py --label single_pass --retrieval-mode single_pass && python eval/run_eval.py --compare eval/results/single_pass.json eval/results/agentic.json
index:     ; docker compose run --rm indexer
schema:    ; python -m app.contracts contracts/label_request.v1.schema.json
dashboard: ; python ops/make_dashboard.py
