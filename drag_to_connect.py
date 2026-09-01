"""Reusable drag-to-connect behavior for fixed-position Flet controls."""

from dataclasses import dataclass
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

    def anchor(self, normalized_anchor):
        """Convert a normalized anchor into Stack coordinates."""
        anchor_x, anchor_y = normalized_anchor
        return self.x + self.width * anchor_x, self.y + self.height * anchor_y

    def contains(self, x, y):
        """Return True when a Stack coordinate is inside this object."""
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height


class DragToConnect:
    """Adds drag-to-connect behavior to arbitrary fixed-position Flet controls."""

    def __init__(
        self,
        objects: dict[str, ConnectableObject],
        width=900,
        height=500,
        connections=None,
        on_connect: Optional[Callable[[str, str], None]] = None,
    ):
        # Public configuration and completed (source, target) connections.
        self.objects = objects
        self.connections = list(connections or [])
        self.on_connect = on_connect

        # Temporary state that exists only while a line is being dragged.
        self._preview_source = None
        self._preview_end = None

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
        self.stack = ft.Stack(
            controls=[self._canvas, *detectors],
            width=width,
            height=height,
        )
        self.view = ft.Column(
            [
                self.stack,
                self.status,
                ft.Row(
                    [ft.ElevatedButton("Clear links", on_click=self.clear_links)],
                    alignment=ft.MainAxisAlignment.START,
                ),
            ],
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._redraw(update_control=False)

    def _anchor(self, object_id, anchor_name):
        """Get an object's start or end anchor in Stack coordinates."""
        item = self.objects[object_id]
        normalized_anchor = getattr(item, anchor_name)
        return item.anchor(normalized_anchor)

    def _make_line(self, source, target):
        """Build one permanent line between connected objects."""
        x1, y1 = self._anchor(source, "start_anchor")
        x2, y2 = self._anchor(target, "end_anchor")
        return Line(
            x1,
            y1,
            x2,
            y2,
            paint=ft.Paint(color=ft.Colors.BLUE_600, stroke_width=3),
        )

    def _redraw(self, update_control=True):
        """Redraw permanent connections and the optional preview line."""
        # Permanent lines are recreated from the public connection list.
        self._canvas.shapes = [
            self._make_line(source, target)
            for source, target in self.connections
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
        # A control can only be updated after it has been added to a page.
        if update_control and self.view.page is not None:
            self.view.update()

    def _pointer_position(self, object_id, local_position):
        """Convert object-local pointer coordinates into Stack coordinates."""
        item = self.objects[object_id]
        return item.x + local_position.x, item.y + local_position.y

    def _begin(self, object_id, event):
        """Start a preview line when the pointer is pressed on an object."""
        self._preview_source = object_id
        self._preview_end = self._pointer_position(object_id, event.local_position)
        self.status.value = f"Connecting from {object_id}..."
        self._redraw()

    def _drag(self, object_id, event):
        """Move the preview line's endpoint with the pointer."""
        if self._preview_source == object_id:
            self._preview_end = self._pointer_position(object_id, event.local_position)
            self._redraw()

    def _drop_target(self, x, y, source):
        """Find the non-source object under the release position."""
        for object_id, item in self.objects.items():
            if object_id != source and item.contains(x, y):
                return object_id
        return None

    def _finish(self, object_id, event):
        """Commit a valid connection or cancel an invalid drop."""
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
            else:
                self.status.value = f"{source} is already connected to {target}."
        else:
            self.status.value = "Connection cancelled. Release over another object."
        self._redraw()

    def _cancel(self, _):
        """Remove the preview if Flet cancels the pan gesture."""
        self._preview_source = None
        self._preview_end = None
        self.status.value = "Connection cancelled."
        self._redraw()

    def clear_links(self, _=None):
        """Public helper and button handler for removing every connection."""
        self.connections.clear()
        self._preview_source = None
        self._preview_end = None
        self.status.value = "All links cleared."
        self._redraw()

    def _make_detector(self, object_id, item):
        """Position an object and attach the four pan event handlers."""
        return ft.GestureDetector(
            left=item.x,
            top=item.y,
            content=item.control,
            drag_interval=10,
            on_pan_down=lambda event: self._begin(object_id, event),
            on_pan_update=lambda event: self._drag(object_id, event),
            on_pan_end=lambda event: self._finish(object_id, event),
            on_pan_cancel=self._cancel,
        )
