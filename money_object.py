"""Money-object model and reusable management UI."""

from dataclasses import dataclass

import flet as ft
from projection import cents


FUNDING_FROM_OUTSIDE = "From outside"
FUNDING_FROM_INSIDE = "From another money object"
FUNDING_TYPES = (FUNDING_FROM_OUTSIDE, FUNDING_FROM_INSIDE)
EXTERNAL_SOURCES = ("Paycheck", "Mortgage", "Loan", "Other")
CATEGORIES = ("Income", "Account", "Investment", "Expense", "Debt", "Other")


@dataclass
class MoneyObject:
    """A balance that is funded externally or by another money object."""

    object_id: str
    name: str
    category: str = "Account"
    current_amount: float = 0.0
    funding_type: str = FUNDING_FROM_INSIDE
    external_source: str = ""
    monthly_income: float = 0.0

    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Money object name cannot be empty.")
        self.current_amount = float(self.current_amount)
        cents(self.current_amount)
        if cents(self.monthly_income) < 0:
            raise ValueError("Monthly income cannot be negative.")
        if self.funding_type not in FUNDING_TYPES:
            raise ValueError("Unknown money-object funding type.")
        if self.funding_type == FUNDING_FROM_OUTSIDE and not self.external_source:
            raise ValueError("An externally funded object requires a source.")

    @property
    def amount_label(self):
        return f"${self.current_amount:,.2f}"

    @property
    def funding_label(self):
        if self.funding_type == FUNDING_FROM_OUTSIDE:
            return f"Outside: {self.external_source}"
        return "Funded by connection"


