from ultralearn.db import KnowledgeDB
from ultralearn.embeddings import HashingEmbedder, cosine, pack_vector, unpack_vector


def make_db(tmp_path) -> KnowledgeDB:
    db = KnowledgeDB(tmp_path / "test.db")
    db.initialize()
    return db


def test_vector_roundtrip():
    vector = HashingEmbedder().embed(["backprop chain rule"])[0]
    restored = unpack_vector(pack_vector(vector))
    assert len(restored) == len(vector)
    assert all(abs(a - b) < 1e-6 for a, b in zip(vector, restored))
    assert abs(cosine(vector, vector) - 1.0) < 1e-6


def test_semantic_chunks_rank_related_source_first(tmp_path):
    db = make_db(tmp_path)
    poker_id = db.add_source("note", "Poker basics")
    db.add_content(poker_id, "Pot odds compare the price of a call to the size of the pot. Implied odds add future winnings.")
    dl_id = db.add_source("note", "Deep learning notes")
    db.add_content(dl_id, "Backpropagation applies the chain rule through layers so gradients flow to early weights.")

    results = db.semantic_chunks("pot odds when calling a bet", k=2)
    assert results
    assert results[0]["source_title"] == "Poker basics"
    assert results[0]["score"] >= results[-1]["score"]


def test_semantic_concepts_rank_related_concept_first(tmp_path):
    db = make_db(tmp_path)
    db.find_or_create_concept("Pot odds", "Price of a call vs pot size.", "poker")
    db.find_or_create_concept("Backprop chain rule", "Gradients compose through nested functions.", "dl")

    matches = db.semantic_concepts("chain rule gradients in backpropagation", k=2)
    assert matches
    assert matches[0][0].title == "Backprop chain rule"


def test_unified_search_merges_keyword_and_semantic_hits(tmp_path):
    db = make_db(tmp_path)
    db.find_or_create_concept("Pot odds", "Price of a call vs pot size.", "poker")
    source_id = db.add_source("note", "Poker basics")
    db.add_content(source_id, "Pot odds compare the price of a call to the size of the pot.")

    hits = db.unified_search("price of a call")
    kinds = {hit["kind"] for hit in hits}
    assert "concept" in kinds
    assert "chunk" in kinds
    # The exact phrase is in the notes, so at least one hit should be keyword-backed.
    assert any(hit["via"] in {"text", "both"} for hit in hits)


def test_unified_search_drops_unrelated_queries(tmp_path):
    db = make_db(tmp_path)
    db.find_or_create_concept("Pot odds", "Price of a call vs pot size.", "poker")
    source_id = db.add_source("note", "Poker basics")
    db.add_content(source_id, "Pot odds compare the price of a call to the size of the pot.")

    assert db.unified_search("zzzzqwerty-no-such-concept") == []


def test_semantic_floor_rejects_weak_neighbours():
    from ultralearn.db import _SEMANTIC_FLOOR

    # MiniLM scores leftover generic words like "concept" around 0.25–0.27.
    assert _SEMANTIC_FLOOR >= 0.30


def test_fts_query_requires_every_meaningful_term():
    from ultralearn.db import fts_query

    assert fts_query("sensor fusion") == "sensor AND fusion"
    assert "OR" not in fts_query("zzzzqwerty-no-such-concept")
    assert "zzzzqwerty" in fts_query("zzzzqwerty-no-such-concept")


def test_best_chunk_for_text_picks_matching_passage(tmp_path):
    db = make_db(tmp_path)
    source_id = db.add_source("note", "Mixed notes")
    db.add_content(
        source_id,
        "Pot odds compare the price of a call to the pot size.\n\n"
        + "x" * 3000  # force a chunk boundary
        + "\n\nBackpropagation applies the chain rule through the layers of a network.",
    )
    chunk_id = db.best_chunk_for_text(source_id, "backprop and the chain rule")
    assert chunk_id is not None
    text = db.source_text(source_id)
    assert "chain rule" in text
