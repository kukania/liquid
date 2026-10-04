import copy
import tempfile
import unittest
from pathlib import Path
import sqlite3

from projection import calculate, cents
from storage import PlannerStore


def example():
    return dict(
        objects=[dict(id=key, name=key, category="Account", starting_cents=balance,
                      monthly_income_cents=income, funding_type="From outside", external_source="Paycheck")
                 for key, balance, income in [("pay", 0, 500000), ("401k", 1000000, 0), ("save", 200000, 0)]],
        transfers=[dict(id="a", source_id="pay", destination_id="401k", amount_cents=50000,
                        use_rest=0, priority=1, start_month=0, end_month=11, title="Retirement"),
                   dict(id="b", source_id="pay", destination_id="save", amount_cents=0,
                        use_rest=1, priority=2, start_month=0, end_month=11, title="Rest")],
        consumption=[dict(id="c", payer_id="pay", month=0, title="Rent", amount_cents=100000)],
        settings={"projection_start": 0, "projection_end": 11})


class ProjectionTests(unittest.TestCase):
    def run_state(self, state):
        return calculate(state["objects"], state["transfers"], state["consumption"])

    def test_consumption_before_transfers_and_carry_forward(self):
        state = example()
        results = self.run_state(state)
        jan, feb = results[0][1], results[1][1]
        self.assertEqual(jan["save"]["closing"], 550000)
        self.assertEqual(jan["401k"]["closing"], 1050000)
        self.assertEqual(feb["save"]["opening"], 550000)
        self.assertEqual(feb["save"]["closing"], 1000000)
        self.assertEqual(sum(v["closing"] for v in jan.values()), 1600000)

    def test_shortfall_skips_fixed_then_runs_rest(self):
        state = example()
        state["consumption"][0]["amount_cents"] = 480000
        jan = self.run_state(state)[0][1]
        self.assertEqual(jan["401k"]["closing"], 1000000)
        self.assertEqual(jan["save"]["closing"], 220000)
        self.assertIn("shortfall $300.00", jan["pay"]["issues"][0])
        self.assertEqual(jan["pay"]["issues"], jan["401k"]["issues"])

    def test_negative_consumption_balance_never_transfers_negative_rest(self):
        state = example()
        state["consumption"][0]["amount_cents"] = 600000
        jan = self.run_state(state)[0][1]
        self.assertEqual(jan["pay"]["closing"], -100000)
        self.assertEqual(jan["save"]["closing"], 200000)

    def test_transfer_dates_and_idle_balances(self):
        state = example()
        for plan in state["transfers"]:
            plan["start_month"] = plan["end_month"] = 1
        results = self.run_state(state)
        self.assertEqual(results[0][1]["pay"]["closing"], 400000)
        self.assertEqual(results[1][1]["save"]["closing"], 1050000)
        self.assertEqual(results[2][1]["save"]["closing"], 1050000)

    def test_missing_payer_rejected_and_inputs_unchanged(self):
        state = example()
        original = copy.deepcopy(state)
        self.run_state(state)
        self.assertEqual(state, original)
        state["consumption"][0]["payer_id"] = "missing"
        with self.assertRaises(ValueError):
            self.run_state(state)

    def test_cent_precision(self):
        self.assertEqual(cents("1.005"), 101)
        for value in ("nan", "inf", "abc"):
            with self.assertRaises(ValueError):
                cents(value)

    def test_sqlite_roundtrip_and_transaction_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PlannerStore(Path(folder) / "test.sqlite3")
            state = example()
            store.save(state)
            self.assertEqual(store.load(), state)
            broken = copy.deepcopy(state)
            broken["consumption"][0]["payer_id"] = "missing"
            with self.assertRaises(sqlite3.IntegrityError):
                store.save(broken)
            self.assertEqual(store.load(), state)
            self.assertEqual(self.run_state(store.load()), self.run_state(state))


if __name__ == "__main__":
    unittest.main()
