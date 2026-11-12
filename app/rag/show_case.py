"""Evaluation-1 helper: print the passages the section 4.1 case depends on and the values to test with.
   python -m app.rag.show_case"""
from .store import CorpusIndex

idx = CorpusIndex()
print(f"index {idx.version}  embedder {idx.meta['embedder']}  chunks {idx.meta['chunks']}\n")
q = "Is the claim 'source of protein' permitted given the protein content on the nutrition panel?"
print("A) What a single semantic search for the question returns (top 3):")
for p in idx.search(q, "semantic", k=3):
    print(f"   {p['clause_id']:34} score={p['score']}")
print("\nB) The passages the case actually depends on:")
for ref in ("LDR-2020:Reg 5(3)", "ACR-2018:Reg 5", "ACR-2018:Schedule I/Protein", "ACR-2018:Schedule I/NRV"):
    for p in idx.lookup(ref):
        print(f"   [{p['clause_id']}]\n     {p['text']}\n")
print("Values to test: protein_g = 4.0 (unmet, needs >= 6.0), 6.0 (met, boundary), 7.5 (met).  NRV 60 g x 10% = 6 g per 100 g.")
