import asyncio
import unittest

from textual import events
from textual.widget import Widget

from frontends.tuiapp_v2 import GenericAgentTUI, SelectableStatic


class FakeScreen:
    def __init__(self, widget, offset):
        self.widget = widget
        self.offset = offset
        self.cleared = False

    def get_widget_and_offset_at(self, x, y):
        return self.widget, self.offset

    def clear_selection(self):
        self.cleared = True


def make_app(screen):
    app = GenericAgentTUI()
    app._screen_stack.append(screen)
    return app


def mouse_down():
    return events.MouseDown(None, 3, 4, 0, 0, 1, False, False, False, 3, 4)


def mouse_move():
    return events.MouseMove(None, 3, 4, 0, 0, 1, False, False, False, 3, 4)


def mouse_up():
    return events.MouseUp(None, 3, 4, 0, 0, 1, False, False, False, 3, 4)


class TuiStaleSelectableTest(unittest.TestCase):
    def test_stale_selectable_mouse_down_is_stopped_and_clears_selection(self):
        screen = FakeScreen(SelectableStatic("stale"), object())
        app = make_app(screen)
        event = mouse_down()

        self.assertTrue(app._is_stale_selectable_mouse_event(event))
        asyncio.run(app.on_event(event))

        self.assertTrue(event._stop_propagation)
        self.assertTrue(screen.cleared)

    def test_stale_selectable_mouse_move_is_stopped_without_clearing_selection(self):
        screen = FakeScreen(SelectableStatic("stale"), object())
        app = make_app(screen)
        event = mouse_move()

        self.assertTrue(app._is_stale_selectable_mouse_event(event))
        asyncio.run(app.on_event(event))

        self.assertTrue(event._stop_propagation)
        self.assertFalse(screen.cleared)

    def test_valid_selectable_parent_is_not_treated_as_stale(self):
        widget = SelectableStatic("mounted")
        parent = Widget()
        widget._parent = parent
        app = make_app(FakeScreen(widget, object()))

        self.assertFalse(app._is_stale_selectable_mouse_event(mouse_down()))

    def test_missing_selection_offset_and_mouse_up_are_not_treated_as_stale(self):
        widget = SelectableStatic("stale")
        app = make_app(FakeScreen(widget, None))

        self.assertFalse(app._is_stale_selectable_mouse_event(mouse_down()))

        app = make_app(FakeScreen(widget, object()))
        self.assertFalse(app._is_stale_selectable_mouse_event(mouse_up()))


if __name__ == "__main__":
    unittest.main()
