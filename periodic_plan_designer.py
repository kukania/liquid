"""Visual editor for building prioritized periodic money transfers."""

import logging
from copy import deepcopy

import flet as ft

from drag_to_connect import ConnectableObject, DragToConnect
from money_object import (
    CATEGORIES,
    EXTERNAL_SOURCES,
    FUNDING_FROM_OUTSIDE,
    MoneyObjectSection,
)
from periodic_plan import PeriodicPlanEdge
from projection import cents
from timeline import MONTH_NAMES


logger = logging.getLogger(__name__)


class PeriodicPlanDesigner:
    """Build periodic plans by connecting money objects in priority order."""

    NODE_WIDTH = 180
    NODE_HEIGHT = 64
    CANVAS_WIDTH = 650
    CANVAS_HEIGHT = 500

    def _set_layout_sizes(self, width):
        """Allocate one shared width for the headers, canvas and footer."""
        available = max(360, width)
        self._panel_width = available if available < 850 else available * 0.3
        self.CANVAS_WIDTH = (
            available if available < 850 else available - self._panel_width - 20
        )
        self.NODE_WIDTH = self.CANVAS_WIDTH * 0.27

    def _node_x(self, role):
        lane_width = self.CANVAS_WIDTH / 2
        inset = (lane_width - self.NODE_WIDTH) / 2
        return inset if role == "source" else lane_width + inset

    def _update_page(self):
        """Refresh through Page so temporarily detached columns are safe."""
        try:
            page = self.connector.view.page
        except RuntimeError:
            return
        page.update()

    def __init__(self, timeline, on_close):
        self.timeline = timeline
        self._set_layout_sizes(timeline.width)
        self.on_close = on_close
        self.money_objects = list(timeline.money_objects)
        self._source_nodes = {}
        self._destination_nodes = {}
        self._node_labels = {}
        self._source_order = []
        self._destination_order = []
        self._edges = {}
        self._priority_orders = {}
        self._selected_source = None

        self.connector = DragToConnect(
            objects={},
            width=self.CANVAS_WIDTH,
            height=self.CANVAS_HEIGHT,
            on_connections_changed=self._connections_changed,
            on_connection_tap=self._edit_connection,
            connection_label=self._edge_label,
            background_controls=self._background(),
        )
        self.connector.status.value = (
            "Drag from a source object on the left to a destination on the right."
        )

        self.money_object_section = MoneyObjectSection(
            timeline,
            on_changed=self._money_objects_changed,
        )
        self.status = ft.Text(size=12, color=ft.Colors.RED_700)
        self.transfer_list = ft.Column(spacing=8)
        self.source_selector = ft.Row(wrap=True, spacing=6, run_spacing=6)
        self.priority_panel = ft.Column(
            [
                ft.Text("HIGH PRIORITY", size=11, weight="bold"),
                self.transfer_list,
                ft.Text("LOW PRIORITY", size=11, weight="bold"),
            ],
            spacing=8,
            visible=False,
        )

        objects_by_id = {item.object_id: item for item in self.money_objects}
        for object_id in self.timeline.source_object_order:
            if object_id in objects_by_id:
                self._add_node(objects_by_id[object_id], "source")
        for object_id in self.timeline.destination_object_order:
            if object_id in objects_by_id:
                self._add_node(objects_by_id[object_id], "destination")
        self._restore_column_orders()
        self._load_saved_edges()
        self._refresh_transfers()

        self.connector.view.width = self.CANVAS_WIDTH
        self.toolbars = ft.Row(
            [self._column_toolbar("source"), self._column_toolbar("destination")],
            spacing=0,
        )
        self.canvas_panel = ft.Column(
            [self.toolbars, self.connector.view],
            width=self.CANVAS_WIDTH,
            spacing=0,
        )
        self.priorities_panel = ft.Column(
            [
                ft.Text("Select a source to set its priorities", size=12, weight="bold"),
                self.source_selector,
                self.priority_panel,
            ],
            spacing=8,
            width=self._panel_width,
        )

        self.view = ft.Column(
            [
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.ARROW_BACK,
                            tooltip="Back",
                            on_click=lambda _: self.on_close(),
                        ),
                        ft.Text("Periodic plan designer", size=26, weight="bold"),
                    ]
                ),
                ft.Text(
                    "Drag node bodies to reorder them, click a body to edit, or drag between OUT and IN ports to connect.",
                    color=ft.Colors.GREY_700,
                ),
                self.money_object_section.view,
                ft.Divider(),
                self.status,
                ft.Row(
                    [
                        self.canvas_panel,
                        self.priorities_panel,
                    ],
                    spacing=20,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Row(
                    [
                        ft.Button("Cancel", on_click=lambda _: self.on_close()),
                        ft.Button("Save periodic plans", on_click=self._save),
                    ],
                    spacing=12,
                ),
            ],
            spacing=14,
        )

    def resize(self, width):
        """Resize the designer without discarding its unsaved transfers."""
        if width == getattr(self, "_last_resize_width", None):
            return
        self._last_resize_width = width
        with self.connector.batch_layout():
            self._set_layout_sizes(width)
            self.canvas_panel.width = self.CANVAS_WIDTH
            self.connector.view.width = self.CANVAS_WIDTH
            self.connector.stack.width = self.CANVAS_WIDTH
            self.connector._canvas.width = self.CANVAS_WIDTH
            for role, nodes in (("source", self._source_nodes),
                                ("destination", self._destination_nodes)):
                for node_id, money_object in nodes.items():
                    item = self.connector.objects[node_id]
                    item.width = self.NODE_WIDTH
                    item.control.width = self.NODE_WIDTH
                    body_index = 0 if role == "source" else 1
                    item.control.content.controls[body_index].width = self.NODE_WIDTH - 42
                    item.start_region = ((1 - 42 / self.NODE_WIDTH, 0, 1, 1)
                                         if role == "source" else (2, 2, 2, 2))
                    item.end_region = ((0, 0, 42 / self.NODE_WIDTH, 1)
                                       if role == "destination" else (2, 2, 2, 2))
                self._snap_column(role)
            for toolbar in self.toolbars.controls:
                toolbar.width = self.CANVAS_WIDTH / 2
            self.priorities_panel.width = self._panel_width
            self.connector.set_background_controls(self._background(), self.CANVAS_HEIGHT)
            self.connector.refresh_connections()

    def _month_dropdown(self, label, value):
        return ft.Dropdown(
            label=label,
            value=value,
            width=170,
            options=[
                ft.DropdownOption(key=str(index), text=month)
                for index, month in enumerate(MONTH_NAMES)
            ],
        )

    def _money_objects_changed(self, item, change):
        """Keep designer nodes in sync with edits from the shared section."""
        self.money_objects = list(self.timeline.money_objects)
        if change == "removed":
            source_id = f"source:{item.object_id}"
            destination_id = f"destination:{item.object_id}"
            self._remove_node("source", source_id)
            self._remove_node("destination", destination_id)
        for node_id, current_item in {
            **self._source_nodes,
            **self._destination_nodes,
        }.items():
            if current_item is item:
                name_text, details_text = self._node_labels[node_id]
                name_text.value = item.name
                details_text.value = f"{item.category} | {item.amount_label}"
        self._refresh_transfers()
        self.connector.refresh_connections()

    def _background(self):
        return [
            ft.Container(
                left=0,
                top=0,
                width=self.CANVAS_WIDTH / 2,
                height=self.CANVAS_HEIGHT,
                bgcolor=ft.Colors.with_opacity(0.25, ft.Colors.BLUE_50),
                padding=12,
                content=ft.Text("SOURCES", weight="bold", color=ft.Colors.BLUE_700),
            ),
            ft.Container(
                left=self.CANVAS_WIDTH / 2,
                top=0,
                width=self.CANVAS_WIDTH / 2,
                height=self.CANVAS_HEIGHT,
                bgcolor=ft.Colors.with_opacity(0.25, ft.Colors.GREEN_50),
                padding=12,
                content=ft.Text(
                    "DESTINATIONS",
                    weight="bold",
                    color=ft.Colors.GREEN_700,
                ),
            ),
        ]

    def _column_toolbar(self, role):
        label = "Sources" if role == "source" else "Destinations"
        return ft.Container(
            width=self.CANVAS_WIDTH / 2,
            padding=8,
            bgcolor=ft.Colors.BLUE_GREY_50,
            content=ft.Row(
                [
                    ft.Text(label, weight="bold", expand=True),
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        tooltip=f"Add to {label.lower()}",
                        on_click=lambda event: self._open_add_to_column(role, event),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REMOVE,
                        tooltip=f"Remove from {label.lower()}",
                        on_click=lambda event: self._open_remove_from_column(role, event),
                    ),
                ]
            ),
        )

    def _open_add_to_column(self, role, event):
        """Choose a shared money object to place in a designer column."""
        page = event.control.page
        nodes = self._source_nodes if role == "source" else self._destination_nodes
        available = [
            item
            for item in self.money_objects
            if f"{role}:{item.object_id}" not in nodes
        ]
        selection = ft.Dropdown(
            label="Money object",
            options=[
                ft.DropdownOption(key=item.object_id, text=item.name)
                for item in available
            ],
        )
        error = ft.Text(size=12, color=ft.Colors.RED_700)

        def add(_):
            if not selection.value:
                error.value = "Choose a money object."
                page.update()
                return
            item = next(
                candidate
                for candidate in self.money_objects
                if candidate.object_id == selection.value
            )
            self._add_node(item, role)
            self._snap_column(role)
            page.pop_dialog()
            page.update()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(
                    "Add source object" if role == "source" else "Add destination object"
                ),
                content=ft.Column([selection, error], tight=True, width=400),
                actions=[
                    ft.Button("Cancel", on_click=lambda _: page.pop_dialog()),
                    ft.Button("Add", on_click=add),
                ],
            )
        )

    def _open_remove_from_column(self, role, event):
        """Choose a placement to remove from one designer column."""
        page = event.control.page
        nodes = self._source_nodes if role == "source" else self._destination_nodes
        if not nodes:
            self.status.value = f"There are no {role} objects to remove."
            page.update()
            return
        selection = ft.Dropdown(
            label=f"{role.title()} object",
            options=[
                ft.DropdownOption(key=node_id, text=item.name)
                for node_id, item in nodes.items()
            ],
        )
        error = ft.Text(size=12, color=ft.Colors.RED_700)

        def remove(_):
            if not selection.value:
                error.value = "Choose an object to remove."
                page.update()
                return
            self._remove_node(role, selection.value)
            page.pop_dialog()
            page.update()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text(f"Remove {role} object"),
                content=ft.Column([selection, error], tight=True, width=400),
                actions=[
                    ft.Button("Cancel", on_click=lambda _: page.pop_dialog()),
                    ft.Button("Remove", on_click=remove),
                ],
            )
        )

    def _node_control(self, item, role, node_id):
        color = ft.Colors.BLUE_100 if role == "source" else ft.Colors.GREEN_100
        name_text = ft.Text(item.name, weight="bold", max_lines=1)
        category_text = ft.Text(
            f"{item.category} | {item.amount_label}",
            size=10,
            color=ft.Colors.GREY_700,
        )
        self._node_labels[node_id] = (name_text, category_text)
        body = ft.Container(
            width=self.NODE_WIDTH - 42,
            height=self.NODE_HEIGHT,
            padding=8,
            alignment=ft.Alignment.CENTER_LEFT,
            content=ft.Column(
                [name_text, category_text],
                spacing=2,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        )
        port = ft.Container(
            width=42,
            height=self.NODE_HEIGHT,
            bgcolor=color,
            alignment=ft.Alignment.CENTER,
            content=ft.Text("OUT" if role == "source" else "IN", size=9),
        )
        return ft.Container(
            width=self.NODE_WIDTH,
            height=self.NODE_HEIGHT,
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(2, color),
            border_radius=10,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Row(
                [body, port] if role == "source" else [port, body],
                spacing=0,
            ),
        )

    def _add_node(self, item, role):
        """Place an existing money object in one designer column."""
        nodes = self._source_nodes if role == "source" else self._destination_nodes
        order = self._source_order if role == "source" else self._destination_order
        node_id = f"{role}:{item.object_id}"
        if node_id in nodes:
            return
        nodes[node_id] = item
        order.append(node_id)
        is_source = role == "source"
        self.connector.add_object(
            node_id,
            ConnectableObject(
                self._node_control(item, role, node_id),
                x=self._node_x(role),
                y=48 + (len(order) - 1) * 82,
                width=self.NODE_WIDTH,
                height=self.NODE_HEIGHT,
                start_anchor=(1.0, 0.5),
                end_anchor=(0.0, 0.5),
                start_region=(1 - 42 / self.NODE_WIDTH, 0.0, 1.0, 1.0)
                if is_source
                else (2.0, 2.0, 2.0, 2.0),
                end_region=(2.0, 2.0, 2.0, 2.0)
                if is_source
                else (0.0, 0.0, 42 / self.NODE_WIDTH, 1.0),
                on_move=self._drag_node,
                on_move_end=self._finish_node_drag,
                on_tap=self._edit_node,
            ),
        )

    def _remove_node(self, role, node_id):
        """Remove a column placement without deleting the shared money object."""
        nodes = self._source_nodes if role == "source" else self._destination_nodes
        order = self._source_order if role == "source" else self._destination_order
        if node_id not in nodes:
            return
        order.remove(node_id)
        nodes.pop(node_id)
        self._node_labels.pop(node_id, None)
        self.connector.remove_object(node_id)
        self._snap_column(role)

    def _drag_node(self, node_id, event):
        """Move a node body vertically while keeping it in its own column."""
        delta = event.local_delta or event.global_delta
        if delta is None:
            return
        item = self.connector.objects[node_id]
        maximum_y = self.CANVAS_HEIGHT - self.NODE_HEIGHT - 12
        new_y = max(48, min(maximum_y, item.y + delta.y))
        self.connector.move_object(node_id, item.x, new_y)

    def _finish_node_drag(self, node_id, _):
        """Snap a dragged node into a new position within its column."""
        role = "source" if node_id.startswith("source:") else "destination"
        order = self._source_order if role == "source" else self._destination_order
        dragged = self.connector.objects[node_id]
        new_index = round((dragged.y - 48) / 82)
        new_index = max(0, min(len(order) - 1, new_index))
        order.remove(node_id)
        order.insert(new_index, node_id)
        self._snap_column(role)
        self._update_page()

    def _snap_column(self, role):
        """Position and persist all nodes in one ordered column."""
        order = self._source_order if role == "source" else self._destination_order
        nodes = self._source_nodes if role == "source" else self._destination_nodes
        x = self._node_x(role)
        for position, node_id in enumerate(order):
            self.connector.move_object(node_id, x, 48 + position * 82)

    def _restore_column_orders(self):
        """Restore independently saved source and destination column order."""
        source_rank = {
            object_id: index
            for index, object_id in enumerate(self.timeline.source_object_order)
        }
        destination_rank = {
            object_id: index
            for index, object_id in enumerate(self.timeline.destination_object_order)
        }
        self._source_order.sort(
            key=lambda node_id: source_rank.get(
                self._source_nodes[node_id].object_id, len(source_rank)
            )
        )
        self._destination_order.sort(
            key=lambda node_id: destination_rank.get(
                self._destination_nodes[node_id].object_id, len(destination_rank)
            )
        )
        for position, node_id in enumerate(self._source_order):
            self.connector.move_object(node_id, self._node_x("source"), 48 + position * 82)
        for position, node_id in enumerate(self._destination_order):
            self.connector.move_object(
                node_id,
                self._node_x("destination"),
                48 + position * 82,
            )

    def _edit_node(self, node_id, event):
        """Use the shared editor for balances and recurring external income."""
        nodes = self._source_nodes if node_id.startswith("source:") else self._destination_nodes
        self.money_object_section._show_editor(event.control.page, nodes[node_id])

    def _connections_changed(self):
        invalid_pairs = []
        for pair in self.connector.connections:
            source = self._source_nodes[pair[0]]
            destination = self._destination_nodes[pair[1]]
            if (
                source.object_id == destination.object_id
            ):
                invalid_pairs.append(pair)
        if invalid_pairs:
            self.connector.connections[:] = [
                pair
                for pair in self.connector.connections
                if pair not in invalid_pairs
            ]
            self.status.value = (
                "Transfer source and destination must differ."
            )
            self.connector.status.value = self.status.value
        active = set(self.connector.connections)
        for pair in list(self._edges):
            if pair not in active:
                del self._edges[pair]
        for pair in self.connector.connections:
            if pair not in self._edges:
                self._edges[pair] = PeriodicPlanEdge(pair[0], pair[1])
                self._priority_orders.setdefault(pair[0], []).append(pair)
                self._edges[pair].priority = len(self._priority_orders[pair[0]])
                self._selected_source = pair[0]
        for source_id in list(self._priority_orders):
            self._priority_orders[source_id] = [
                pair for pair in self._priority_orders[source_id] if pair in active
            ]
            if not self._priority_orders[source_id]:
                del self._priority_orders[source_id]
        if self._selected_source not in self._priority_orders:
            self._selected_source = None
        self._refresh_transfers()

    def _load_saved_edges(self):
        """Restore the saved graph and per-source priorities on reopen."""
        valid_edges = []
        for edge in self.timeline.periodic_edges:
            pair = (edge.source_id, edge.destination_id)
            if pair[0] not in self._source_nodes or pair[1] not in self._destination_nodes:
                continue
            valid_edges.append(edge)
            self._edges[pair] = deepcopy(edge)
            self.connector.connections.append(pair)
            self._priority_orders.setdefault(pair[0], []).append(pair)
        for source_id, order in self._priority_orders.items():
            order.sort(key=lambda pair: self._edges[pair].priority)
        if valid_edges:
            self._selected_source = valid_edges[0].source_id
        self.connector.refresh_connections()

    def _edge_label(self, source_id, destination_id):
        edge = self._edges.get((source_id, destination_id))
        if edge is None:
            return "Edit flow"
        return (
            f"{edge.amount_label} | "
            f"{MONTH_NAMES[edge.start_month][:3]}-{MONTH_NAMES[edge.end_month][:3]}"
        )

    def _edit_connection(self, source_id, destination_id, event):
        """Edit direction, period, and amount by clicking an edge badge."""
        page = event.control.page
        pair = (source_id, destination_id)
        edge = self._edges[pair]
        source_input = ft.Dropdown(
            label="Flow from",
            value=source_id,
            options=[
                ft.DropdownOption(key=node_id, text=item.name)
                for node_id, item in self._source_nodes.items()
            ],
        )
        destination_input = ft.Dropdown(
            label="Flow to",
            value=destination_id,
            options=[
                ft.DropdownOption(key=node_id, text=item.name)
                for node_id, item in self._destination_nodes.items()
            ],
        )
        start_input = self._month_dropdown("Start month", str(edge.start_month))
        end_input = self._month_dropdown("End month", str(edge.end_month))
        amount_input = ft.TextField(
            label="Amount ($)",
            value=f"{edge.amount:.2f}",
            disabled=edge.use_rest,
            keyboard_type=ft.KeyboardType.NUMBER,
        )

        def toggle_rest(change_event):
            amount_input.disabled = bool(change_event.control.value)
            page.update()

        rest_input = ft.Checkbox(
            label="Use rest of money",
            value=edge.use_rest,
            on_change=toggle_rest,
        )
        error = ft.Text(size=12, color=ft.Colors.RED_700)

        def save(_):
            new_pair = (source_input.value, destination_input.value)
            if new_pair != pair and new_pair in self.connector.connections:
                error.value = "That flow already exists."
                page.update()
                return
            new_source = self._source_nodes[new_pair[0]]
            new_destination = self._destination_nodes[new_pair[1]]
            if (
                new_source.object_id == new_destination.object_id
            ):
                error.value = (
                    "Transfer source and destination must differ."
                )
                page.update()
                return
            start_month = int(start_input.value)
            end_month = int(end_input.value)
            if start_month > end_month:
                error.value = "End month must be after the start month."
                page.update()
                return
            use_rest = bool(rest_input.value)
            try:
                amount = 0.0 if use_rest else cents(amount_input.value or 0) / 100
            except ValueError:
                error.value = "Amount must be a number."
                page.update()
                return
            if amount < 0:
                error.value = "Amount must be zero or greater."
                page.update()
                return

            edge.source_id, edge.destination_id = new_pair
            edge.start_month = start_month
            edge.end_month = end_month
            edge.amount = amount
            edge.use_rest = use_rest
            if new_pair != pair:
                connection_index = self.connector.connections.index(pair)
                self.connector.connections[connection_index] = new_pair
                old_order = self._priority_orders[pair[0]]
                old_index = old_order.index(pair)
                old_order.pop(old_index)
                if not old_order:
                    del self._priority_orders[pair[0]]
                new_order = self._priority_orders.setdefault(new_pair[0], [])
                new_order.insert(min(old_index, len(new_order)), new_pair)
                del self._edges[pair]
                self._edges[new_pair] = edge
                self._selected_source = new_pair[0]
                for priority, ordered_pair in enumerate(new_order, start=1):
                    self._edges[ordered_pair].priority = priority
            self.connector.refresh_connections()
            self._refresh_transfers()
            page.pop_dialog()
            page.update()

        page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Edit money flow"),
                content=ft.Column(
                    [
                        ft.Row([source_input, destination_input]),
                        ft.Row([start_input, end_input]),
                        amount_input,
                        rest_input,
                        error,
                    ],
                    tight=True,
                    width=470,
                ),
                actions=[
                    ft.Button("Cancel", on_click=lambda _: page.pop_dialog()),
                    ft.Button("Save flow", on_click=save),
                ],
            )
        )

    def _move_transfer(self, pair, offset):
        order = self._priority_orders[pair[0]]
        index = order.index(pair)
        new_index = max(0, min(len(order) - 1, index + offset))
        if index != new_index:
            order.insert(new_index, order.pop(index))
            for priority, ordered_pair in enumerate(order, start=1):
                self._edges[ordered_pair].priority = priority
            self._refresh_transfers()
            self.connector.refresh_connections()
            self._update_page()

    def _remove_edge(self, pair):
        """Remove an edge and its priority entry from the designer."""
        if pair in self.connector.connections:
            self.connector.connections.remove(pair)
        self._connections_changed()
        self.connector.refresh_connections()

    def _select_source(self, source_id):
        """Show the independent priority queue for one source object."""
        self._selected_source = source_id
        self._refresh_transfers()
        self._update_page()

    def _refresh_transfers(self):
        connected_sources = []
        for pair in self.connector.connections:
            if pair[0] not in connected_sources:
                connected_sources.append(pair[0])
        self.source_selector.controls = [
            ft.Button(
                self._source_nodes[source_id].name,
                icon=(
                    ft.Icons.CHECK
                    if source_id == self._selected_source
                    else ft.Icons.ACCOUNT_BALANCE_WALLET
                ),
                on_click=lambda _, selected=source_id: self._select_source(selected),
            )
            for source_id in connected_sources
        ]
        self.priority_panel.visible = self._selected_source is not None

        controls = []
        selected_pairs = self._priority_orders.get(self._selected_source, [])
        for index, pair in enumerate(selected_pairs):
            source = self._source_nodes[pair[0]]
            destination = self._destination_nodes[pair[1]]
            edge = self._edges[pair]
            controls.append(
                ft.Container(
                    padding=10,
                    bgcolor=ft.Colors.WHITE,
                    border=ft.Border.all(1, ft.Colors.BLUE_GREY_200),
                    border_radius=8,
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        f"{index + 1}. {source.name} -> {destination.name}",
                                        weight="bold",
                                        expand=True,
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.ARROW_UPWARD,
                                        tooltip="Higher priority",
                                        on_click=lambda _, selected=pair: self._move_transfer(
                                            selected, -1
                                        ),
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.ARROW_DOWNWARD,
                                        tooltip="Lower priority",
                                        on_click=lambda _, selected=pair: self._move_transfer(
                                            selected, 1
                                        ),
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.DELETE_OUTLINE,
                                        tooltip="Remove edge",
                                        on_click=lambda _, selected=pair: self._remove_edge(
                                            selected
                                        ),
                                    ),
                                ],
                                spacing=2,
                            ),
                            ft.Row(
                                [
                                    ft.Text(
                                        f"{edge.amount_label} | "
                                        f"{MONTH_NAMES[edge.start_month]} to "
                                        f"{MONTH_NAMES[edge.end_month]}",
                                        size=11,
                                        expand=True,
                                    ),
                                    ft.Button(
                                        "Edit",
                                        on_click=lambda event, selected=pair: self._edit_connection(
                                            selected[0], selected[1], event
                                        ),
                                    ),
                                ]
                            ),
                        ],
                        spacing=4,
                    ),
                )
            )
        self.transfer_list.controls = controls or [
            ft.Text(
                "Draw a connection, then select its source.",
                size=12,
                color=ft.Colors.GREY_600,
                italic=True,
            )
        ]
        self._update_page()

    def _save(self, _):
        self.timeline.source_object_order = [self._source_nodes[key].object_id for key in self._source_order]
        self.timeline.destination_object_order = [self._destination_nodes[key].object_id for key in self._destination_order]
        logger.info(
            "designer save begin connections=%d pairs=%s edge_map=%d",
            len(self.connector.connections),
            list(self.connector.connections),
            len(self._edges),
        )
        prepared = []
        for pair in self.connector.connections:
            source = self._source_nodes[pair[0]]
            destination = self._destination_nodes[pair[1]]
            edge = self._edges[pair]
            priority = self._priority_orders[pair[0]].index(pair) + 1
            edge.priority = priority
            prepared.append((source, destination, edge, priority))

        self.timeline.set_money_objects(self.money_objects)
        self.timeline.replace_periodic_edge_plans(
            [edge for _, _, edge, _ in prepared]
        )
        logger.info(
            "designer save complete prepared=%d timeline_edges=%d timeline_plans=%d cards=%d",
            len(prepared),
            len(self.timeline.periodic_edges),
            len(self.timeline.periodic_plans),
            len(self.timeline.periodic_plans_view.controls),
        )
        self.on_close(
            f"Saved {len(prepared)} periodic plan(s) in priority order."
        )
