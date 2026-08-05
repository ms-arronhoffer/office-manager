"""Pure-function tests for the pgvector ranking path in ``knowledge_service``.

These cover the cosine distance/similarity conversion, the relevance floors, and
the vector literal encoding. They deliberately touch no database so they stay
fast and can be executed directly, not just under the DB-backed pytest suite.
"""
import os

os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("JWT_SECRET", "test")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "test")

from app.services import knowledge_service as ks  # noqa: E402


class _Chunk:
    """Minimal stand-in matching the attributes ``_source_key`` reads."""

    def __init__(self, source_type="ticket", source_id="s1"):
        self.source_type = source_type
        self.source_id = source_id


def _scored(*scores, source_id="s1"):
    return [(s, "knowledge", _Chunk(source_id=f"{source_id}-{i}")) for i, s in enumerate(scores)]


# ── distance <-> similarity conversion ────────────────────────────────────────

def test_distance_zero_is_perfect_similarity():
    assert ks._similarity_from_distance(0.0) == 1.0


def test_distance_one_is_orthogonal():
    assert ks._similarity_from_distance(1.0) == 0.0


def test_distance_two_is_opposite():
    assert ks._similarity_from_distance(2.0) == -1.0


def test_conversion_is_the_inverse_of_python_cosine():
    """A pgvector distance must yield exactly what ``_cosine`` would have scored."""
    a = [1.0, 2.0, 3.0]
    b = [2.0, 1.0, 0.5]
    similarity = ks._cosine(a, b)
    distance = 1.0 - similarity
    assert abs(ks._similarity_from_distance(distance) - similarity) < 1e-12


def test_conversion_preserves_ranking_order():
    """Smaller distance must map to a larger similarity, never a silent inversion."""
    distances = [0.9, 0.1, 0.5]
    sims = [ks._similarity_from_distance(d) for d in distances]
    assert sorted(range(3), key=lambda i: distances[i]) == sorted(
        range(3), key=lambda i: -sims[i]
    )


# ── relevance floors ──────────────────────────────────────────────────────────

def test_absolute_floor_dominates_for_weak_best_match():
    # best 0.2 * 0.6 = 0.12, below the 0.15 absolute floor.
    assert ks._relevance_threshold(0.2) == ks.SEMANTIC_RELEVANCE_FLOOR


def test_relative_floor_dominates_for_strong_best_match():
    assert ks._relevance_threshold(0.9) == 0.9 * ks.SEMANTIC_RELATIVE_FLOOR_RATIO


def test_threshold_matches_original_formula():
    for best in (0.0, 0.05, 0.15, 0.25, 0.5, 0.75, 1.0):
        expected = max(
            ks.SEMANTIC_RELEVANCE_FLOOR, best * ks.SEMANTIC_RELATIVE_FLOOR_RATIO
        )
        assert ks._relevance_threshold(best) == expected


def test_select_relevant_drops_chunks_below_threshold():
    # best 0.9 -> threshold 0.54; only 0.9 and 0.6 survive.
    selected = ks._select_relevant(_scored(0.9, 0.6, 0.3, 0.1), limit=10)
    assert [round(s, 4) for s, _, _ in selected] == [0.9, 0.6]


def test_select_relevant_always_keeps_top_match_below_floor():
    selected = ks._select_relevant(_scored(0.05, 0.04), limit=10)
    assert len(selected) == 1
    assert selected[0][0] == 0.05


def test_select_relevant_honours_limit():
    selected = ks._select_relevant(_scored(0.9, 0.89, 0.88, 0.87), limit=2)
    assert len(selected) == 2


def test_select_relevant_caps_chunks_per_source():
    scored = [(0.9 - i * 0.01, "knowledge", _Chunk(source_id="same")) for i in range(6)]
    selected = ks._select_relevant(scored, limit=10)
    assert len(selected) == ks.MAX_CHUNKS_PER_SOURCE


def test_select_relevant_sorts_descending_by_similarity():
    selected = ks._select_relevant(_scored(0.6, 0.95, 0.8), limit=10)
    scores = [s for s, _, _ in selected]
    assert scores == sorted(scores, reverse=True)


def test_select_relevant_on_empty_input():
    assert ks._select_relevant([], limit=5) == []


def test_floors_applied_to_vector_scores_match_python_scores():
    """Ranking via converted distances must select the same set as raw cosines."""
    similarities = [0.92, 0.71, 0.55, 0.40, 0.12]
    distances = [1.0 - s for s in similarities]

    from_python = ks._select_relevant(_scored(*similarities), limit=10)
    from_vector = ks._select_relevant(
        _scored(*[ks._similarity_from_distance(d) for d in distances]), limit=10
    )
    assert [round(s, 6) for s, _, _ in from_python] == [
        round(s, 6) for s, _, _ in from_vector
    ]


# ── vector literal encoding ───────────────────────────────────────────────────

def test_vector_literal_format():
    assert ks._vector_literal([1.0, -0.5]) == "[1.0,-0.5]"


def test_vector_literal_accepts_ints():
    assert ks._vector_literal([1, 2]) == "[1.0,2.0]"


def test_vector_literal_round_trips_full_precision():
    values = [0.123456789012345, -0.987654321098765]
    parsed = [float(v) for v in ks._vector_literal(values).strip("[]").split(",")]
    assert parsed == values


def test_embedding_dim_matches_gemini_text_embedding_004():
    assert ks.EMBEDDING_DIM == 768
