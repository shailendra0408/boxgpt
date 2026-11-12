import unittest

from webapp.api.rag_adapter import (
    build_relaxed_lexical_query,
    merge_neighbor_results,
    select_hybrid_results,
)


def candidate(chunk_id: int, embedding: list[float], rrf: float) -> dict:
    return {
        "id": chunk_id,
        "embedding": embedding,
        "rrf": rrf,
    }


class HybridSelectionTests(unittest.TestCase):
    def test_relaxed_lexical_query_ignores_typo_and_uses_or(self):
        query = build_relaxed_lexical_query(
            "Whjat PPE is required for GCT water spray nozzle inspection?"
        )

        self.assertEqual(query, "ppe OR gct OR water OR spray OR nozzle OR inspection")

    def test_neighbor_merge_deduplicates_and_caps_context(self):
        base = [{"id": 10}, {"id": 20}, {"id": 30}, {"id": 40}]
        neighbors = [{"id": 9}, {"id": 20}, {"id": 11}, {"id": 21}, {"id": 41}]

        results = merge_neighbor_results(base, neighbors, max_context_chunks=8)

        self.assertEqual([item["id"] for item in results], [10, 20, 30, 40, 9, 11, 21, 41])

    def test_exact_lexical_result_survives_mmr(self):
        fused = {
            1: candidate(1, [1.0, 0.0], 0.040),
            2: candidate(2, [0.9, 0.1], 0.035),
            99: candidate(99, [0.0, 1.0], 0.020),
        }

        results = select_hybrid_results(
            fused=fused,
            keyword_chunk_ids=[99],
            query_vector=[1.0, 0.0],
            limit=2,
            candidates=3,
            mmr_lambda=0.72,
            lexical_reserved_slots=1,
        )

        self.assertEqual([item["id"] for item in results], [99, 1])
        self.assertEqual(results[0]["selection_reason"], "lexical_reserved")

    def test_no_lexical_match_uses_mmr_for_all_slots(self):
        fused = {
            1: candidate(1, [1.0, 0.0], 0.040),
            2: candidate(2, [0.8, 0.2], 0.030),
        }

        results = select_hybrid_results(
            fused=fused,
            keyword_chunk_ids=[],
            query_vector=[1.0, 0.0],
            limit=2,
            candidates=2,
            mmr_lambda=0.72,
            lexical_reserved_slots=1,
        )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(item["selection_reason"] == "mmr" for item in results))

    def test_reserved_result_is_not_duplicated(self):
        fused = {
            1: candidate(1, [1.0, 0.0], 0.040),
            2: candidate(2, [0.5, 0.5], 0.030),
        }

        results = select_hybrid_results(
            fused=fused,
            keyword_chunk_ids=[1],
            query_vector=[1.0, 0.0],
            limit=2,
            candidates=2,
            mmr_lambda=0.72,
            lexical_reserved_slots=1,
        )

        self.assertEqual([item["id"] for item in results], [1, 2])


if __name__ == "__main__":
    unittest.main()
