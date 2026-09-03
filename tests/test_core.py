from datetime import date
import tempfile
import unittest

from watchdog.db import Store
from watchdog.service import Watchdog


class CoreFlowTest(unittest.TestCase):
    def test_report_requires_stale_decisions_but_not_healthy_decisions(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            store = Store(database.name)
            store.add_project("owner/stale", 7, "Ship one small thing")
            store.add_project("owner/healthy", 7, "Keep moving")
            ids = {row["repo"]: row["id"] for row in store.projects()}
            report_id = store.create_report(
                date.today(),
                [
                    {
                        "project_id": ids["owner/stale"],
                        "days_idle": 8,
                        "hours_idle": 200,
                        "last_push": "2026-08-25T00:00:00+00:00",
                        "last_commit_message": "Implement the first useful slice",
                        "needs_decision": True,
                    },
                    {
                        "project_id": ids["owner/healthy"],
                        "days_idle": 1,
                        "hours_idle": 25,
                        "last_push": "2026-09-02T00:00:00+00:00",
                        "last_commit_message": "Update documentation",
                        "needs_decision": False,
                    },
                ],
            )

            text, markup = Watchdog(store, None).render(report_id, date.today().isoformat())
            self.assertIn("owner/stale", text)
            self.assertIn("owner/healthy", text)
            self.assertIn("#1 🔴 owner/stale", text)
            self.assertIn("last commit 200 hrs ago", text)
            self.assertIn("Last: Implement the first useful slice", text)
            self.assertEqual(len(markup.inline_keyboard[0]), 2)
            self.assertEqual(markup.inline_keyboard[0][0].text, "Work today (#1)")
            self.assertTrue(markup.inline_keyboard)
            self.assertFalse(store.acknowledge(report_id))

            store.decide(report_id, ids["owner/stale"], "today", date.today())
            self.assertTrue(store.acknowledge(report_id))


if __name__ == "__main__":
    unittest.main()
