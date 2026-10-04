"""Timeline box model and visual control."""

from dataclasses import dataclass
from typing import Callable, Optional

import flet as ft

from drag_to_connect import ConnectableObject


@dataclass
class TimelineBox:
    """The data, position, and visual control for one timeline box."""

    box_id: str
    title: str
    x: float
    y: float
    width: float = 210
    height: float = 70
    on_move: Optional[Callable] = None
    on_move_end: Optional[Callable] = None
    on_edit: Optional[Callable] = None
    on_remove: Optional[Callable] = None
    source: str = ""
    destination: str = ""
    amount: float = 0.0
    use_rest: bool = False
    priority: int = 0
    lane: str = ""
    plan_edge_id: str = ""
    is_rollover: bool = False
    visible: bool = True
    payer_id: str = ""
    warning: bool = False
    explanation: str = ""

    @property
    def details(self):
        """Return a compact description of the box's money flow."""
        if self.lane in ("source", "destination"):
            return "Rest of money" if self.use_rest else f"${self.amount:,.2f}"
        parts = []
        if self.source and self.destination:
            parts.append(f"{self.source} -> {self.destination}")
        elif self.source:
            parts.append(f"From: {self.source}")
        elif self.destination:
            parts.append(f"To: {self.destination}")
        parts.append("Rest of money" if self.use_rest else f"${self.amount:,.2f}")
        if self.priority:
            parts.append(f"Priority {self.priority}")
        return " | ".join(parts)

    def refresh_text(self):
        """Refresh the text controls after editing box data."""
        self.title_text.value = self.title
        self.details_text.value = self.details

    def build_control(self):
        """Create the Flet control displayed for this box."""
        # The three horizontal areas deliberately have different responsibilities.
        compact = self.lane in ("source", "destination")
        port_width = 16 if compact else 42
        input_port = ft.Container(
            width=port_width,
            height=self.height,
            bgcolor=ft.Colors.BLUE_50,
            alignment=ft.Alignment.CENTER,
            content=None if compact else ft.Text("IN", size=9, color=ft.Colors.BLUE_700),
        )
        self.title_text = ft.Text(self.title, size=11 if compact else 14, weight="bold", max_lines=1)
        self.details_text = ft.Text(
            self.details,
            size=10,
            color=ft.Colors.GREY_700,
            max_lines=1,
        )
        port_count = 1 if self.lane in ("source", "destination") else 2
        body_content = ft.Column(
            [self.title_text, self.details_text],
            spacing=1 if compact else 3,
            alignment=ft.MainAxisAlignment.CENTER,
        )
        if not self.lane and self.on_remove is not None:
            body_content.expand = True
            body_content = ft.Row(
                [
                    body_content,
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        tooltip="Delete consumption plan",
                        icon_size=18,
                        on_click=lambda event: self.on_remove(self.box_id, event),
                    ),
                ],
                spacing=0,
            )
        content_area = ft.GestureDetector(
            on_pan_update=(
                (lambda event: self.on_move(self.box_id, event))
                if self.on_move is not None and self.lane != "source" else None
            ),
            on_pan_end=(
                (lambda event: self.on_move_end(self.box_id, event))
                if self.on_move_end is not None and self.lane != "source" else None
            ),
            on_tap=(
                lambda event: self.on_edit(self.box_id, event)
                if self.on_edit is not None else None
            ),
            on_long_press=(
                lambda event: self.on_remove(self.box_id, event)
                if self.on_remove is not None else None
            ),
            content=ft.Container(
                width=self.width - port_width * port_count,
                height=self.height,
                padding=6 if compact else 10,
                alignment=ft.Alignment.CENTER_LEFT,
                content=body_content,
            ),
        )
        output_port = ft.Container(
            width=port_width,
            height=self.height,
            bgcolor=ft.Colors.BLUE_50,
            alignment=ft.Alignment.CENTER,
            content=None if compact else ft.Text("OUT", size=9, color=ft.Colors.BLUE_700),
        )

        if self.lane == "source":
            row_controls = [content_area, output_port]
        elif self.lane == "destination":
            row_controls = [input_port, content_area]
        else:
            row_controls = [input_port, content_area, output_port]

        return ft.Container(
            tooltip=self.explanation or None,
            visible=self.visible,
            width=self.width,
            height=self.height,
            bgcolor=ft.Colors.WHITE,
            border=ft.Border.all(2, ft.Colors.RED_700 if self.warning else ft.Colors.BLUE_300),
            border_radius=6 if compact else 12,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            shadow=ft.BoxShadow(
                blur_radius=8,
                color=ft.Colors.with_opacity(0.12, ft.Colors.BLACK),
                offset=ft.Offset(0, 3),
            ),
            content=ft.Row(
                row_controls,
                spacing=0,
            ),
        )

    def as_connectable_object(self):
        """Adapt this box for the generic DragToConnect component."""
        start_region = (0.8, 0.0, 1.0, 1.0)
        end_region = (0.0, 0.0, 1.0, 1.0)
        if self.lane == "source":
            # The whole compact source card is a connection drag handle.
            start_region = (0.0, 0.0, 1.0, 1.0)
            end_region = (2.0, 2.0, 2.0, 2.0)
        elif self.lane == "destination":
            start_region = (2.0, 2.0, 2.0, 2.0)
            end_region = (0.0, 0.0, 1.0, 1.0)

        return ConnectableObject(
            control=self.build_control(),
            x=self.x,
            y=self.y,
            width=self.width,
            height=self.height,
            # Draw flows from the right edge to the target's left edge.
            start_anchor=(1.0, 0.5),
            end_anchor=(0.0, 0.5),
            start_region=start_region,
            end_region=end_region,
        )
