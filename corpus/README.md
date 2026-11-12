# Corpus

Category in scope: **packaged biscuits, cookies, crackers and cereal-based bakery snacks** (`biscuits_bakery`).
Anything else is escalated (F7).

`*.seed.md` are *paraphrased seed passages* so the system runs from a clean clone. They are **not** the official text.
For the real project:

1. Download the Labelling & Display Regulations 2020 and the Advertising & Claims Regulations 2018 from fssai.gov.in
   (text-layer PDFs). Save them as `corpus/raw/LDR-2020.pdf` and `corpus/raw/ACR-2018.pdf` (the file stem becomes the doc id).
2. Delete the matching `*.seed.md`.
3. `docker compose run --rm indexer` (or `python -m app.rag.ingest`). The ingest step reports which clause ids used by
   `app/rules.py` / `app/claims.py` are missing from the index; update those ids to the official numbering.
4. Show the Evaluation-1 passages with `python -m app.rag.show_case` (prints the passages the section 4.1 case depends on).
