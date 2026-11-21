# Data contracts (D1) - version 1.0

## 1. POST /v1/runs  (request) - machine-readable: `contracts/label_request.v1.schema.json`, live at `GET /v1/contract`
Headers: `X-Client-Id` (rate-limit key, optional), `Idempotency-Key` (optional), `X-Correlation-ID` (optional).
Query: `fault` (test only).
Body `LabelRequest` (additional properties forbidden):

| field | type / range | notes |
|---|---|---|
| schema_version | "1.0" | |
| product_name | str 2-120 | free text -> guardrails |
| brand_name | str <=80, opt | free text |
| declared_category | enum unspecified, biscuits_bakery, beverages_juices, dairy_products, snacks_savoury, confectionery_chocolates, cereals_breakfast, instant_ready_to_eat, spices_seasonings, sauces_dips_condiments, edible_oils_fats, pulses_packaged_grains, nutritional_health_foods, other; legacy values dairy, beverages, meat_fish, infant_nutrition, supplements, confectionery remain accepted | |
| custom_category | str 2-80, opt | required when declared_category is `other`; recorded as user-provided description, not as evidence of coverage |
| physical_state | solid \| liquid | |
| net_quantity_value / unit | float (0, 100000] / g,kg,ml,l | **cross-field**: solid->g/kg, liquid->ml/l |
| package_type | pouch, box, wrapper, bottle, jar, can, other | |
| package_surface_area_cm2 | float (0, 10000] | drives small-pack exemption check |
| ingredients_text | str 3-2000 | free text |
| front_of_pack_text | list[str<=200], <=20 | claims are detected here |
| diet_mark | veg, non_veg, none | |
| allergen_statement | str <=500, opt | |
| fssai_license_no | 14 digits, opt | |
| fssai_logo_present, batch_marking_present | bool | |
| manufacturer_name (<=120) / manufacturer_address (<=300) | opt | |
| date_marking | best_before, use_by, expiry, none | |
| is_imported / country_of_origin | bool / str <=60 | **cross-field**: imported => origin required |
| nutrition | object, opt; per 100 g (solid) or 100 ml (liquid) | energy_kcal 0-900, protein/carbohydrate/total_sugars/added_sugars/dietary_fibre/total_fat/saturated_fat/trans_fat 0-100 g, sodium_mg 0-40000 |

Nutrition cross-field rules: total_sugars <= carbohydrate; added_sugars <= total_sugars; saturated+trans <= total_fat;
energy within 35% of 4*(protein+carb)+9*fat.
Free-text fields additionally pass injection and toxicity detection **at the boundary**.

Responses: `202 {run_id, status_url, trace_url, cached}` | `422 {error, quarantined:true, quarantine_id, errors:[{field,code,message}], agent_run_started:false}` | `429 {retry_after_s}`.
Rejected records are stored in Redis list `quarantine` (`GET /v1/quarantine`) with field-level errors. **No agent run is created.**

Category values are descriptive input, not a coverage guarantee. The automated category workflow remains configured only
for biscuits and bakery snacks. Other categories are accepted but escalated for human review; no product-specific
requirements are inferred from the category label.

## 2. GET /v1/runs/{id}
`{run_id, status: queued|researching|assessing|completed|failed, result?}`. `result`:
`route, route_reason, complete, category, category_details, claims_detected, findings[], escalations[], escalation_path, summary, summary_source,
verification{ok,attempts,repaired,failures}, degraded, versions{prompt,index,corpus,retrieval_mode}, stats{researcher,assessor,cost_usd,tokens,e2e_seconds}, disclaimer`.
Finding: `{id, kind: rule|claim, title, status: met|unmet|needs_human|not_applicable, detail, computed?, citations[{doc_id, clause_id, chunk_id, quote}]}`.
A run that did not complete has `status:"failed"`, `complete:false`, `route:"regulatory-review"`, no findings.

## 3. Internal: queue messages and EvidenceBundle
`q:research`/`q:assess`: `{run_id, attempt, carrier(traceparent)}`. `bundle:{run_id}` (JSON):
`{category, claims[], passages{chunk_id->{doc_id,clause_id,title,text}}, unresolved[], cues[], stop_reason, degraded, retrieval_mode, stats}`.

## 4. POST /v1/runs/{id}/feedback  `{satisfactory: bool, reason: str<=500}` -> aggregated at `GET /v1/feedback/summary`.

## 5. LLM provider interface
OpenAI-compatible `POST {LLM_BASE_URL}/chat/completions`; usage tokens used for cost. Swap provider by env only.

## 6. Corpus pipeline contract
Input: `CORPUS_DIR/*.md|txt|pdf` (md header `# DOC: id | title | version`, clauses `## [clause] title`). Output `INDEX_DIR` contains `active_index.json` and immutable `generations/<version-id>/` directories containing `faiss/`, `vectors.npy`, `chunks.jsonl`, and `index_meta.json` (document versions/hashes, embedder, chunks, throughput). Existing root-level indexes remain readable until the first generation is published. Source editions mapping to the same canonical ID must be curated before ingestion to avoid mixing versions.
