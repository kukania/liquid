import flet as ft

# The reusable module contains connection behavior, not box styling.
from drag_to_connect import ConnectableObject, DragToConnect


AREA_WIDTH = 900
AREA_HEIGHT = 500
BOX_WIDTH = 150
BOX_HEIGHT = 90


def main(page: ft.Page):
    # Configure the application window.
    page.title = "Drag & Connect Boxes"
    page.window.width = 980
    page.window.height = 640
    page.bgcolor = "#F5F7FB"
    page.padding = 20

    # These coordinates are relative to the connector's 900 x 500 Stack.
    positions = {
        "A": {"x": 80, "y": 110, "w": BOX_WIDTH, "h": BOX_HEIGHT},
        "B": {"x": 500, "y": 160, "w": BOX_WIDTH, "h": BOX_HEIGHT},
        "C": {"x": 300, "y": 330, "w": BOX_WIDTH, "h": BOX_HEIGHT},
    }

    def make_box(name):
        """Create the demo visual; DragToConnect works with other controls too."""
        return ft.Container(
            width=BOX_WIDTH,
            height=BOX_HEIGHT,
            bgcolor="#FFFFFF",
            border=ft.Border.all(2, ft.Colors.BLUE_GREY_200),
            border_radius=16,
            alignment=ft.Alignment.CENTER,
            shadow=ft.BoxShadow(
                blur_radius=12,
                color=ft.Colors.with_opacity(0.15, ft.Colors.BLACK),
                offset=ft.Offset(0, 4),
            ),
            content=ft.Column(
                [
                    ft.Text(name, size=22, weight="bold"),
                    ft.Text("drag from me", size=11, color=ft.Colors.GREY_700),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    # Pair each visual control with the geometry needed for drawing and hit tests.
    # start_anchor and end_anchor are omitted, so their defaults are used:
    # bottom-center for outgoing lines and top-center for incoming lines.
    objects = {
        name: ConnectableObject(
            control=make_box(name),
            x=position["x"],
            y=position["y"],
            width=position["w"],
            height=position["h"],
        )
        for name, position in positions.items()
    }

    # The component wraps these controls in gesture detectors and adds a canvas.
    connector = DragToConnect(
        objects=objects,
        width=AREA_WIDTH,
        height=AREA_HEIGHT,
    )

    # connector.view contains the drawing area, status text, and clear button.
    page.add(
        ft.Column(
            [
                ft.Text("Drag & Connect", size=28, weight="bold"),
                connector.view,
            ],
            spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )
    )


if __name__ == "__main__":
    ft.run(main)
