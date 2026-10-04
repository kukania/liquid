"""Application entry point for the consumption-plan timeline."""

import logging
import asyncio
from pathlib import Path

import flet as ft

from money_object import FUNDING_FROM_OUTSIDE, MoneyObject, MoneyObjectSection
from periodic_plan import PeriodicPlanEdge
from periodic_plan_designer import PeriodicPlanDesigner
from timeline import MONTH_NAMES, MonthlyTimeline
from planner_state import restore
from storage import PlannerStore
from projection import cents
from bank_panel import BankPanel


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)


def seed_debug_data(timeline):
    """Start a fresh session with an editable example transfer graph."""
    timeline.set_money_objects([
        MoneyObject("paycheck", "Paycheck", category="Income", current_amount=0, monthly_income=5000,
                    funding_type=FUNDING_FROM_OUTSIDE, external_source="Paycheck"),
        MoneyObject("401k", "401K", category="Investment", current_amount=10000),
        MoneyObject("savings", "Savings", category="Account", current_amount=2000),
    ])
    timeline.source_object_order = ["paycheck"]
    timeline.destination_object_order = ["401k", "savings"]
    timeline.replace_periodic_edge_plans([
        PeriodicPlanEdge("source:paycheck", "destination:401k", amount=500, priority=1),
        PeriodicPlanEdge("source:paycheck", "destination:savings", use_rest=True, priority=2),
    ])
    timeline._sync_periodic_plans_for_month(0)


