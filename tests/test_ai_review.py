import json
import unittest

from aegis.simulation import create_scenario
from aegis_api.main import Runtime, _ai_review_context, _validated_ai_items


class AIReviewContextTests(unittest.TestCase):
    def test_context_uses_synthetic_simulation_facts_for_selected_person(self):
        state = create_scenario(4, 417, "Fire / smoke")
        selected = state.people[0]
        context = _ai_review_context(Runtime(state, "Office"), selected.id)

        self.assertEqual(context["selected_person"]["id"], selected.id)
        self.assertTrue(context["hazards"])
        fact_ids = {fact["id"] for fact in context["facts"]}
        self.assertIn(f"person:{selected.id}", fact_ids)
        self.assertTrue(any(fact_id.startswith("hazard:") for fact_id in fact_ids))
        self.assertIn("synthetic AEGIS simulation state", context["source"])
        serialized = json.dumps(context)
        self.assertNotIn("site_address", serialized)
        self.assertNotIn("callback_number", serialized)

    def test_ai_items_with_unknown_evidence_are_discarded(self):
        result = _validated_ai_items(
            [
                {"text": "Grounded observation", "evidence": ["hazard:H1", "not-a-fact"]},
                {"text": "Unsupported claim", "evidence": ["not-a-fact"]},
            ],
            {"hazard:H1": "H1 fire is at the north room."},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "Grounded observation")
        self.assertEqual(result[0]["evidence"][0]["id"], "hazard:H1")


if __name__ == "__main__":
    unittest.main()
