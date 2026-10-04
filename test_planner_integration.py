import tempfile
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from main import main, seed_debug_data
from planner_state import restore, snapshot
from storage import PlannerStore
from timeline import MonthlyTimeline
from periodic_plan_designer import PeriodicPlanDesigner
from money_object import MoneyObjectSection


class PlannerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlannerStore(Path(self.temp.name) / "planner.sqlite3")
        self.timeline = MonthlyTimeline()
        seed_debug_data(self.timeline)
        self.timeline.store = self.store
        self.timeline._update_page()
        self.page = Mock()
        self.event = SimpleNamespace(control=SimpleNamespace(page=self.page))

    def dialog(self):
        return self.page.show_dialog.call_args.args[0]

    def test_shortfall_render_reload_and_resize(self):
        t = self.timeline
        t.add_item("Rent", month_index=0, amount=4800, payer_id="paycheck")
        self.assertEqual(sum(b.warning for b in t.months[0].boxes), 2)
        self.assertEqual(len([b for b in t.months[0].boxes if b.lane == "destination"]), 3)
        loaded = MonthlyTimeline()
        restore(loaded, self.store.load())
        self.assertEqual(snapshot(loaded), snapshot(t))
        loaded.store = self.store
        loaded._update_page()
        self.assertEqual(loaded.projection, t.projection)
        designer = PeriodicPlanDesigner(t, lambda: None)
        designer.resize(800)
        t.resize(900)
        self.assertEqual(sum(b.warning for b in t.months[0].boxes), 2)

    def test_edit_consumption_updates_payer_and_saved_balance(self):
        t = self.timeline
        box = t.add_item("Rent", month_index=0, amount=100, payer_id="paycheck")
        t.edit_box(box.box_id, self.event)
        dialog = self.dialog()
        dialog.content.controls[1].value = "200"
        dialog.content.controls[2].value = "savings"
        dialog.actions[1].on_click(None)
        saved = self.store.load()["consumption"][0]
        self.assertEqual(saved["payer_id"], "savings")
        self.assertEqual(saved["amount_cents"], 20000)
        t.remove_box(box.box_id, None)
        self.assertEqual(self.store.load()["consumption"], [])

    def test_consumption_delete_buttons_persist_and_recalculate(self):
        t = self.timeline
        first = t.add_item("Rent", month_index=0, amount=2000, payer_id="paycheck")
        second = t.add_item("Food", month_index=0, amount=100, payer_id="paycheck")
        card = t.connector.objects[first.box_id].control
        delete_button = card.content.controls[1].content.content.controls[1]
        self.assertEqual(delete_button.tooltip, "Delete consumption plan")
        delete_button.on_click(None)
        self.assertEqual(t.projection[0][1]["savings"]["incoming"], 440000)
        self.assertEqual(len(self.store.load()["consumption"]), 1)
        t.edit_box(second.box_id, self.event)
        self.dialog().actions[2].on_click(None)
        self.assertEqual(self.store.load()["consumption"], [])
        self.assertFalse(t.connector.view.visible)
        self.page.pop_dialog.assert_called_once()

    def test_edit_periodic_plan_updates_saved_edges(self):
        t = self.timeline
        t.edit_periodic_plan(t.periodic_plans[0], self.event)
        dialog = self.dialog()
        dialog.content.controls[2].value = "700"
        dialog.actions[1].on_click(None)
        self.assertEqual(self.store.load()["transfers"][0]["amount_cents"], 70000)
        self.assertEqual(t.periodic_edges[0].amount, 700)

    def test_drag_assignment_changes_calculation_and_connection(self):
        t = self.timeline
        box = t.add_item("Rent", month_index=0, amount=100, payer_id="paycheck")
        source = "projection:0:source:savings"
        t.connector.connections.append((source, box.box_id))
        t._assign_consumption_source(source, box.box_id)
        self.assertEqual(box.payer_id, "savings")
        self.assertIn((source, box.box_id), t.connector.connections)
        self.assertEqual(self.store.load()["consumption"][0]["payer_id"], "savings")

    def test_delete_object_cascades_and_last_object_can_be_deleted(self):
        t = self.timeline
        t.add_item("Rent", month_index=0, amount=100, payer_id="paycheck")
        for key in ("paycheck", "401k", "savings"):
            t.remove_money_object(key)
        saved = self.store.load()
        self.assertEqual(saved["objects"], [])
        self.assertEqual(saved["transfers"], [])
        self.assertEqual(saved["consumption"], [])

    def test_empty_startup_builds_home(self):
        empty_store = PlannerStore(Path(self.temp.name) / "empty.sqlite3")
        page = Mock(width=1000)
        with patch("main.PlannerStore", return_value=empty_store):
            main(page)
        page.add.assert_called_once()
        self.assertEqual(empty_store.load()["objects"], [])

    def test_resize_reuses_cards_and_redraws_connections_once(self):
        t = self.timeline
        t.add_item("Rent", month_index=0, amount=100, payer_id="paycheck")
        controls = {key: item.control for key, item in t.connector.objects.items()}
        with patch.object(t.connector, "_make_line", wraps=t.connector._make_line) as lines:
            with patch.object(t.connector, "_update_page") as updates:
                t.resize(900)
                self.assertEqual(lines.call_count, len(t.connector.connections))
                self.assertEqual(updates.call_count, 1)
                t.resize(900)
                self.assertEqual(updates.call_count, 1)
        for key, control in controls.items():
            self.assertIs(t.connector.objects[key].control, control)
            self.assertEqual(control.width, t._boxes[key].width)

    def test_timeline_shows_only_consumption_months_and_hides_after_removal(self):
        t = self.timeline
        self.assertFalse(t.connector.view.visible)
        self.assertEqual(t._visible_months(), [])
        self.assertEqual(len(t.projection), 12)
        box = t.add_item("Rent", month_index=2, amount=2000, payer_id="paycheck")
        self.assertEqual([month.index for month in t._visible_months()], [2])
        self.assertTrue(t.connector.view.visible)
        self.assertFalse(t.months[0].boxes)
        self.assertFalse(t.months[1].boxes)
        # January and February's transfers still accumulate in March.
        self.assertEqual(t.projection[2][1]["savings"]["closing"], 1350000)
        t.remove_box(box.box_id, None)
        self.assertFalse(t.connector.view.visible)
        self.assertFalse(any(month.boxes for month in t.months))

    def test_remainder_after_consumption_is_distinct_from_accumulated_savings(self):
        t = self.timeline
        t.add_item("Rent", month_index=0, amount=2000, payer_id="paycheck")
        savings = t.projection[0][1]["savings"]
        self.assertEqual(savings["incoming"], 250000)
        self.assertEqual(savings["closing"], 450000)
        card = t._boxes["projection:0:destination:savings"]
        self.assertEqual(card.amount, 4500)
        self.assertIn("Transfers in: $2,500.00", card.explanation)

    def test_resize_events_are_coalesced_and_height_changes_skipped(self):
        page = Mock(width=1000)
        with patch("main.PlannerStore", return_value=self.store):
            with patch("main.MonthlyTimeline", return_value=self.timeline):
                main(page)
        page.update.reset_mock()

        async def resize_burst():
            tasks = []
            for width in (1050, 1100, 1150):
                page.width = width
                tasks.append(asyncio.create_task(page.on_resize(None)))
                await asyncio.sleep(0)
            await asyncio.gather(*tasks)
            await page.on_resize(None)

        with patch.object(self.timeline, "resize") as resize:
            asyncio.run(resize_burst())
            resize.assert_called_once_with(1110)
        page.update.assert_called_once()

    def test_money_editor_saves_income_and_rename_preserves_relationships(self):
        t = self.timeline
        box = t.add_item("Rent", month_index=0, amount=100, payer_id="paycheck")
        section = MoneyObjectSection(t)
        section._show_editor(self.page, t.money_objects[0])
        dialog = self.dialog()
        dialog.content.controls[0].value = "Salary"
        dialog.content.controls[5].value = "6000"
        dialog.actions[1].on_click(None)
        saved = self.store.load()
        self.assertEqual(saved["objects"][0]["monthly_income_cents"], 600000)
        self.assertEqual(saved["objects"][0]["name"], "Salary")
        self.assertEqual(saved["transfers"][0]["source_id"], "paycheck")
        self.assertEqual(box.payer_id, "paycheck")
        self.assertEqual(t.projection[0][1]["savings"]["closing"], 740000)


if __name__ == "__main__":
    unittest.main()
