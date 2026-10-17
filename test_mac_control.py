"""Regression checks for Cocoa activation and synthetic keyboard state."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

if sys.platform == 'darwin':
    sys.path.insert(0, str(Path(__file__).parent / 'memory'))
    import macljqCtrl as control


@unittest.skipUnless(sys.platform == 'darwin', 'macOS control only')
class ActivationTests(unittest.TestCase):
    def activate(self, accepted=True, becomes_active=True):
        state = {'foreground': 101}
        app = Mock()
        app.activateWithOptions_.return_value = accepted
        app.isActive.side_effect = lambda: state['foreground'] == 202
        workspace = Mock()
        workspace.frontmostApplication.return_value.processIdentifier.side_effect = lambda: state['foreground']
        loop = Mock()

        def process_notifications(_deadline):
            if accepted and becomes_active:
                state['foreground'] = 202

        loop.runUntilDate_.side_effect = process_notifications
        with patch.object(control, 'NSWorkspace', SimpleNamespace(sharedWorkspace=lambda: workspace)), \
             patch.object(control, 'NSRunningApplication', SimpleNamespace(runningApplicationWithProcessIdentifier_=lambda pid: app)), \
             patch.object(control, 'NSRunLoop', SimpleNamespace(currentRunLoop=lambda: loop), create=True), \
             patch.object(control, 'NSDate', SimpleNamespace(dateWithTimeIntervalSinceNow_=lambda seconds: seconds), create=True), \
             patch.object(control.time, 'sleep'):
            result = control.ActivateApp(202)
            observed_pid = workspace.frontmostApplication().processIdentifier()
        return result, observed_pid

    def test_foreground_cache_is_current_when_activation_returns(self):
        result, observed_pid = self.activate()
        self.assertTrue(result)
        self.assertEqual(observed_pid, 202)

    def test_rejected_activation_is_not_reported_as_success(self):
        self.assertFalse(self.activate(accepted=False)[0])

    def test_accepted_but_inactive_application_is_not_success(self):
        self.assertFalse(self.activate(becomes_active=False)[0])


@unittest.skipUnless(sys.platform == 'darwin', 'macOS control only')
class KeyboardTests(unittest.TestCase):
    def events(self, action):
        quartz = Mock()
        quartz.CGEventCreateKeyboardEvent.side_effect = lambda source, key, down: {'flags': 1 << 20, 'down': down}
        quartz.CGEventSetFlags.side_effect = lambda event, flags: event.update(flags=flags)
        sent = []
        with patch.object(control, 'Quartz', quartz), \
             patch.object(control, '_post', side_effect=lambda event: sent.append(event.copy())), \
             patch.object(control.time, 'sleep'):
            action()
        return sent

    def test_shortcut_releases_its_modifiers(self):
        events = self.events(lambda: control._key_tap(0, 1 << 20))
        self.assertEqual([e['flags'] for e in events], [1 << 20, 0])

    def test_plain_key_does_not_inherit_a_previous_shortcut(self):
        events = self.events(lambda: control._key_tap(36))
        self.assertEqual([e['flags'] for e in events], [0, 0])

    def test_unicode_text_does_not_inherit_command(self):
        events = self.events(lambda: control.TypeText('中文'))
        self.assertEqual([e['flags'] for e in events], [0, 0, 0, 0])


if __name__ == '__main__':
    unittest.main()
