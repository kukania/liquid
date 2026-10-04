"""Month, box, and timeline components for the scheduler-style UI."""

import logging
from uuid import uuid4

import flet as ft

from box import TimelineBox
from drag_to_connect import DragToConnect
from periodic_plan import PeriodicPlan
from projection import cents


# Monthly balance calculation (implemented in projection.py):
# 1. Carry forward each money object's previous closing balance; use its
#    starting balance for the first month.
# 2. Add that month's external income.
# 3. Deduct consumption plans BEFORE applying any periodic transfers.
# 4. Apply periodic plans in priority order, using the balances remaining
#    after consumption and earlier transfers. A "rest" transfer uses the
#    source's remaining nonnegative balance.
# 5. Display closing balances in Savings and carry them into the next month.
# If a periodic plan cannot be funded, highlight the affected money objects
# in Savings with a red outline and expose the shortfall in their details.
# Unaffordable fixed transfers are skipped in full; later transfers still run.


MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

logger = logging.getLogger(__name__)


class Month:
    """One timeline row that owns and positions all boxes in that month."""

    LABEL_WIDTH = 132
    BOX_GAP = 20
    MONTH_COLUMN_WIDTH = 120
    COLUMN_GAP = 12

    @property
    def CONTENT_SECTION_WIDTH(self):
        return (self.timeline_width - self.MONTH_COLUMN_WIDTH - self.COLUMN_GAP * 4) / 2

    def __init__(self, name, index, timeline_width, row_height):
        self.name = name
        self.index = index
        self.timeline_width = timeline_width
        self.row_height = row_height
        self.boxes = []
        self.display_index = index

    @property
    def y(self):
        """Top coordinate of this month inside the timeline Stack."""
        return self.display_index * self.row_height

    def _section_geometry(self):
        """Return x/width values for source, consumption, and destination areas."""
        usable_width = (
            self.timeline_width
            - self.MONTH_COLUMN_WIDTH
            - self.CONTENT_SECTION_WIDTH
            - self.COLUMN_GAP * 4
        )
        lane_width = usable_width / 2
        source_x = self.MONTH_COLUMN_WIDTH + self.COLUMN_GAP
        content_x = source_x + lane_width + self.COLUMN_GAP
        destination_x = (
            content_x + self.CONTENT_SECTION_WIDTH + self.COLUMN_GAP
        )
        return source_x, lane_width, content_x, destination_x

    def build_background(self):
        """Create Month, outgoing, timeline, and incoming columns."""
        left_lane_x, lane_width, content_x, right_lane_x = (
            self._section_geometry()
        )

        month_label = ft.Container(
            left=self.COLUMN_GAP,
            top=12,
            width=self.MONTH_COLUMN_WIDTH - self.COLUMN_GAP,
            height=self.row_height - 24,
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(1, ft.Colors.BLUE_GREY_200),
            border_radius=10,
            alignment=ft.Alignment.CENTER,
            content=ft.Text(
                self.name,
                size=13,
                weight="bold",
                color=ft.Colors.BLUE_GREY_700,
            ),
        )

        left_lane = ft.Container(
            left=left_lane_x,
            top=12,
            width=lane_width,
            height=self.row_height - 24,
            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.BLUE_50),
            border=ft.Border.all(1, ft.Colors.BLUE_100),
            border_radius=10,
            padding=10,
            alignment=ft.Alignment.TOP_LEFT,
            content=ft.Text(
                "SOURCES",
                size=10,
                color=ft.Colors.BLUE_500,
            ),
        )
        right_lane = ft.Container(
            left=right_lane_x,
            top=12,
            width=lane_width,
            height=self.row_height - 24,
            bgcolor=ft.Colors.with_opacity(0.35, ft.Colors.GREEN_50),
            border=ft.Border.all(1, ft.Colors.GREEN_100),
            border_radius=10,
            padding=10,
            alignment=ft.Alignment.TOP_RIGHT,
            content=ft.Text(
                "SAVINGS",
                size=10,
                color=ft.Colors.GREEN_600,
            ),
        )
        content_lane = ft.Container(
            left=content_x,
            top=12,
            width=self.CONTENT_SECTION_WIDTH,
            height=self.row_height - 24,
            bgcolor=ft.Colors.with_opacity(0.45, ft.Colors.AMBER_50),
            border=ft.Border.all(1, ft.Colors.AMBER_200),
            border_radius=10,
            padding=10,
            alignment=ft.Alignment.TOP_CENTER,
            content=ft.Text(
                "CONSUMPTION PLANS",
                size=10,
                color=ft.Colors.AMBER_800,
            ),
        )
        return ft.Container(
            left=0,
            top=self.y,
            width=self.timeline_width,
            height=self.row_height,
            bgcolor="#F8FAFD" if self.index % 2 == 0 else "#EEF3F9",
            border=ft.Border(
                bottom=ft.BorderSide(1, ft.Colors.BLUE_GREY_100)
            ),
            content=ft.Stack(
                controls=[month_label, left_lane, content_lane, right_lane],
                width=self.timeline_width,
                height=self.row_height,
            ),
        )

    def add_box(
        self,
        box_id,
        title,
        source="",
        destination="",
        amount=0.0,
        use_rest=False,
        priority=0,
        lane="",
        plan_edge_id="",
        is_rollover=False,
        **handlers,
    ):
        """Create and position the next box in this month's horizontal row."""
        lane_width = self._section_geometry()[1]
        box_width = (
            min(116, lane_width * 0.6)
            if lane in ("source", "destination")
            else self.CONTENT_SECTION_WIDTH * 0.85
        )
        box_height = 44 if lane in ("source", "destination") else 56
        box_index = len(self.boxes)
        x = self.LABEL_WIDTH + box_index * (box_width + self.BOX_GAP)
        y = self.y + (self.row_height - box_height) / 2

        box = TimelineBox(
            box_id=box_id,
            title=title,
            x=x,
            y=y,
            width=box_width,
            height=box_height,
            source=source,
            destination=destination,
            amount=amount,
            use_rest=use_rest,
            priority=priority,
            lane=lane,
            plan_edge_id=plan_edge_id,
            is_rollover=is_rollover,
            **handlers,
        )
        self.boxes.append(box)
        self.position_boxes()
        return box

    def position_boxes(self):
        """Lay out source and destination nodes in their respective lanes."""
        left_lane_x, lane_width, content_x, right_lane_x = (
            self._section_geometry()
        )
        lane_indexes = {"source": 0, "destination": 0}
        seen_objects = set()
        regular_index = 0
        for box in self.boxes:
            box.visible = True
            if box.lane in lane_indexes:
                # Keep each plan's occurrence for editing/removal, but show
                # its money object only once per lane in this month.
                object_key = (box.lane, box.title.strip().casefold())
                if object_key in seen_objects:
                    box.visible = False
                    continue
                seen_objects.add(object_key)
                lane_index = lane_indexes[box.lane]
                lane_indexes[box.lane] += 1
                lane_x = left_lane_x if box.lane == "source" else right_lane_x
                box.x = lane_x + (lane_width - box.width) / 2
                box.y = self.y + 40 + lane_index * (box.height + 6)
            else:
                box.x = content_x + (self.CONTENT_SECTION_WIDTH - box.width) / 2
                box.y = self.y + 34 + regular_index * (box.height + 6)
                regular_index += 1


