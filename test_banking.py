import asyncio
import logging
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError

from banking import BankError, BankService, PlaidClient, WindowsTokenVault
from bank_panel import BankPanel
from storage import PlannerStore
from test_projection import example
from main import seed_debug_data
from timeline import MonthlyTimeline
from periodic_plan_designer import PeriodicPlanDesigner
from planner_state import snapshot


class FakeVault:
    def seal(self, token):
        return ('protected:' + token).encode()

    def open(self, value):
        return value.decode().removeprefix('protected:')


class BankingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = PlannerStore(Path(self.folder.name) / 'test.sqlite3')
        self.store.save(example())
        self.client = Mock()
        self.service = BankService(self.store, self.client, FakeVault())

    def link(self):
        self.service.link_token = 'link-test'
        self.client.call.side_effect = [
            {'link_sessions': [{'results': {'item_add_results': [
                {'public_token': 'public-test', 'institution': {'name': 'Test Bank'}}]}}]},
            {'item_id': 'item', 'access_token': 'access-test'},
        ]
        self.assertEqual(self.service.finish(), 1)
        self.client.call.side_effect = None

    def refresh(self):
        self.client.call.return_value = {'accounts': [
            {'account_id': 'account', 'name': 'Checking', 'mask': '1234',
             'balances': {'current': 12.345, 'available': None, 'iso_currency_code': 'USD'}}]}
        self.service.refresh('item')

    def test_link_refresh_mapping_reload_and_planner_save(self):
        before = self.store.load()
        self.link()
        self.refresh()
        self.service.map_account('account', 'save')
        self.store.save(before)
        loaded = BankService(PlannerStore(self.store.path), self.client, FakeVault())
        account = loaded.accounts('item')[0]
        self.assertEqual(account['current_cents'], 1235)
        self.assertIsNone(account['available_cents'])
        self.assertEqual(account['money_object_id'], 'save')
        self.assertTrue(account['fetched_at'])
        self.assertEqual(self.store.load(), before)
        self.refresh()
        self.assertEqual(len(loaded.accounts('item')), 1)
        self.assertEqual(loaded.accounts('item')[0]['money_object_id'], 'save')

    def test_delete_object_unmaps_without_deleting_bank_account(self):
        self.link()
        self.refresh()
        self.service.map_account('account', 'save')
        state = self.store.load()
        state['transfers'] = []
        state['objects'] = [o for o in state['objects'] if o['id'] != 'save']
        self.store.save(state)
        self.assertIsNone(self.service.accounts('item')[0]['money_object_id'])

    def test_refresh_failure_preserves_last_snapshot(self):
        self.link()
        self.refresh()
        before = self.service.accounts('item')
        self.client.call.side_effect = BankError('Offline')
        with self.assertRaises(BankError):
            self.service.refresh('item')
        self.assertEqual(self.service.accounts('item'), before)

    def test_disconnect_revokes_before_local_removal(self):
        self.link()
        self.refresh()
        before = self.store.load()
        self.client.call.side_effect = BankError('Offline')
        with self.assertRaises(BankError):
            self.service.disconnect('item')
        self.assertEqual(len(self.service.items()), 1)
        self.client.call.side_effect = None
        self.service.disconnect('item')
        self.client.call.assert_called_with('/item/remove', access_token='access-test')
        self.assertEqual(self.service.items(), [])
        self.assertEqual(self.service.accounts('item'), [])
        self.assertEqual(self.store.load(), before)

    def test_pending_link_can_be_checked_again(self):
        self.service.link_token = 'link-test'
        self.client.call.return_value = {'link_sessions': []}
        self.assertEqual(self.service.finish(), 0)
        self.assertEqual(self.service.link_token, 'link-test')

    def test_sandbox_only_and_missing_credentials(self):
        with patch.dict(os.environ, {'PLAID_ENV': 'production'}):
            with self.assertRaisesRegex(BankError, 'Sandbox only'):
                PlaidClient().call('/accounts/get')
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(BankError, 'PLAID_CLIENT_ID'):
                PlaidClient().call('/accounts/get')

    def test_api_error_does_not_expose_response_secrets(self):
        error = HTTPError('https://sandbox.plaid.com/accounts/get', 400, 'bad', {},
                          io.BytesIO(b'{"error_code":"INVALID_API_KEYS","error_message":"secret-value"}'))
        with patch.dict(os.environ, {'PLAID_ENV': 'sandbox', 'PLAID_CLIENT_ID': 'id', 'PLAID_SECRET': 'secret'}):
            with patch('banking.urlopen', side_effect=error):
                with self.assertRaises(BankError) as caught:
                    PlaidClient().call('/accounts/get')
        self.assertNotIn('secret-value', str(caught.exception))

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_real_windows_vault(self):
        vault = WindowsTokenVault()
        sealed = vault.seal('sandbox-test-token')
        self.assertNotIn(b'sandbox-test-token', sealed)
        self.assertEqual(vault.open(sealed), 'sandbox-test-token')

    def test_panel_connection_flow_and_rendering(self):
        timeline = MonthlyTimeline()
        page = Mock()
        page.launch_url = AsyncMock()
        self.client.call.return_value = {'link_token': 'link-test',
                                         'hosted_link_url': 'https://secure.plaid.com/hl/test'}
        panel = BankPanel(page, timeline, self.store, self.service)
        asyncio.run(panel.connect(None))
        page.launch_url.assert_awaited_once()
        self.assertTrue(panel.finish_button.visible)
        self.link()
        self.refresh()
        panel.render()
        self.assertEqual(len(panel.cards.controls), 2)

    def test_migration_preserves_version_one_inputs(self):
        before = self.store.load()
        with self.store.connect() as db:
            db.execute('DROP TABLE bank_accounts')
            db.execute('DROP TABLE bank_items')
            db.execute('PRAGMA user_version=1')
        migrated = PlannerStore(self.store.path)
        self.assertEqual(migrated.load(), before)
        with migrated.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)


class DesignerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.timeline = MonthlyTimeline()
        seed_debug_data(self.timeline)
        self.designer = PeriodicPlanDesigner(self.timeline, lambda *args: None)

    def test_draft_edges_and_column_order_are_isolated(self):
        pair = next(iter(self.designer._edges))
        original = self.timeline.periodic_edges[0].amount
        self.designer._edges[pair].amount = 999
        self.assertEqual(self.timeline.periodic_edges[0].amount, original)
        order = list(self.timeline.destination_object_order)
        self.designer._destination_order.reverse()
        self.designer._snap_column('destination')
        self.assertEqual(self.timeline.destination_object_order, order)

    def test_externally_funded_self_transfer_rejected(self):
        self.designer._add_node(self.timeline.money_objects[0], 'destination')
        pair = ('source:paycheck', 'destination:paycheck')
        self.designer.connector.connections.append(pair)
        self.designer._connections_changed()
        self.assertNotIn(pair, self.designer.connector.connections)

    def test_transfer_snapshot_uses_stable_ids_after_name_changes(self):
        self.timeline.money_objects[0].name = 'Changed outside the editor'
        state = snapshot(self.timeline)
        self.assertEqual(state['transfers'][0]['source_id'], 'paycheck')


if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    unittest.main()
