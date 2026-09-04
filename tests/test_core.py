from datetime import date
import tempfile
import unittest

from watchdog.db import Store
from watchdog.service import Watchdog


class CoreFlowTest(unittest.TestCase):
    def test_pending_task_can_be_registered_then_linked(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            store = Store(database.name)
            first = store.add_pending_task("AI wiki expansion")
            duplicate = store.add_pending_task("AI wiki expansion")
            self.assertEqual(first, "P-0001")
            self.assertEqual(duplicate, first)
            self.assertEqual(len(store.pending_tasks()), 1)

            store.add_project("owner/ai-wiki", 1, first)
            store.mark_pending_linked(first, "owner/ai-wiki")
            self.assertEqual(store.pending_tasks(), [])
            self.assertEqual(store.projects()[0]["next_action"], "P-0001")

    def test_pending_task_appears_in_report_and_requires_decision(self):
        with tempfile.NamedTemporaryFile(suffix=".sqlite3") as database:
            store = Store(database.name)
            store.add_pending_task("AI wiki expansion")
            pending_id = store.pending_tasks()[0]["id"]
            report_id = store.create_report(date.today(), [])

            text, markup = Watchdog(store, None).render(report_id, date.today().isoformat())
            self.assertIn("P-0001 — AI wiki expansion", text)
            self.assertIn("Repo: not attached", text)
            self.assertEqual(markup.inline_keyboard[0][0].text, "Work today (#1)")
            self.assertFalse(store.acknowledge(report_id))

            store.decide_pending(report_id, pending_id, "today", date.today())
            self.assertTrue(store.acknowledge(report_id))

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

            replacement = [
                {
                    "project_id": ids["owner/healthy"],
                    "days_idle": 0,
                    "hours_idle": 2,
                    "last_push": "2026-09-03T00:00:00+00:00",
                    "last_commit_message": "A newer commit",
                    "needs_decision": False,
                }
            ]
            store.replace_report_items(report_id, replacement)
            refreshed = store.report_items(report_id)
            self.assertEqual(len(refreshed), 1)
            self.assertEqual(refreshed[0]["repo"], "owner/healthy")


if __name__ == "__main__":
    unittest.main()
