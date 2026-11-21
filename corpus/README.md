# Corpus

Category in scope: **packaged biscuits, cookies, crackers and cereal-based bakery snacks** (`biscuits_bakery`).
Anything else is escalated (F7).

`*.seed.md` are *paraphrased seed passages* so the system runs from a clean clone. They are **not** the official text.
The supplied source PDFs are preserved in `source_pdfs/`. The directory contains multiple editions and a separate Gazette
notification; do not ingest all of them together. Ingestion rejects two files that map to the same canonical document ID.

For a reproducible extraction test without changing source documents:

```powershell
New-Item -ItemType Directory -Force corpus\active | Out-Null
Copy-Item "corpus\source_pdfs\Comp_Labelling Display_Version VIII_09_09_2025.pdf" "corpus\active\LDR-2020.pdf"
Copy-Item "corpus\source_pdfs\Compendium_Advertising_Claims_Regulations_04_10_2022.pdf" "corpus\active\ACR-2018.pdf"
python -m app.rag.ingest --corpus corpus\active --out data\official-index
```

The base filenames are mapped to canonical document IDs. The source copy retains the original PDF; the version should be
checked in the generated metadata. Ingestion warns about referenced clauses absent from the index but does not establish
legal currency or resolve amendments. Do not change any rule or claim clause until an authorized reviewer verifies the
applicable official edition and amendments.

The default runtime corpus remains `raw/`, whose `.seed.md` passages are paraphrased placeholders and are not official law.
