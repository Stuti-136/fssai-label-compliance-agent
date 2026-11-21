import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.rag.chunking import _pdf_identity, parse_file
from app.rag.index_paths import resolve_index_dir
from app.rag.ingest import run_ingest
from app.rag.store import CorpusIndex

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "corpus" / "source_pdfs"


@pytest.mark.parametrize(
    ("filename", "doc_id"),
    [("LDR-2020.pdf", "LDR-2020"), ("ACR-2018.pdf", "ACR-2018")],
)
def test_documented_pdf_filename_mapping(filename, doc_id):
    mapped_id, _, version = _pdf_identity(Path(filename))

    assert mapped_id == doc_id
    assert version == "Source PDF (version not encoded in PDF)"


@pytest.mark.parametrize(
    ("filename", "doc_id"),
    [
        ("Comp_Labelling Display_Version VIII_09_09_2025.pdf", "LDR-2020"),
        ("Compendium_Advertising_Claims_Regulations_04_10_2022.pdf", "ACR-2018"),
    ],
)
def test_parse_supplied_regulatory_pdf(filename, doc_id):
    chunks = parse_file(PDF_DIR / filename)

    assert chunks
    assert {chunk.doc_id for chunk in chunks} == {doc_id}
    assert all(chunk.text.strip() for chunk in chunks)
    if doc_id == "ACR-2018":
        assert any(
            chunk.clause_id == "ACR-2018:Schedule I/Protein"
            and "10% of RDA per 100 g" in chunk.text
            for chunk in chunks
        )


@pytest.mark.parametrize(
    ("source_name", "alias", "expected_version"),
    [
        (
            "Comp_Labelling Display_Version VIII_09_09_2025.pdf",
            "LDR-2020.pdf",
            "Version VIII (09.09.2025)",
        ),
        (
            "Compendium_Advertising_Claims_Regulations_04_10_2022.pdf",
            "ACR-2018.pdf",
            "Compendium (04.10.2022)",
        ),
    ],
)
def test_pdf_alias_reads_edition_from_pdf_text(
    tmp_path, source_name, alias, expected_version
):
    source = PDF_DIR / source_name
    staged = tmp_path / alias
    shutil.copyfile(source, staged)

    chunks = parse_file(staged)

    assert chunks
    assert {chunk.doc_version for chunk in chunks} == {expected_version}


def test_pdf_edition_is_not_inferred_from_non_header_text():
    from app.rag.chunking import _pdf_edition_from_text

    assert (
        _pdf_edition_from_text(
            "LDR-2020",
            "An unrelated sentence mentions Version VIII (09.09.2025).",
        )
        is None
    )


def test_gazette_source_gets_its_own_version_label():
    _, _, version = _pdf_identity(
        PDF_DIR / "Gazette_Notification_Advertising_Claims_27_11_2018.pdf"
    )

    assert version == "Gazette Notification (27.11.2018)"


