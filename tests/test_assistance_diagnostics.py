import unittest

from aegis.simulation import create_scenario
from aegis_api.main import Runtime, _snapshot


class AssistanceDiagnosticsTests(unittest.TestCase):
    def test_snapshot_explains_blocked_exit_path_and_location(self):
        state = create_scenario(2, 417, "Fire / smoke")
        person = state.people[0]
        person.status = "Needs Assistance"
        state.blocked_edges.update(state.building.edges)

        snapshot = _snapshot("diagnostic-test", Runtime(state, "Office"))
        record = next(item for item in snapshot["people"] if item["id"] == person.id)

        self.assertIn("No open path", record["assistance_reason"])
        self.assertTrue(record["assistance_blockers"])
        self.assertIn("closed", record["assistance_blockers"][0])
        self.assertEqual(record["current_node"], person.current_node)


if __name__ == "__main__":
    unittest.main()
