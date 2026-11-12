import unittest

from webapp.api.app import _build_budgeted_context


class ContextBudgetTests(unittest.TestCase):
    def test_context_is_capped_and_preserves_every_source(self):
        sources = [
            {
                "citation": f"S{index}",
                "title": f"Document {index}",
                "page_start": index,
                "section": "PPE Matrix",
                "content": "safety requirement " * 500,
            }
            for index in range(1, 9)
        ]

        context, estimated_tokens = _build_budgeted_context(sources, token_budget=2000)

        self.assertLessEqual(estimated_tokens, 2000)
        for index in range(1, 9):
            self.assertIn(f"[S{index}]", context)


if __name__ == "__main__":
    unittest.main()
