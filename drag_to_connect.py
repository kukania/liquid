"""Reusable drag-to-connect behavior for fixed-position Flet controls."""

from dataclasses import dataclass
from contextlib import contextmanager
import math
from typing import Callable, Optional

import flet as ft
from flet.canvas import Canvas, Line


@dataclass
class ConnectableObject:
    """A Flet control and the geometry used to connect it to other controls."""

    # This can be any Flet control: a Container, Image, Button, etc.
    control: ft.Control

    # Position and size inside the DragToConnect Stack.
    x: float
    y: float
    width: float
    height: float

    # Normalized anchors: (0, 0) is top-left, (1, 1) is bottom-right.
    # Defaults make lines leave bottom-center and arrive at top-center.
    start_anchor: tuple[float, float] = (0.5, 1.0)
    end_anchor: tuple[float, float] = (0.5, 0.0)

    # Normalized connection zones: left, top, right, bottom.
    start_region: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    end_region: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    on_move: Optional[Callable] = None
    on_move_end: Optional[Callable] = None
    on_tap: Optional[Callable] = None

    def anchor(self, normalized_anchor):
        """Convert a normalized anchor into Stack coordinates."""
        anchor_x, anchor_y = normalized_anchor
        return self.x + self.width * anchor_x, self.y + self.height * anchor_y

    def contains(self, x, y):
        """Return True when a Stack coordinate is inside this object."""
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    def region_contains(self, region, x, y):
        """Check a Stack coordinate against a normalized object region."""
        left, top, right, bottom = region
        return (
            self.x + self.width * left <= x <= self.x + self.width * right
            and self.y + self.height * top <= y <= self.y + self.height * bottom
        )


