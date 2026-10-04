"""Sandbox-only Plaid service. Bank observations never change planning inputs."""

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from projection import cents


class BankError(Exception):
    """A safe, user-facing banking error (never contains tokens)."""


class WindowsTokenVault:
    """Encrypt tokens with Windows DPAPI for the current Windows user."""

    def _crypt(self, value, decrypt=False):
        if os.name != 'nt':
            raise BankError('Bank linking currently requires Windows token protection.')

        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

        buffer = ctypes.create_string_buffer(value)
        # DPAPI expects a byte count and a pointer, rather than a Python string.
        # Keep this buffer alive until the native call has finished reading it.
        source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        target = Blob()
        crypt = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(Blob)]
        function.restype = wintypes.BOOL
        if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
            raise BankError('Windows could not unlock or protect the bank connection token.')
        try:
            return ctypes.string_at(target.data, target.size)
        finally:
            # Windows allocated this output; its own allocator must release it.
            kernel.LocalFree(target.data)

    def seal(self, token):
        return self._crypt(token.encode())

    def open(self, blob):
        return self._crypt(bytes(blob), decrypt=True).decode()


class PlaidClient:
    """Make authenticated Sandbox requests without exposing raw errors to the UI."""
    def call(self, endpoint, **payload):
        if os.getenv('PLAID_ENV', 'sandbox') != 'sandbox':
            raise BankError('This build supports Plaid Sandbox only.')
        client_id, secret = os.getenv('PLAID_CLIENT_ID'), os.getenv('PLAID_SECRET')
        if not client_id or not secret:
            raise BankError('Set PLAID_CLIENT_ID and PLAID_SECRET to your Sandbox keys, then restart.')
        request = Request('https://sandbox.plaid.com' + endpoint,
                          data=json.dumps(dict(payload, client_id=client_id, secret=secret)).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as error:
            try:
                code = json.load(error).get('error_code')
            except (ValueError, OSError):
                code = None
            messages = {
                'ITEM_LOGIN_REQUIRED': 'Bank authorization expired. Disconnect and link again in Sandbox.',
                'INVALID_LINK_TOKEN': 'This connection session expired. Cancel it and connect again.',
                'INVALID_API_KEYS': 'Plaid rejected your Sandbox API keys.',
                'PRODUCT_NOT_READY': 'Bank data is still being prepared. Try Refresh shortly.',
            }
            raise BankError(messages.get(code, 'Plaid could not complete this request. Please try again.')) from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise BankError('Could not reach Plaid or read its response. Please try again.') from None


class BankService:
    """Coordinate Link, encrypted credentials, and separately stored bank balances.

    A Plaid Item represents a bank login; one Item can contain several accounts.
    Account-to-money-object mappings are optional and do not change forecasts.
    """
    def __init__(self, store, client=None, vault=None):
        self.store = store
        self.client = client or PlaidClient()
        self.vault = vault or WindowsTokenVault()
        self.link_token = None
        self.completed = set()

    def start(self):
        """Create a temporary Link session and return its browser URL."""
        # Check protected storage before creating an external connection.
        self.vault.open(self.vault.seal('probe'))
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS bank_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('INSERT OR IGNORE INTO bank_settings VALUES (?, ?)', ('user_id', uuid4().hex))
            user_id = db.execute('SELECT value FROM bank_settings WHERE key=?', ('user_id',)).fetchone()[0]
        result = self.client.call('/link/token/create', user={'client_user_id': user_id},
                                  client_name='Liquid Sandbox', products=['transactions'],
                                  country_codes=['US'], language='en', hosted_link={})
        self.link_token = result['link_token']
        self.completed.clear()
        return result['hosted_link_url']

    def finish(self):
        """Check the browser session and store credentials for completed logins."""
        if not self.link_token:
            raise BankError('Start a bank connection first.')
        result = self.client.call('/link/token/get', link_token=self.link_token)
        linked = 0
        for session in result.get('link_sessions', []):
            for item in (session.get('results') or {}).get('item_add_results', []):
                public_token = item.get('public_token')
                if not public_token or public_token in self.completed:
                    continue
                exchanged = self.client.call('/item/public_token/exchange', public_token=public_token)
                # The public token is a short-lived exchange credential. Keep only
                # the resulting access token, encrypted, for later account requests.
                token, item_id = exchanged['access_token'], exchanged['item_id']
                try:
                    sealed = self.vault.seal(token)
                    with self.store.connect() as db:
                        db.execute('INSERT INTO bank_items VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET token=excluded.token',
                                   (item_id, sealed, (item.get('institution') or {}).get('name', 'Bank')))
                except Exception:
                    # Best effort revoke if we cannot retain the new credential.
                    try:
                        self.client.call('/item/remove', access_token=token)
                    except BankError:
                        pass
                    raise BankError('Could not save the bank connection. Please start again.') from None
                self.completed.add(public_token)
                linked += 1
        if linked:
            self.link_token = None
        return linked

    def items(self):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('SELECT id, institution FROM bank_items ORDER BY rowid')]

    def accounts(self, item_id):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM bank_accounts WHERE item_id=? ORDER BY rowid', (item_id,))]

    def _token(self, item_id):
        with self.store.connect() as db:
            row = db.execute('SELECT token FROM bank_items WHERE id=?', (item_id,)).fetchone()
        if row is None:
            raise BankError('Bank connection no longer exists.')
        return self.vault.open(row['token'])

    def refresh(self, item_id):
        """Fetch cached bank balances, then replace observations in one transaction."""
        result = self.client.call('/accounts/get', access_token=self._token(item_id))
        fetched_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        rows = []
        for account in result['accounts']:
            balance = account['balances']
            # Keep unknown balances unknown. Do not treat them as zero.
            rows.append((account['account_id'], item_id, account['name'], account.get('mask'),
                         balance.get('iso_currency_code') or balance.get('unofficial_currency_code'),
                         None if balance.get('current') is None else cents(balance['current']),
                         None if balance.get('available') is None else cents(balance['available']), fetched_at))
        with self.store.connect() as db:
            for row in rows:
                # Do not overwrite money_object_id: the user's mapping must survive
                # refreshes, even if the bank changes the account's display name.
                db.execute('''INSERT INTO bank_accounts
                    (id, item_id, name, mask, currency, current_cents, available_cents, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, mask=excluded.mask, currency=excluded.currency,
                    current_cents=excluded.current_cents, available_cents=excluded.available_cents,
                    fetched_at=excluded.fetched_at''', row)
            current_ids = {row[0] for row in rows}
            for row in db.execute('SELECT id FROM bank_accounts WHERE item_id=?', (item_id,)).fetchall():
                if row['id'] not in current_ids:
                    db.execute('DELETE FROM bank_accounts WHERE id=?', (row['id'],))

    def map_account(self, account_id, money_object_id):
        """Record a relationship only; never copy a live balance into January."""
        with self.store.connect() as db:
            db.execute('UPDATE bank_accounts SET money_object_id=? WHERE id=?',
                       (money_object_id or None, account_id))

    def disconnect(self, item_id):
        # Keep local credentials if revocation fails, so it can be retried.
        self.client.call('/item/remove', access_token=self._token(item_id))
        with self.store.connect() as db:
            db.execute('DELETE FROM bank_items WHERE id=?', (item_id,))