def test_ingest_documented_pdf_filenames_and_load_index(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copyfile(
        PDF_DIR / "Comp_Labelling Display_Version VIII_09_09_2025.pdf",
        corpus / "LDR-2020.pdf",
    )
    shutil.copyfile(
        PDF_DIR / "Compendium_Advertising_Claims_Regulations_04_10_2022.pdf",
        corpus / "ACR-2018.pdf",
    )
    out = tmp_path / "index"

    result = run_ingest(str(corpus), str(out))
    index = CorpusIndex(str(out))

    assert result["chunks"] > 0
    assert set(result["documents"]) == {"LDR-2020", "ACR-2018"}
    assert index.version == result["index_version"]
    assert resolve_index_dir(out).is_dir()
    assert (out / "active_index.json").is_file()


def test_ingest_rejects_multiple_editions_for_same_document_id(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copyfile(
        PDF_DIR / "Comp_Labelling Display_Version VII_03042025.pdf",
        corpus / "Comp_Labelling Display_Version VII_03042025.pdf",
    )
    shutil.copyfile(
        PDF_DIR / "Comp_Labelling Display_Version VIII_09_09_2025.pdf",
        corpus / "Comp_Labelling Display_Version VIII_09_09_2025.pdf",
    )

    with pytest.raises(ValueError, match="avoid mixing regulatory editions"):
        run_ingest(str(corpus), str(tmp_path / "index"))


def test_failed_index_publication_preserves_active_generation(tmp_path, monkeypatch):
    from app.rag import ingest

    corpus = ROOT / "corpus" / "raw"
    out = tmp_path / "index"
    first = run_ingest(str(corpus), str(out))
    index = CorpusIndex(str(out))
    manifest_path = out / "active_index.json"
    original_manifest = manifest_path.read_bytes()
    original_generation = resolve_index_dir(out)

    real_replace = ingest.os.replace

    def fail_manifest_replace(source, destination):
        if Path(destination) == manifest_path:
            raise OSError("simulated manifest replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(ingest.os, "replace", fail_manifest_replace)

    with pytest.raises(OSError, match="simulated manifest replacement failure"):
        run_ingest(str(corpus), str(out), reembed=True)

    assert manifest_path.read_bytes() == original_manifest
    assert resolve_index_dir(out) == original_generation
    assert index.version == first["index_version"]

    monkeypatch.undo()
    run_ingest(str(corpus), str(out), reembed=True)
    index.reload_if_changed()
    assert index.dir == resolve_index_dir(out)
    assert index.dir != original_generation
    assert original_generation.is_dir()


def test_metadata_only_change_publishes_new_generation_without_mutating_noop(
    tmp_path,
):
    corpus = tmp_path / "corpus"
    shutil.copytree(ROOT / "corpus" / "raw", corpus)
    source = next(corpus.glob("*.seed.md"))
    lines = source.read_text(encoding="utf-8").splitlines()
    header_parts = lines[0].split("|")
    old_version = header_parts[-1].strip()
    new_version = f"{old_version} (metadata update)"
    lines[0] = "|".join([*header_parts[:-1], new_version])
    source.write_text("\n".join(lines), encoding="utf-8")
    out = tmp_path / "index"

    initial = run_ingest(str(corpus), str(out))
    initial_generation = resolve_index_dir(out)
    initial_meta = (initial_generation / "index_meta.json").read_bytes()
    initial_manifest = (out / "active_index.json").read_bytes()

    unchanged = run_ingest(str(corpus), str(out))

    assert unchanged["noop"] is True
    assert (initial_generation / "index_meta.json").read_bytes() == initial_meta
    assert (out / "active_index.json").read_bytes() == initial_manifest

    source.write_text(
        source.read_text(encoding="utf-8").replace(
            new_version, f"{old_version} (new edition metadata)"
        ),
        encoding="utf-8",
    )
    updated = run_ingest(str(corpus), str(out))
    updated_generation = resolve_index_dir(out)
    document = next(iter(updated["documents"].values()))

    assert updated["index_version"] != initial["index_version"]
    assert updated_generation != initial_generation
    assert document["version"] == f"{old_version} (new edition metadata)"
    assert updated["chunks_embedded_this_run"] == 0
    assert (initial_generation / "index_meta.json").read_bytes() == initial_meta


def test_old_generation_remains_openable_and_queryable_after_publish(tmp_path):
    corpus = ROOT / "corpus" / "raw"
    out = tmp_path / "index"
    run_ingest(str(corpus), str(out))
    old_generation = resolve_index_dir(out)
    old_index = CorpusIndex(str(old_generation))

    run_ingest(str(corpus), str(out), reembed=True)

    new_generation = resolve_index_dir(out)
    new_index = CorpusIndex(str(new_generation))
    assert old_generation != new_generation
    assert old_generation.is_dir()
    assert old_index.search("ingredients", mode="lexical", k=3)
    assert new_index.search("ingredients", mode="lexical", k=3)


def test_concurrent_reader_observes_valid_generations_during_publish(
    tmp_path, monkeypatch
):
    from app.rag import ingest

    corpus = ROOT / "corpus" / "raw"
    out = tmp_path / "index"
    run_ingest(str(corpus), str(out))
    index = CorpusIndex(str(out))
    build_ready = threading.Event()
    publish_allowed = threading.Event()
    writer_finished = threading.Event()
    read_count = 0
    errors = []
    real_publish = ingest.publish_index

    def paused_publish(index_root, generation_dir):
        build_ready.set()
        if not publish_allowed.wait(timeout=10):
            raise TimeoutError("timed out waiting to publish test generation")
        real_publish(index_root, generation_dir)

    def read_until_writer_finishes():
        nonlocal read_count
        while not writer_finished.is_set():
            try:
                results = index.search("ingredients", mode="lexical", k=3)
                if not results:
                    errors.append("reader returned no results")
                read_count += 1
            except Exception as exc:
                errors.append(
                    f"{exc!r}; filename={getattr(exc, 'filename', None)!r}; "
                    f"winerror={getattr(exc, 'winerror', None)!r}"
                )
                break

    monkeypatch.setattr(ingest, "publish_index", paused_publish)

    with ThreadPoolExecutor(max_workers=2) as executor:
        reader = executor.submit(read_until_writer_finishes)

        def write_new_generation():
            try:
                run_ingest(str(corpus), str(out), reembed=True)
            finally:
                writer_finished.set()

        writer = executor.submit(write_new_generation)
        assert build_ready.wait(timeout=10)
        publish_allowed.set()
        writer.result(timeout=30)
        reader.result(timeout=30)

    index.search("ingredients", mode="lexical", k=3)
    assert read_count > 0
    assert errors == []
    assert index.dir == resolve_index_dir(out)


def test_hybrid_search_and_exact_clause_lookup_keep_source_metadata(index):
    exact = index.lookup("ldr-2020:reg 5(3)")
    hybrid = index.search("nutrition information per 100 grams", mode="hybrid", k=5)

    assert exact
    assert all(passage["clause_id"] == "LDR-2020:Reg 5(3)" for passage in exact)
    assert hybrid
    assert all(passage["doc_title"] and passage["doc_version"] for passage in hybrid)


def test_search_rejects_unknown_mode_and_nonpositive_limit(index):
    with pytest.raises(ValueError, match="unsupported retrieval mode"):
        index.search("nutrition", mode="semanticish")
    with pytest.raises(ValueError, match="at least 1"):
        index.search("nutrition", k=0)


def test_official_small_package_boundary_is_inclusive():
    from app.agents.assessor import draft_findings
    from app.samples import make

    source = parse_file(
        PDF_DIR / "Comp_Labelling Display_Version VIII_09_09_2025.pdf"
    )
    provision = next(chunk for chunk in source if chunk.clause_id == "LDR-2020:Reg 8")
    passage = {
        "chunk_id": provision.chunk_id,
        "doc_id": provision.doc_id,
        "clause_id": provision.clause_id,
        "text": provision.text,
    }

    findings = draft_findings(
        make(package_surface_area_cm2=100),
        {"claims": []},
        {provision.chunk_id: passage},
    )
    small_pack = next(item for item in findings if item["id"] == "R13_small_pack")

    assert small_pack["status"] == "needs_human"
    assert "at or below 100 cm2" in small_pack["detail"]
    assert small_pack["citations"][0]["quote"] in provision.text


def test_small_package_without_retrieved_evidence_at_boundary_needs_review():
    from app.agents.assessor import draft_findings
    from app.samples import make

    findings = draft_findings(
        make(package_surface_area_cm2=100),
        {"claims": []},
        {},
    )
    small_pack = next(item for item in findings if item["id"] == "R13_small_pack")

    assert small_pack["status"] == "needs_human"
    assert "at or below 100 cm2" in small_pack["detail"]
    assert small_pack["citations"] == []


def test_official_protein_rda_text_without_verified_value_needs_review():
    from app.agents.assessor import draft_findings
    from app.claims import detect_claims
    from app.samples import make

    source = parse_file(
        PDF_DIR / "Compendium_Advertising_Claims_Regulations_04_10_2022.pdf"
    )
    provision = next(
        chunk
        for chunk in source
        if chunk.clause_id == "ACR-2018:Schedule I/Protein"
        and "10% of RDA per 100 g" in chunk.text
    )
    passage = {
        "chunk_id": provision.chunk_id,
        "doc_id": provision.doc_id,
        "clause_id": provision.clause_id,
        "text": provision.text,
    }

    findings = draft_findings(
        make(
            front_of_pack_text=["Source of Protein"],
            nutrition={"protein_g": 8.0},
        ),
        {"claims": detect_claims(["Source of Protein"])},
        {provision.chunk_id: passage},
    )
    protein_claim = next(
        item for item in findings if item["id"] == "CLAIM:source_of_protein"
    )

    assert protein_claim["status"] == "needs_human"
    assert "no determination is made" in protein_claim["detail"]