class DragToConnect:
    """Adds drag-to-connect behavior to arbitrary fixed-position Flet controls."""

    def __init__(
        self,
        objects: dict[str, ConnectableObject],
        width=900,
        height=500,
        connections=None,
        on_connect: Optional[Callable[[str, str], None]] = None,
        on_connections_changed: Optional[Callable[[], None]] = None,
        on_connection_tap: Optional[Callable] = None,
        connection_label: Optional[Callable[[str, str], str]] = None,
        background_controls=None,
        show_footer=True,
    ):
        # Public configuration and completed (source, target) connections.
        self.objects = objects
        self.connections = list(connections or [])
        self.on_connect = on_connect
        self.on_connections_changed = on_connections_changed
        self.on_connection_tap = on_connection_tap
        self.connection_label = connection_label
        self._detectors = {}
        self._edge_controls = []
        self.suspend_updates = False
        self._batch_depth = 0

        # Temporary state that exists only while a line is being dragged.
        self._preview_source = None
        self._preview_end = None
        self._moving_object = None

        # The canvas sits behind the objects and draws all connection lines.
        self._canvas = Canvas(width=width, height=height)
        self.status = ft.Text(
            "Press an object, drag to another object, and release to connect them."
        )

        # Wrap every supplied control to add gestures without depending on its type.
        detectors = [
            self._make_detector(object_id, item)
            for object_id, item in objects.items()
        ]
        # Background controls are useful for grids, lanes, or timeline rows.
        self._background_controls = list(background_controls or [])
        self.stack = ft.Stack(
            controls=[*self._background_controls, self._canvas, *detectors],
            width=width,
            height=height,
        )
        view_controls = [self.stack]
        if show_footer:
            view_controls.extend(
                [
                    self.status,
                    ft.Row(
                        [ft.Button("Clear links", on_click=self.clear_links)],
                        alignment=ft.MainAxisAlignment.START,
                    ),
                ]
            )
        self.view = ft.Column(
            view_controls,
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._redraw(update_control=False)

    def _anchor(self, object_id, anchor_name):
        """Get an object's start or end anchor in Stack coordinates."""
        item = self.objects[object_id]
        normalized_anchor = getattr(item, anchor_name)
        return item.anchor(normalized_anchor)

    def _update_page(self):
        """Update only when this component is currently attached to a page."""
        if self.suspend_updates or self._batch_depth:
            return
        try:
            page = self.view.page
        except RuntimeError:
            return
        page.update()

    def _make_line(self, source, target):
        """Build a thick permanent line and arrowhead for one edge."""
        x1, y1 = self._anchor(source, "start_anchor")
        x2, y2 = self._anchor(target, "end_anchor")
        paint = ft.Paint(color=ft.Colors.BLUE_600, stroke_width=7)
        angle = math.atan2(y2 - y1, x2 - x1)
        arrow_length = 16
        return [
            Line(x1, y1, x2, y2, paint=paint),
            Line(
                x2,
                y2,
                x2 - arrow_length * math.cos(angle - 0.55),
                y2 - arrow_length * math.sin(angle - 0.55),
                paint=paint,
            ),
            Line(
                x2,
                y2,
                x2 - arrow_length * math.cos(angle + 0.55),
                y2 - arrow_length * math.sin(angle + 0.55),
                paint=paint,
            ),
        ]

    def _make_edge_control(self, source, target):
        """Create a clickable label centered over a completed edge."""
        x1, y1 = self._anchor(source, "start_anchor")
        x2, y2 = self._anchor(target, "end_anchor")
        label = (
            self.connection_label(source, target)
            if self.connection_label is not None
            else "Edit flow"
        )
        return ft.GestureDetector(
            left=(x1 + x2) / 2 - 65,
            top=(y1 + y2) / 2 - 16,
            mouse_cursor=ft.MouseCursor.CLICK,
            on_tap=lambda event: self.on_connection_tap(source, target, event),
            content=ft.Container(
                width=130,
                height=32,
                bgcolor=ft.Colors.WHITE,
                border=ft.Border.all(2, ft.Colors.BLUE_500),
                border_radius=16,
                alignment=ft.Alignment.CENTER,
                padding=4,
                content=ft.Text(label, size=10, weight="bold", max_lines=1),
            ),
        )

    def _redraw(self, update_control=True):
        """Redraw permanent connections and the optional preview line."""
        if self._batch_depth:
            return
        # Permanent lines are recreated from the public connection list.
        self._canvas.shapes = [
            shape
            for source, target in self.connections
            for shape in self._make_line(source, target)
        ]
        # While dragging, add a temporary line ending at the mouse pointer.
        if self._preview_source is not None and self._preview_end is not None:
            x1, y1 = self._anchor(self._preview_source, "start_anchor")
            x2, y2 = self._preview_end
            self._canvas.shapes.append(
                Line(
                    x1,
                    y1,
                    x2,
                    y2,
                    paint=ft.Paint(color=ft.Colors.BLUE_400, stroke_width=3),
                )
            )
        self._edge_controls = (
            [
                self._make_edge_control(source, target)
                for source, target in self.connections
            ]
            if self.on_connection_tap is not None
            else []
        )
        self.stack.controls = [
            *self._background_controls,
            self._canvas,
            *self._edge_controls,
            *self._detectors.values(),
        ]
        # A control can only be updated after it has been added to a page.
        if update_control:
            self._update_page()

    def _pointer_position(self, object_id, local_position):
        """Convert object-local pointer coordinates into Stack coordinates."""
        item = self.objects[object_id]
        return item.x + local_position.x, item.y + local_position.y

    def _begin(self, object_id, event):
        """Start a preview line when the pointer is pressed on an object."""
        item = self.objects[object_id]
        pointer = self._pointer_position(object_id, event.local_position)
        if item.region_contains(item.start_region, *pointer):
            self._preview_source = object_id
            self._preview_end = pointer
            self.status.value = f"Connecting from {object_id}..."
        elif item.on_move is not None:
            self._moving_object = object_id
        self._redraw()

    def _drag(self, object_id, event):
        """Move the preview line's endpoint with the pointer."""
        if self._preview_source == object_id:
            self._preview_end = self._pointer_position(object_id, event.local_position)
            self._redraw()
        elif self._moving_object == object_id:
            item = self.objects[object_id]
            item.on_move(object_id, event)

    def _drop_target(self, x, y, source):
        """Find the non-source object under the release position."""
        for object_id, item in self.objects.items():
            if (
                item.control.visible
                and object_id != source
                and item.region_contains(item.end_region, x, y)
            ):
                return object_id
        return None

    def _finish(self, object_id, event):
        """Commit a valid connection or cancel an invalid drop."""
        if self._moving_object == object_id:
            self._moving_object = None
            item = self.objects[object_id]
            if item.on_move_end is not None:
                item.on_move_end(object_id, event)
            return
        end_x, end_y = self._pointer_position(object_id, event.local_position)
        source = self._preview_source
        target = self._drop_target(end_x, end_y, source)
        self._preview_source = None
        self._preview_end = None

        if source is not None and target is not None:
            pair = (source, target)
            if pair not in self.connections:
                self.connections.append(pair)
                self.status.value = f"Connected {source} to {target}."
                if self.on_connect is not None:
                    self.on_connect(source, target)
                if self.on_connections_changed is not None:
                    self.on_connections_changed()
            else:
                self.status.value = f"{source} is already connected to {target}."
        else:
            self.status.value = "Connection cancelled. Release over another object."
        self._redraw()

    def _cancel(self, _):
        """Remove the preview if Flet cancels the pan gesture."""
        self._preview_source = None
        self._preview_end = None
        self._moving_object = None
        self.status.value = "Connection cancelled."
        self._redraw()

    def _tap(self, object_id, event):
        """Send body taps to the object while reserving its connection ports."""
        item = self.objects[object_id]
        pointer = self._pointer_position(object_id, event.local_position)
        if item.region_contains(item.start_region, *pointer):
            return
        if item.region_contains(item.end_region, *pointer):
            return
        if item.on_tap is not None:
            item.on_tap(object_id, event)

    def clear_links(self, _=None):
        """Public helper and button handler for removing every connection."""
        self.connections.clear()
        self._preview_source = None
        self._preview_end = None
        self.status.value = "All links cleared."
        if self.on_connections_changed is not None:
            self.on_connections_changed()
        self._redraw()

    def add_object(self, object_id, item):
        """Add a connectable control after the component has been created."""
        if object_id in self.objects:
            raise ValueError(f"An object named {object_id!r} already exists.")
        self.objects[object_id] = item
        detector = self._make_detector(object_id, item)
        self._detectors[object_id] = detector
        self.stack.controls.append(detector)
        self._update_page()

    @contextmanager
    def batch_layout(self):
        """Defer connection rebuilding and page updates until layout is complete."""
        self._batch_depth += 1
        try:
            yield
        finally:
            self._batch_depth -= 1
            if not self._batch_depth:
                self._redraw()

    def set_background_controls(self, controls, height):
        """Replace background rows and resize the drawing area."""
        self._background_controls = list(controls)
        self._canvas.height = height
        self.stack.height = height
        self._redraw()

    def move_object(self, object_id, x, y):
        """Move an object and redraw every connection attached to it."""
        item = self.objects[object_id]
        item.x = x
        item.y = y
        detector = self._detectors[object_id]
        detector.left = x
        detector.top = y
        self._redraw()

    def resize_object(self, object_id, item):
        """Replace a resized control and its hit geometry, preserving links."""
        self.objects[object_id] = item
        self._detectors[object_id].content = item.control

    def refresh_connections(self):
        """Redraw connections after external edge metadata changes."""
        self._redraw()

    def remove_object(self, object_id):
        """Remove an object and every connection attached to it."""
        self.objects.pop(object_id, None)
        detector = self._detectors.pop(object_id, None)
        if detector in self.stack.controls:
            self.stack.controls.remove(detector)
        self.connections[:] = [
            pair for pair in self.connections if object_id not in pair
        ]
        if self.on_connections_changed is not None:
            self.on_connections_changed()
        self._redraw()

    def _make_detector(self, object_id, item):
        """Position an object and attach the four pan event handlers."""
        detector = ft.GestureDetector(
            left=item.x,
            top=item.y,
            content=item.control,
            drag_interval=10,
            on_pan_down=lambda event: self._begin(object_id, event),
            on_pan_update=lambda event: self._drag(object_id, event),
            on_pan_end=lambda event: self._finish(object_id, event),
            on_pan_cancel=self._cancel,
            on_tap=lambda event: self._tap(object_id, event),
        )
        self._detectors[object_id] = detector
        return detector