def main(page: ft.Page):
    page.title = "Consumption Plan"
    page.bgcolor = "#F5F7FB"
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    timeline = MonthlyTimeline(width=max(640, (page.width or 1000) - 40))
    store = PlannerStore(Path(__file__).with_name("planner.sqlite3"))
    # Rebuild the UI from saved inputs before enabling automatic saves. Otherwise,
    # constructing the first few controls could save a partially restored plan.
    restore(timeline, store.load())
    timeline.store = store
    timeline._update_page()
    timeline_scroller = ft.Row(
        [timeline.connector.view],
        scroll=ft.ScrollMode.AUTO,
    )
    money_object_section = MoneyObjectSection(timeline)
    bank_panel = BankPanel(page, timeline, store)
    # Banking has its own records and controls: a refresh must never replace the
    # January starting balances used by the planning calculator.
    active_designer = None
    root = ft.Container()
    page_status = ft.Text(size=12, color=ft.Colors.GREEN_700)

    title_input = ft.TextField(
        label="Timeline item title",
        hint_text="Leave empty for an automatic title",
        col={"xs": 12, "md": 5},
    )
    month_input = ft.Dropdown(
        label="Month",
        value="0",
        col={"xs": 6, "md": 3},
        options=[
            ft.DropdownOption(key=str(index), text=month)
            for index, month in enumerate(MONTH_NAMES)
        ],
    )
    amount_input = ft.TextField(
        label="Amount ($)",
        col={"xs": 6, "md": 2},
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    timeline_status = ft.Text(size=12, color=ft.Colors.RED_700)
    payer_input = ft.Dropdown(label="Pay from", col={"xs": 12, "md": 4})

    def refresh_payers(*_):
        bank_panel.render()
        payer_input.options = [ft.DropdownOption(key=obj.object_id, text=obj.name)
                               for obj in timeline.money_objects]
        if payer_input.value not in {obj.object_id for obj in timeline.money_objects}:
            payer_input.value = timeline.money_objects[0].object_id if timeline.money_objects else None

    refresh_payers()
    money_object_section.on_changed = refresh_payers

    def load_example(_):
        if timeline.money_objects or timeline.periodic_plans:
            page_status.value = "Example data is available only in an empty planner."
            page.update()
            return
        timeline.store = None
        try:
            seed_debug_data(timeline)
        finally:
            timeline.store = store
        timeline._update_page()
        money_object_section.refresh()
        refresh_payers()
        page_status.value = "Example loaded. Changes are saved automatically."
        page.update()

    def add_timeline_item(_):
        try:
            amount = cents(amount_input.value or 0) / 100
        except ValueError:
            timeline_status.value = "Amount must be a number."
            page.update()
            return
        if amount < 0:
            timeline_status.value = "Amount must be zero or greater."
            page.update()
            return
        if not payer_input.value:
            timeline_status.value = "Create a money object and choose who pays."
            page.update()
            return
        timeline.add_item(
            title_input.value,
            month_index=int(month_input.value),
            amount=amount,
            payer_id=payer_input.value,
        )
        title_input.value = ""
        amount_input.value = ""
        timeline_status.value = ""
        page.update()

    def show_home(message=""):
        nonlocal home_view, active_designer
        active_designer = None
        timeline.resize((page.width or 1000) - 40)
        logger.info(
            "show_home begin message=%r plans=%d edges=%d cards=%d",
            message,
            len(timeline.periodic_plans),
            len(timeline.periodic_edges),
            len(timeline.periodic_plans_view.controls),
        )
        page_status.value = message
        money_object_section.refresh()
        refresh_payers()
        timeline._update_page()
        # Fully detach the designer before restoring the reusable home controls.
        # This prevents Flet from retaining a stale child in a rebuilt plan list.
        root.content = None
        if root.page is not None:
            page.update()
        old_plan_view = timeline.periodic_plans_view
        new_plan_view = timeline.rebuild_periodic_plans_view()
        home_view = ft.Column(
            [
                new_plan_view if control is old_plan_view else control
                for control in home_view.controls
            ],
            spacing=15,
        )
        root.content = home_view
        page.scroll = ft.ScrollMode.AUTO
        if root.page is not None:
            page.update()
        logger.info(
            "show_home complete plans=%d cards=%d",
            len(timeline.periodic_plans),
            len(timeline.periodic_plans_view.controls),
        )

    def show_periodic_designer(_):
        nonlocal active_designer
        designer = PeriodicPlanDesigner(timeline, on_close=show_home)
        designer.resize((page.width or 1000) - 40)
        active_designer = designer
        root.content = designer.view
        page.scroll = ft.ScrollMode.AUTO
        page.update()

    home_view = ft.Column(
        [
            ft.Text("Consumption Plan", size=28, weight="bold"),
            ft.Text(
                "Plan cash flow and other forms of consumption over time.",
                color=ft.Colors.GREY_700,
            ),
            ft.ResponsiveRow(
                [
                    title_input,
                    month_input,
                    amount_input,
                    payer_input,
                    ft.Button(
                        "Add consumption",
                        on_click=add_timeline_item,
                        col={"xs": 12, "md": 2},
                    ),
                ],
                spacing=12,
            ),
            timeline_status,
            ft.Text(
                "Only months with consumption are shown. Savings shows accumulated closing balances, "
                "including starting money. Click a balance card to see consumption and transfers.",
                size=12,
                color=ft.Colors.GREY_700,
            ),
            ft.Divider(),
            money_object_section.view,
            bank_panel.view,
            ft.Button("Load example data", on_click=load_example),
            ft.Text("Saved automatically • January–December projection • Consumption runs before transfers.", size=12),
            ft.Divider(),
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Periodic plans", size=20, weight="bold"),
                            ft.Text(
                                "Each source has its own high-to-low transfer priority.",
                                size=12,
                                color=ft.Colors.GREY_700,
                            ),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Button(
                        "Open periodic plan designer",
                        icon=ft.Icons.ACCOUNT_TREE,
                        on_click=show_periodic_designer,
                    ),
                ]
            ),
            page_status,
            timeline.periodic_plans_view,
            ft.Divider(),
            timeline_scroller,
        ],
        spacing=15,
    )

    root.content = home_view
    resize_revision = 0
    last_resize_width = page.width

    async def resize_page(_):
        nonlocal resize_revision, last_resize_width
        resize_revision += 1
        revision = resize_revision
        # Wait for a brief pause while the user drags the window edge.
        await asyncio.sleep(0.12)
        if revision != resize_revision or page.width == last_resize_width:
            return
        last_resize_width = page.width
        target = active_designer or timeline
        target.connector.suspend_updates = True
        try:
            target.resize((page.width or 1000) - 40)
        finally:
            target.connector.suspend_updates = False
        page.update()

    page.on_resize = resize_page
    page.add(root)


if __name__ == "__main__":
    ft.run(main)
