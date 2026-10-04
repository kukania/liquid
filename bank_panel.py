"""Desktop Sandbox bank-link controls; all network work runs off the UI thread."""

import asyncio
import sqlite3
from urllib.parse import urlparse

import flet as ft

from banking import BankError, BankService


class BankPanel:
    def __init__(self, page, timeline, store, service=None):
        self.page, self.timeline = page, timeline
        self.service = service or BankService(store)
        self.busy = False
        self.status = ft.Text(size=12)
        self.cards = ft.Column()
        self.connect_button = ft.Button('Connect bank (Sandbox)', on_click=self.connect)
        self.finish_button = ft.Button('Check connection', on_click=self.finish, visible=False)
        self.cancel_button = ft.Button('Cancel connection', on_click=self.cancel, visible=False)
        self.view = ft.Column([
            ft.Text('Linked bank accounts', size=20, weight='bold'),
            ft.Text('Sandbox test accounts. Observed balances are separate from your forecast.', size=12),
            ft.Row([self.connect_button, self.finish_button, self.cancel_button], wrap=True),
            self.status, self.cards,
        ])
        self.render()

    async def run(self, action):
        # Serialize bank actions so repeated clicks cannot exchange the same token
        # twice or disconnect an account while its balances are being refreshed.
        if self.busy:
            return
        self.busy = True
        self.view.disabled = True
        self.status.value = 'Working...'
        self.page.update()
        try:
            await action()
        except BankError as error:
            self.status.value = str(error)
        except (sqlite3.Error, OSError):
            self.status.value = 'Could not save bank data. Please try again.'
        except (KeyError, TypeError, ValueError):
            self.status.value = 'The bank response was incomplete. Please try again.'
        finally:
            self.busy = False
            self.view.disabled = False
            self.connect_button.disabled = bool(self.service.link_token)
            self.finish_button.visible = bool(self.service.link_token)
            self.cancel_button.visible = bool(self.service.link_token)
            self.render()
            self.page.update()

    async def connect(self, _):
        async def action():
            # Network and database calls run on a worker thread. Flet control
            # changes stay here on the UI event loop to keep the window responsive.
            url = await asyncio.to_thread(self.service.start)
            parsed = urlparse(url)
            if parsed.scheme != 'https' or parsed.hostname != 'secure.plaid.com':
                raise BankError('Plaid returned an unexpected connection URL.')
            await self.page.launch_url(url)
            self.status.value = 'Complete Link in your browser, then click Check connection here.'
        await self.run(action)

    async def finish(self, _):
        async def action():
            count = await asyncio.to_thread(self.service.finish)
            if not count:
                self.status.value = 'Link has not completed. Finish in your browser, or cancel and try again.'
                return
            self.status.value = 'Connected. Fetching account balances...'
            for item in self.service.items():
                await asyncio.to_thread(self.service.refresh, item['id'])
            self.status.value = 'Connected. You can map accounts to existing money objects below.'
        await self.run(action)

    async def cancel(self, _):
        if self.busy:
            return
        self.service.link_token = None
        self.finish_button.visible = self.cancel_button.visible = False
        self.connect_button.disabled = False
        self.status.value = 'Connection cancelled locally. Close the Link browser tab.'
        self.page.update()

    async def refresh_item(self, item_id):
        async def action():
            await asyncio.to_thread(self.service.refresh, item_id)
            self.status.value = 'Latest available bank data fetched. Forecast unchanged.'
        await self.run(action)

    def confirm_disconnect(self, item_id):
        async def remove(_):
            self.page.pop_dialog()
            async def action():
                await asyncio.to_thread(self.service.disconnect, item_id)
                self.status.value = 'Disconnected. Local bank balances removed; plans preserved.'
            await self.run(action)
        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text('Disconnect bank?'),
            content=ft.Text('Revoke this connection and remove its locally stored bank balances and mappings?'),
            actions=[ft.Button('Cancel', on_click=lambda _: self.page.pop_dialog()),
                     ft.Button('Disconnect', on_click=remove)],
        ))

    def render(self):
        controls = []
        for item in self.service.items():
            item_id = item['id']
            async def refresh(_, selected=item_id):
                await self.refresh_item(selected)
            controls.append(ft.Row([
                ft.Text(item['institution'], weight='bold'),
                ft.Button('Refresh', on_click=refresh),
                ft.Button('Disconnect', on_click=lambda _, selected=item_id: self.confirm_disconnect(selected)),
            ], wrap=True))
            accounts = self.service.accounts(item_id)
            if not accounts:
                controls.append(ft.Text('No balances loaded. Click Refresh to fetch accounts.'))
            for account in accounts:
                def money(value):
                    return 'Unavailable' if value is None else f'{value / 100:,.2f}'
                async def map_account(event, selected=account['id']):
                    async def action():
                        await asyncio.to_thread(self.service.map_account, selected, event.control.value)
                        self.status.value = 'Account mapping saved. Forecast unchanged.'
                    await self.run(action)
                controls.append(ft.Container(padding=10, content=ft.Column([
                    ft.Text(f"{account['name']} (ending {account['mask'] or 'unknown'})"),
                    ft.Text(f"Current: {money(account['current_cents'])} | Available: "
                            f"{money(account['available_cents'])} {account['currency'] or '(currency unknown)'}"),
                    ft.Text(f"Fetched {account['fetched_at']}; bank data may be delayed.", size=11),
                    ft.Dropdown(label='Related money object (optional)',
                                value=account['money_object_id'] or '',
                                options=[ft.DropdownOption(key='', text='Not mapped')] + [
                                    ft.DropdownOption(key=obj.object_id, text=obj.name)
                                    for obj in self.timeline.money_objects], on_select=map_account),
                ])))
        self.cards.controls = controls or [ft.Text('No bank accounts connected.', size=12)]