class MonthlyTimeline:
    """Own the month rows and coordinate their boxes with DragToConnect."""

    def __init__(self, width=1500, row_height=180):
        self.store = None
        self._last_state = None
        self._refreshing = False
        self.width = width
        self.row_height = row_height
        self.height = len(MONTH_NAMES) * row_height
        self._item_count = 0
        self._boxes = {}
        self.periodic_plans = []
        self.periodic_edges = []
        self.money_objects = []
        self.source_object_order = []
        self.destination_object_order = []
        self.periodic_plans_view = ft.Column(spacing=8)
        self._refresh_periodic_plans_view()

        # Each Month owns its background row and its own collection of boxes.
        self.months = [
            Month(name, index, width, row_height)
            for index, name in enumerate(MONTH_NAMES)
        ]

        self.connector = DragToConnect(
            objects={},
            width=width,
            height=0,
            background_controls=[],
            show_footer=False,
            on_connect=self._assign_consumption_source,
        )
        # No month row is visible until that specific month contains a box.
        self.connector.view.visible = False

    def set_money_objects(self, money_objects):
        """Set the named objects available as periodic-plan endpoints."""
        self.money_objects = list(money_objects)
        existing_ids = {item.object_id for item in self.money_objects}
        self.source_object_order = [
            object_id
            for object_id in self.source_object_order
            if object_id in existing_ids
        ]
        self.destination_object_order = [
            object_id
            for object_id in self.destination_object_order
            if object_id in existing_ids
        ]

    def update_money_object(self, old_name, money_object):
        """Propagate a renamed money object through plans and occurrences."""
        for plan in self.periodic_plans:
            automatic_title = f"{plan.source} to {plan.destination}"
            title_was_automatic = plan.title == automatic_title
            source_was_renamed = plan.source == old_name
            destination_was_renamed = plan.destination == old_name
            if source_was_renamed:
                plan.source = money_object.name
            if destination_was_renamed:
                plan.destination = money_object.name
            if title_was_automatic:
                plan.title = f"{plan.source} to {plan.destination}"
        self._layout_visible_months()
        self._refresh_periodic_plans_view()
        self._update_page()

    def remove_money_object(self, object_id):
        """Delete a money object and every saved edge that references it."""
        for box in list(self._boxes.values()):
            if not box.lane and box.payer_id == object_id:
                self._remove_box(box.box_id)
        self.money_objects = [
            item for item in self.money_objects if item.object_id != object_id
        ]
        self.source_object_order = [
            item for item in self.source_object_order if item != object_id
        ]
        self.destination_object_order = [
            item for item in self.destination_object_order if item != object_id
        ]
        remaining_edges = [
            edge
            for edge in self.periodic_edges
            if edge.source_id.split(":", 1)[-1] != object_id
            and edge.destination_id.split(":", 1)[-1] != object_id
        ]
        self.replace_periodic_edge_plans(remaining_edges)

    def _update_page(self):
        """Update only while the timeline is attached to the current page."""
        # Rebuilding calculated cards also changes controls. This guard prevents
        # those nested updates from starting another save/calculation cycle.
        if self.store is not None and not self._refreshing:
            from planner_state import refresh
            self._refreshing = True
            self.connector.suspend_updates = True
            try:
                refresh(self)
            finally:
                self._refreshing = False
                self.connector.suspend_updates = False
        try:
            page = self.connector.view.page
        except RuntimeError:
            return
        page.update()

    def _assign_consumption_source(self, source_id, target_id):
        source, target = self._boxes[source_id], self._boxes[target_id]
        if source.lane != "source" or target.lane:
            self.connector.connections.remove((source_id, target_id))
            return
        target.payer_id = source.payer_id
        self._update_page()

    def show_balance(self, box_id, event):
        page = event.control.page
        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Monthly balance"),
            content=ft.Text(self._boxes[box_id].explanation),
            actions=[ft.Button("Close", on_click=lambda _: page.pop_dialog())],
        ))

    def _money_object_options(self, current_value=""):
        """Build dropdown options while preserving a legacy/current value."""
        objects = [
            item
            if isinstance(item, dict)
            else {"name": item.name, "category": item.category}
            for item in self.money_objects
        ]
        if current_value and not any(
            item["name"] == current_value for item in objects
        ):
            objects.append({"name": current_value, "category": "Existing"})
        return [
            ft.DropdownOption(
                key=item["name"],
                text=f'{item["name"]} ({item["category"]})',
            )
            for item in objects
        ]

    def add_item(
        self,
        title="",
        month_index=None,
        source="",
        destination="",
        amount=0.0,
        use_rest=False,
        priority=0,
        lane="",
        plan_edge_id="",
        is_rollover=False,
        sync_periodic_plans=True,
        payer_id="",
        consumption_id=None,
    ):
        """Add a box to a month and register it with DragToConnect.

        When month_index is omitted, items cycle through January to December.
        Passing an index explicitly allows multiple boxes to be added to one month.
        Existing periodic plans are materialized when a month first becomes
        occupied. Generated plan occurrences disable that synchronization to
        avoid recursively creating duplicates.
        """
        item_number = self._item_count + 1
        if month_index is None:
            month_index = self._item_count % len(self.months)
        if not 0 <= month_index < len(self.months):
            raise ValueError("month_index must be between 0 and 11.")

        title = title.strip() or f"Timeline item {item_number}"
        if not lane:
            if payer_id not in {obj.object_id for obj in self.money_objects}:
                raise ValueError("Choose a paying money object for consumption.")
            if cents(amount) < 0:
                raise ValueError("Consumption cannot be negative.")
        box_id = consumption_id or uuid4().hex
        month = self.months[month_index]
        box = month.add_box(
            box_id,
            title,
            source=source.strip(),
            destination=destination.strip(),
            amount=float(amount),
            use_rest=use_rest,
            priority=priority,
            lane=lane,
            plan_edge_id=plan_edge_id,
            is_rollover=is_rollover,
            on_move=self.move_box,
            on_move_end=self.finish_move,
            on_edit=self.edit_box,
            on_remove=self.remove_box,
        )

        self.connector.add_object(box.box_id, box.as_connectable_object())
        box.payer_id = payer_id
        self._boxes[box.box_id] = box
        self._item_count = item_number
        self._layout_visible_months()
        periodic_count = 0
        if sync_periodic_plans:
            periodic_count = self._sync_periodic_plans_for_month(month_index)
        self.connector.status.value = f"Added {title} to {month.name}."
        if periodic_count:
            self.connector.status.value += (
                f" Added {periodic_count} periodic plan occurrence(s)."
            )
        self._update_page()
        return box

    def _sync_periodic_plans_for_month(self, month_index):
        """Balances are derived for all months by planner_state.refresh."""
        return 0

    def _add_periodic_occurrence(self, plan, month_index):
        """Individual transfers no longer create duplicate money-object cards."""
        return 0

    def _add_rollover_source(self, plan, month_index):
        """The calculation engine carries every object's balance forward."""
        return

    def add_periodic_plan(
        self,
        title,
        start_month,
        end_month,
        source="",
        destination="",
        amount=0.0,
        use_rest=False,
        priority=1,
        edge_id="",
        refresh_view=True,
    ):
        """Add plan occurrences only to occupied months in its active range."""
        plan = PeriodicPlan(
            start_month,
            end_month,
            title=title,
            source=source.strip(),
            destination=destination.strip(),
            amount=float(amount),
            use_rest=use_rest,
            priority=priority,
            edge_id=edge_id or uuid4().hex,
        )
        objects_by_name = {obj.name: obj.object_id for obj in self.money_objects}
        plan.source_object_id = objects_by_name.get(plan.source, "")
        plan.destination_object_id = objects_by_name.get(plan.destination, "")
        occupied_months = {
            month.index for month in self.months if month.boxes
        }
        for month_index in sorted(occupied_months):
            if plan.is_active_in(month_index):
                self._add_periodic_occurrence(plan, month_index)
            self._add_rollover_source(plan, month_index)
        self.periodic_plans.append(plan)
        if refresh_view:
            self._refresh_periodic_plans_view()
        if plan.contents:
            occurrence_count = len(plan.active_months)
            self.connector.status.value = (
                f"Added periodic plan {title} to {occurrence_count} "
                "occupied month(s)."
            )
        else:
            self.connector.status.value = (
                "Periodic plan was saved, but no selected month has a timeline box."
            )
        if refresh_view:
            self._update_page()
        return plan

    def replace_periodic_edge_plans(self, edges):
        """Replace plans generated by the designer with its current edge graph."""
        logger.info(
            "replace plans begin incoming_edges=%d existing_plans=%d incoming=%s",
            len(edges),
            len(self.periodic_plans),
            [
                (edge.edge_id, edge.source_id, edge.destination_id, edge.priority)
                for edge in edges
            ],
        )
        # The designer is the only periodic-plan creation path. Clear every
        # previous record so plans created by older builds without edge IDs
        # cannot survive and appear as duplicates.
        for plan in self.periodic_plans:
            for box in list(plan.contents):
                if box.box_id in self._boxes:
                    self._remove_box(box.box_id)
        self.periodic_plans = []

        unique_edges = []
        seen_pairs = set()
        for edge in edges:
            pair = (edge.source_id, edge.destination_id)
            if pair in seen_pairs:
                logger.warning(
                    "dropping duplicate edge pair edge_id=%s pair=%s",
                    edge.edge_id,
                    pair,
                )
                continue
            seen_pairs.add(pair)
            unique_edges.append(edge)
        self.periodic_edges = unique_edges
        objects_by_id = {
            item.object_id: item for item in self.money_objects
        }
        for edge in sorted(
            self.periodic_edges,
            key=lambda item: (item.source_id, item.priority),
        ):
            source = objects_by_id[edge.source_id.split(":", 1)[-1]]
            destination = objects_by_id[edge.destination_id.split(":", 1)[-1]]
            self.add_periodic_plan(
                f"{source.name} to {destination.name}",
                edge.start_month,
                edge.end_month,
                source=source.name,
                destination=destination.name,
                amount=edge.amount,
                use_rest=edge.use_rest,
                priority=edge.priority,
                edge_id=edge.edge_id,
                refresh_view=False,
            )
            logger.info(
                "created plan edge_id=%s pair=(%s, %s) priority=%d total_plans=%d",
                edge.edge_id,
                source.name,
                destination.name,
                edge.priority,
                len(self.periodic_plans),
            )
        self._layout_visible_months()
        self._refresh_periodic_plans_view()
        logger.info(
            "replace plans complete edges=%d plans=%d cards=%d plan_state=%s",
            len(self.periodic_edges),
            len(self.periodic_plans),
            len(self.periodic_plans_view.controls),
            [
                (plan.edge_id, plan.source, plan.destination, plan.priority)
                for plan in self.periodic_plans
            ],
        )
        if self.periodic_plans and len(self.periodic_plans_view.controls) != len(self.periodic_plans):
            raise RuntimeError("Periodic-plan UI is out of sync with its model.")
        self._update_page()

    def _refresh_periodic_plans_view(self):
        """Rebuild the clickable summary cards shown above the timeline."""
        logger.info(
            "refresh plan cards begin plans=%d old_cards=%d",
            len(self.periodic_plans),
            len(self.periodic_plans_view.controls),
        )
        if not self.periodic_plans:
            self.periodic_plans_view.controls = [
                ft.Text(
                    "No periodic plans yet.",
                    size=12,
                    color=ft.Colors.GREY_600,
                    italic=True,
                )
            ]
            logger.info("refresh plan cards complete empty_state_cards=1")
            return

        cards = []
        sorted_plans = sorted(
            self.periodic_plans,
            key=lambda item: (item.source.casefold(), item.priority),
        )
        for index, plan in enumerate(sorted_plans):
            occurrence_count = len(plan.active_months)
            subtitle = (
                f"{MONTH_NAMES[plan.start_month]} to {MONTH_NAMES[plan.end_month]}"
                f"  |  {occurrence_count} timeline occurrence(s)"
            )
            flow = TimelineBox(
                "preview",
                plan.title,
                0,
                0,
                source=plan.source,
                destination=plan.destination,
                amount=plan.amount,
                use_rest=plan.use_rest,
                priority=plan.priority,
            ).details
            cards.append(
                ft.GestureDetector(
                    key=plan.edge_id or f"periodic-plan-{index}",
                    on_tap=lambda event, selected_plan=plan: self.edit_periodic_plan(
                        selected_plan, event
                    ),
                    mouse_cursor=ft.MouseCursor.CLICK,
                    content=ft.Container(
                        padding=12,
                        bgcolor=ft.Colors.WHITE,
                        border=ft.Border.all(1, ft.Colors.BLUE_GREY_200),
                        border_radius=10,
                        content=ft.Row(
                            [
                                ft.Icon(ft.Icons.EVENT_REPEAT, color=ft.Colors.BLUE_600),
                                ft.Column(
                                    [
                                        ft.Text(
                                            f"{plan.priority}. {plan.title}",
                                            weight="bold",
                                        ),
                                        ft.Text(flow, size=12, color=ft.Colors.BLUE_GREY_700),
                                        ft.Text(subtitle, size=12, color=ft.Colors.GREY_700),
                                    ],
                                    spacing=2,
                                    expand=True,
                                ),
                                ft.Icon(ft.Icons.EDIT_OUTLINED, size=18),
                            ]
                        ),
                    ),
                )
            )
        self.periodic_plans_view.controls = cards
        logger.info(
            "refresh plan cards complete cards=%d keys=%s",
            len(cards),
            [plan.edge_id or f"periodic-plan-{index}" for index, plan in enumerate(sorted_plans)],
        )

    def rebuild_periodic_plans_view(self):
        """Return a fresh plan-list control for a clean frontend mount."""
        self.periodic_plans_view = ft.Column(spacing=8)
        self._refresh_periodic_plans_view()
        logger.info(
            "rebuilt plan-list control control_id=%s cards=%d",
            id(self.periodic_plans_view),
            len(self.periodic_plans_view.controls),
        )
        return self.periodic_plans_view

    def edit_periodic_plan(self, plan, event):
        """Open a dialog and update a plan and its generated occurrences."""
        page = event.control.page
        title_input = ft.TextField(label="Plan contents", value=plan.title)
        source_input = ft.Dropdown(
            label="Source object",
            value=plan.source or None,
            options=self._money_object_options(plan.source),
        )
        destination_input = ft.Dropdown(
            label="Destination object",
            value=plan.destination or None,
            options=self._money_object_options(plan.destination),
        )
        amount_input = ft.TextField(
            label="Amount ($)",
            value=f"{plan.amount:.2f}",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        rest_input = ft.Checkbox(
            label="Use rest of money",
            value=plan.use_rest,
        )
        priority_input = ft.TextField(
            label="Priority",
            value=str(plan.priority),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        start_input = ft.Dropdown(
            label="Start month",
            value=str(plan.start_month),
            options=[
                ft.DropdownOption(key=str(index), text=month)
                for index, month in enumerate(MONTH_NAMES)
            ],
        )
        end_input = ft.Dropdown(
            label="End month",
            value=str(plan.end_month),
            options=[
                ft.DropdownOption(key=str(index), text=month)
                for index, month in enumerate(MONTH_NAMES)
            ],
        )
        error_text = ft.Text(size=12, color=ft.Colors.RED_700)

        def save(_):
            title = title_input.value.strip()
            start_month = int(start_input.value)
            end_month = int(end_input.value)
            if not title:
                error_text.value = "Enter the contents of the periodic plan."
                page.update()
                return
            if not source_input.value or not destination_input.value:
                error_text.value = "Choose both a source and destination object."
                page.update()
                return
            if source_input.value == destination_input.value:
                error_text.value = "Source and destination must differ."
                page.update()
                return
            if start_month > end_month:
                error_text.value = "End month must be after the start month."
                page.update()
                return
            try:
                amount = cents(amount_input.value or 0) / 100
            except ValueError:
                error_text.value = "Amount must be a number."
                page.update()
                return
            try:
                priority = int(priority_input.value)
            except (TypeError, ValueError):
                error_text.value = "Priority must be a whole number."
                page.update()
                return
            if priority < 1:
                error_text.value = "Priority must be one or greater."
                page.update()
                return
            if amount < 0:
                error_text.value = "Amount must be zero or greater."
                page.update()
                return

            plan.title = title
            plan.start_month = start_month
            plan.end_month = end_month
            plan.source = source_input.value
            plan.destination = destination_input.value
            objects_by_name = {obj.name: obj.object_id for obj in self.money_objects}
            plan.source_object_id = objects_by_name[plan.source]
            plan.destination_object_id = objects_by_name[plan.destination]
            plan.amount = amount
            plan.use_rest = bool(rest_input.value)
            plan.priority = priority
            self._update_page()
            self._refresh_periodic_plans_view()
            self._layout_visible_months()
            self.connector.status.value = f"Updated periodic plan {title}."
            page.pop_dialog()
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit periodic plan"),
            content=ft.Column(
                [
                    title_input,
                    ft.Row([source_input, destination_input]),
                    amount_input,
                    rest_input,
                    priority_input,
                    ft.Row([start_input, end_input]),
                    error_text,
                ],
                tight=True,
                width=440,
            ),
            actions=[
                ft.Button("Cancel", on_click=lambda _: page.pop_dialog()),
                ft.Button("Save", on_click=save),
            ],
        )
        page.show_dialog(dialog)

    def move_box(self, box_id, event):
        """Move a box when its content area is dragged."""
        delta = event.local_delta or event.global_delta
        if delta is None:
            return
        box = self._boxes[box_id]
        visible_height = len(self._visible_months()) * self.row_height
        box.x = max(Month.LABEL_WIDTH, min(self.width - box.width, box.x + delta.x))
        box.y = max(0, min(visible_height - box.height, box.y + delta.y))
        self.connector.move_object(box_id, box.x, box.y)

    def finish_move(self, box_id, _):
        """Snap a moved box into the month under its vertical center."""
        box = self._boxes[box_id]
        visible_months = self._visible_months()
        display_index = int((box.y + box.height / 2) // self.row_height)
        display_index = max(0, min(len(visible_months) - 1, display_index))
        new_month = visible_months[display_index]

        for month in self.months:
            if box in month.boxes:
                month.boxes.remove(box)
        new_month.boxes.append(box)
        self._layout_visible_months()
        self._sync_periodic_plans_for_month(new_month.index)
        self._update_page()

    def edit_box(self, box_id, event):
        """Open a dialog for changing a box title."""
        box = self._boxes[box_id]
        page = event.control.page
        title_input = ft.TextField(label="Box title", value=box.title, autofocus=True)
        amount_input = ft.TextField(
            label="Amount ($)",
            value=f"{box.amount:.2f}",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        error_text = ft.Text(size=12, color=ft.Colors.RED_700)

        payer_input = ft.Dropdown(
            label="Pay from", value=box.payer_id,
            options=[ft.DropdownOption(key=obj.object_id, text=obj.name)
                     for obj in self.money_objects],
        )

        def delete(_):
            self.remove_box(box_id, None)
            page.pop_dialog()
            page.update()

        def save(_):
            new_title = title_input.value.strip()
            try:
                amount = cents(amount_input.value or 0) / 100
            except ValueError:
                error_text.value = "Amount must be a number."
                page.update()
                return
            if amount < 0:
                error_text.value = "Amount must be zero or greater."
                page.update()
                return
            if not new_title:
                error_text.value = "Enter a box title."
                page.update()
                return
            if payer_input.value not in {obj.object_id for obj in self.money_objects}:
                error_text.value = "Choose a paying object."
                page.update()
                return
            box.payer_id = payer_input.value
            box.title = new_title
            box.amount = amount
            box.refresh_text()
            self._update_page()
            page.pop_dialog()
            page.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit consumption plan"),
            content=ft.Column(
                [
                    title_input,
                    amount_input,
                    payer_input,
                    error_text,
                ],
                tight=True,
                width=440,
            ),
            actions=[
                ft.Button("Cancel", on_click=lambda _: page.pop_dialog()),
                ft.Button("Save", on_click=save),
                ft.Button("Delete consumption plan", on_click=delete),
            ],
        )
        page.show_dialog(dialog)

    def remove_box(self, box_id, _):
        """Delete consumption, recalculate balances and persist the change."""
        box = self._remove_box(box_id)
        for plan in self.periodic_plans:
            if box in plan.contents:
                plan.contents.remove(box)
        self._refresh_periodic_plans_view()
        self.connector.status.value = f"Removed {box.title}."
        self._layout_visible_months()
        self._update_page()

    def _remove_box(self, box_id):
        """Remove a box from model and connector without updating the page."""
        box = self._boxes.pop(box_id)
        for month in self.months:
            if box in month.boxes:
                month.boxes.remove(box)
                break
        self.connector.remove_object(box_id)
        return box

    def _visible_months(self):
        """Show a month only when it contains a consumption plan."""
        return [month for month in self.months if any(not box.lane for box in month.boxes)]

    def resize(self, width):
        """Reflow the canvas and its cards when the available page width changes."""
        width = max(640, width)
        if width == self.width:
            return
        self.width = width
        self.connector.stack.width = self.width
        self.connector._canvas.width = self.width
        for month in self.months:
            month.timeline_width = self.width
            lane_width = month._section_geometry()[1]
            for box in month.boxes:
                box.width = (
                    min(116, lane_width * 0.6)
                    if box.lane in ("source", "destination")
                    else month.CONTENT_SECTION_WIDTH * 0.85
                )
                item = self.connector.objects[box.box_id]
                item.width = box.width
                item.control.width = box.width
                body_index = 0 if box.lane == "source" else 1
                body = item.control.content.controls[body_index].content
                body.width = box.width - (16 if box.lane else 84)
        self._layout_visible_months()

    def _layout_visible_months(self):
        """Pack non-empty month rows together and reposition their boxes."""
        with self.connector.batch_layout():
            visible_months = self._visible_months()
            # Reserve enough vertical space for the single-column object lists.
            required_height = self.row_height
            for month in visible_months:
                month.position_boxes()
                required_height = max(
                    required_height,
                    max(
                        (box.y - month.y + box.height + 18
                         for box in month.boxes if box.visible),
                        default=0,
                    ),
                )
            self.row_height = required_height
            for month in self.months:
                month.row_height = required_height
            for display_index, month in enumerate(visible_months):
                month.display_index = display_index
                month.position_boxes()
                for box in month.boxes:
                    self.connector.objects[box.box_id].control.visible = box.visible
                    self.connector.move_object(box.box_id, box.x, box.y)

            visible_height = len(visible_months) * self.row_height
            self.connector.set_background_controls(
                [month.build_background() for month in visible_months],
                visible_height,
            )
            self.connector.view.visible = bool(visible_months)