class MoneyObjectSection:
    """Create and edit the shared money objects displayed on the main page."""

    def __init__(self, timeline, on_changed=None):
        self.timeline = timeline
        self.on_changed = on_changed
        self.status = ft.Text(size=12, color=ft.Colors.RED_700)
        self.cards = ft.ResponsiveRow(spacing=8, run_spacing=8)
        self.view = ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Money objects", size=20, weight="bold", expand=True),
                        ft.Button("Add money object", on_click=self._open_add),
                    ]
                ),
                ft.Text(
                    "Objects created here or in the designer are shared. Click a card to edit it.",
                    color=ft.Colors.GREY_700,
                ),
                self.status,
                self.cards,
            ],
            spacing=10,
        )
        self.refresh()

    def _next_id(self):
        used = {item.object_id for item in self.timeline.money_objects}
        number = 1
        while f"money-{number}" in used:
            number += 1
        return f"money-{number}"

    def _category_dropdown(self, value="Account"):
        return ft.Dropdown(
            label="Category",
            value=value,
            options=[ft.DropdownOption(key=item, text=item) for item in CATEGORIES],
        )

    def _external_dropdown(self, value=None):
        return ft.Dropdown(
            label="Outside source",
            value=value,
            options=[
                ft.DropdownOption(key=item, text=item) for item in EXTERNAL_SOURCES
            ],
        )

    def _open_add(self, event):
        self._show_editor(event.control.page)

    def _show_editor(self, page, item=None, on_saved=None):
        name_input = ft.TextField(
            label="Object name",
            value=item.name if item else "",
            autofocus=True,
        )
        category_input = self._category_dropdown(item.category if item else "Account")
        external_input = self._external_dropdown(
            item.external_source if item and item.external_source else None
        )
        is_outside = bool(item and item.funding_type == FUNDING_FROM_OUTSIDE)
        external_input.visible = is_outside

        def change_funding(event):
            external_input.visible = bool(event.control.value)
            income_input.visible = bool(event.control.value)
            if not external_input.visible:
                external_input.value = None
            page.update()

        outside_input = ft.Checkbox(
            label="Funded from outside",
            value=is_outside,
            on_change=change_funding,
        )
        amount_input = ft.TextField(
            label="Starting balance — January ($)",
            value=f"{item.current_amount:.2f}" if item else "0.00",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        error = ft.Text(size=12, color=ft.Colors.RED_700)
        income_input = ft.TextField(
            label="Monthly external income ($)",
            value=str(item.monthly_income if item else 0),
            visible=is_outside, keyboard_type=ft.KeyboardType.NUMBER,
        )

        def save(_):
            name = name_input.value.strip()
            if not name:
                error.value = "Enter a money object name."
                page.update()
                return
            if any(
                other is not item and other.name.casefold() == name.casefold()
                for other in self.timeline.money_objects
            ):
                error.value = "A money object with that name already exists."
                page.update()
                return
            funded_from_outside = bool(outside_input.value)
            if funded_from_outside and not external_input.value:
                error.value = "Choose an outside source."
                page.update()
                return
            try:
                current_amount = float(amount_input.value or 0)
                cents(current_amount)
                monthly_income = cents(income_input.value or 0) / 100 if funded_from_outside else 0
                if monthly_income < 0:
                    raise ValueError("Negative income")
            except ValueError:
                error.value = "Enter finite amounts; monthly income cannot be negative."
                page.update()
                return

            old_name = item.name if item else ""
            saved_item = item or MoneyObject(
                object_id=self._next_id(),
                name=name,
                funding_type=(
                    FUNDING_FROM_OUTSIDE
                    if funded_from_outside
                    else FUNDING_FROM_INSIDE
                ),
                external_source=external_input.value or "",
            )
            saved_item.name = name
            saved_item.category = category_input.value
            saved_item.current_amount = current_amount
            saved_item.monthly_income = monthly_income
            saved_item.funding_type = (
                FUNDING_FROM_OUTSIDE
                if funded_from_outside
                else FUNDING_FROM_INSIDE
            )
            saved_item.external_source = (
                external_input.value if funded_from_outside else ""
            )
            if item is None:
                self.timeline.set_money_objects(
                    [*self.timeline.money_objects, saved_item]
                )
            else:
                self.timeline.set_money_objects(self.timeline.money_objects)
                self.timeline.update_money_object(old_name, saved_item)
            self.refresh()
            self.timeline._update_page()
            page.pop_dialog()
            page.update()
            if on_saved is not None:
                on_saved(saved_item)
            if self.on_changed is not None:
                self.on_changed(
                    saved_item,
                    "created" if item is None else "updated",
                )

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Edit money object" if item else "Add money object"),
                content=ft.Column(
                    [
                        name_input,
                        category_input,
                        outside_input,
                        external_input,
                        amount_input,
                        income_input,
                        error,
                    ],
                    tight=True,
                    width=430,
                ),
                actions=[
                    ft.Button("Cancel", on_click=lambda _: page.pop_dialog()),
                    ft.Button("Save", on_click=save),
                ],
            )
        )

    def refresh(self):
        if not self.timeline.money_objects:
            self.cards.controls = [
                ft.Text(
                    "No money objects yet.",
                    size=12,
                    color=ft.Colors.GREY_600,
                    italic=True,
                )
            ]
            return
        self.cards.controls = [self._card(item) for item in self.timeline.money_objects]

    def _card(self, item):
        details = ft.GestureDetector(
            expand=True,
            on_tap=lambda event, selected=item: self._show_editor(
                event.control.page, selected
            ),
            mouse_cursor=ft.MouseCursor.CLICK,
            content=ft.Container(
                padding=10,
                content=ft.Column(
                    [
                        ft.Text(item.name, weight="bold"),
                        ft.Text(
                            f"{item.category} | {item.amount_label}",
                            size=11,
                            color=ft.Colors.GREY_700,
                        ),
                        ft.Text(
                            item.funding_label,
                            size=10,
                            color=ft.Colors.BLUE_GREY_600,
                        ),
                    ],
                    spacing=2,
                ),
            ),
        )
        return ft.Container(
            col={"xs": 12, "sm": 6, "lg": 4, "xl": 3},
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, ft.Colors.BLUE_GREY_200),
            border_radius=8,
            content=ft.Row(
                [
                    details,
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        tooltip="Delete money object",
                        on_click=lambda event, selected=item: self._confirm_remove(
                            selected, event
                        ),
                    ),
                ],
                spacing=0,
            ),
        )

    def _confirm_remove(self, item, event):
        """Confirm removal because related edges and plans are also deleted."""
        page = event.control.page

        def remove(_):
            self.timeline.remove_money_object(item.object_id)
            self.refresh()
            page.pop_dialog()
            page.update()
            if self.on_changed is not None:
                self.on_changed(item, "removed")

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Delete money object?"),
                content=ft.Text(
                    f"Delete '{item.name}', its periodic transfers, and consumption plans paid by it?"
                ),
                actions=[
                    ft.Button("Cancel", on_click=lambda _: page.pop_dialog()),
                    ft.Button("Delete", on_click=remove),
                ],
            )
        )
