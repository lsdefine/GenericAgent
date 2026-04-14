"""Desktop Pet with Skin System — Cross-platform with True Transparency"""
import os
import re
import sys
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io

PORT = 51983
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
SKINS_DIR = os.path.join(SCRIPT_DIR, 'skins')
PET_MARGIN_X = 24
PET_MARGIN_Y = 120
DEFAULT_WINDOW_TITLE = 'GenericAgent'


def _clamp(value, lo, hi):
    return max(lo, min(value, hi))


def _pet_position(screen_left, screen_top, screen_width, screen_height, pet_width, pet_height):
    max_x = max(screen_left, screen_left + screen_width - pet_width - PET_MARGIN_X)
    max_y = max(screen_top, screen_top + screen_height - pet_height - PET_MARGIN_Y)
    x_pos = _clamp(screen_left + screen_width - pet_width - PET_MARGIN_X, screen_left, max_x)
    y_pos = _clamp(screen_top + screen_height - pet_height - PET_MARGIN_Y, screen_top, max_y)
    return int(x_pos), int(y_pos)


def _parent_alive(parent_pid):
    if not parent_pid:
        return True
    try:
        os.kill(parent_pid, 0)
        return True
    except OSError:
        return False


def _find_streamlit_screen_rect(window_title):
    title = (window_title or DEFAULT_WINDOW_TITLE).lower()
    if sys.platform == 'darwin':
        try:
            import Quartz
            from AppKit import NSScreen
            screens = list(NSScreen.screens() or [])
            windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
            for window in windows:
                name = str(window.get(Quartz.kCGWindowName) or '').lower()
                if title not in name:
                    continue
                bounds = window.get(Quartz.kCGWindowBounds) or {}
                center_x = float(bounds.get('X', 0)) + float(bounds.get('Width', 0)) / 2
                for screen in screens:
                    frame = screen.visibleFrame()
                    left = frame.origin.x
                    right = left + frame.size.width
                    if left <= center_x <= right:
                        return frame.origin.x, frame.origin.y, frame.size.width, frame.size.height
                if screens:
                    frame = screens[0].visibleFrame()
                    return frame.origin.x, frame.origin.y, frame.size.width, frame.size.height
        except Exception:
            pass
    elif sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            monitor_info_flag = 2
            target = {'rect': None}

            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

            class RECT(ctypes.Structure):
                _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', RECT), ('rcWork', RECT), ('dwFlags', wintypes.DWORD)]

            def callback(hwnd, _):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, len(buf))
                if title not in buf.value.lower():
                    return True
                monitor = user32.MonitorFromWindow(hwnd, monitor_info_flag)
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    rect = info.rcWork
                    target['rect'] = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
                    return False
                return True

            user32.EnumWindows(EnumWindowsProc(callback), 0)
            return target['rect']
        except Exception:
            pass
    return None


def _rect_key(rect):
    return tuple(int(v) for v in rect) if rect else None

class SkinLoader:
    """Load and parse skin configuration"""
    @staticmethod
    def load_skin(skin_path):
        """Load skin.json and return skin config"""
        config_file = os.path.join(skin_path, 'skin.json')
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"skin.json not found in {skin_path}")

        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        if 'animations' not in config:
            raise ValueError("skin.json must contain 'animations' field")

        config['path'] = skin_path
        return config

    @staticmethod
    def list_skins():
        """List all available skins"""
        if not os.path.exists(SKINS_DIR):
            return []

        skins = []
        for item in os.listdir(SKINS_DIR):
            skin_path = os.path.join(SKINS_DIR, item)
            if os.path.isdir(skin_path):
                config_file = os.path.join(skin_path, 'skin.json')
                if os.path.exists(config_file):
                    skins.append(item)
        return skins

class AnimationLoader:
    """Load animation frames from sprite sheet"""
    @staticmethod
    def load_sprite_frames(skin_path, anim_config):
        """Load frames from sprite sheet"""
        file_path = os.path.join(skin_path, anim_config['file'])
        sprite_config = anim_config['sprite']

        img = Image.open(file_path)
        frames = []

        frame_width = sprite_config['frameWidth']
        frame_height = sprite_config['frameHeight']
        frame_count = sprite_config['frameCount']
        columns = sprite_config['columns']
        start_frame = sprite_config.get('startFrame', 0)

        for i in range(frame_count):
            frame_idx = start_frame + i
            row = frame_idx // columns
            col = frame_idx % columns

            x = col * frame_width
            y = row * frame_height

            frame = img.crop((x, y, x + frame_width, y + frame_height))
            frames.append(frame)

        return frames


def _find_bubble_asset():
    """Find user-provided bubble asset in project root."""
    candidates = [
        os.path.join(PROJECT_DIR, '聊天气泡.png'),
        os.path.join(PROJECT_DIR, 'bubble.png'),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _load_default_font(size):
    """Load a usable font for bubble text."""
    font_candidates = [
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simhei.ttf',
        'C:/Windows/Fonts/arial.ttf',
    ]
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _normalize_bubble_text(text):
    """Normalize text for fonts that cannot render some symbols."""
    text = (text or '').strip()
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    if lines:
        turn_match = re.match(r'^\s*🔄?\s*Turn\s+(\d+)\s*$', lines[0], flags=re.IGNORECASE)
        if turn_match:
            rest = '\n'.join(line.strip() for line in lines[1:] if line.strip())
            return f"Turn {turn_match.group(1)}: {rest}" if rest else f"Turn {turn_match.group(1)}:"
    return text.replace('🔄 Turn', 'Turn').replace('🔄', '').strip()


def _wrap_text_for_width(draw, text, font, max_width):
    """Wrap text to fit inside max_width."""
    text = _normalize_bubble_text(text)
    if not text:
        return ['']

    paragraphs = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    lines = []

    for paragraph in paragraphs:
        if not paragraph:
            lines.append('')
            continue

        current = ''
        for ch in paragraph:
            candidate = current + ch
            bbox = draw.textbbox((0, 0), candidate, font=font)
            width = bbox[2] - bbox[0]
            if current and width > max_width:
                lines.append(current)
                current = ch
            else:
                current = candidate
        if current:
            lines.append(current)

    return lines or ['']


def build_bubble_image(message, max_width=220):
    """Build a PIL image for the toast bubble using the user asset when available."""
    message = (message or '').strip()
    bubble_path = _find_bubble_asset()

    if bubble_path and os.path.exists(bubble_path):
        bubble = Image.open(bubble_path).convert('RGBA')
    else:
        bubble = Image.new('RGBA', (256, 128), (255, 255, 255, 0))
        draw = ImageDraw.Draw(bubble)
        draw.rounded_rectangle((8, 8, 247, 87), radius=12, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255), width=3)
        draw.polygon([(48, 87), (72, 87), (56, 112)], fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))

    bubble = ImageOps.contain(bubble, (max_width, max(64, int(max_width * bubble.height / bubble.width))), Image.NEAREST)

    font_size = max(12, bubble.height // 7)
    font = _load_default_font(font_size)
    draw = ImageDraw.Draw(bubble)

    pad_left = max(12, bubble.width // 16)
    pad_right = max(16, bubble.width // 10)
    pad_top = max(8, bubble.height // 10)
    pad_bottom = max(20, bubble.height // 3)
    text_area_width = max(36, bubble.width - pad_left - pad_right)

    lines = _wrap_text_for_width(draw, message, font, text_area_width)
    ascent, descent = font.getmetrics() if hasattr(font, 'getmetrics') else (font_size, font_size // 4)
    line_height = max(font_size, ascent + descent)
    max_lines = max(1, (bubble.height - pad_top - pad_bottom) // line_height)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            while last and draw.textbbox((0, 0), last + '…', font=font)[2] > text_area_width:
                last = last[:-1]
            lines[-1] = (last + '…') if last else '…'

    total_text_height = len(lines) * line_height
    y = pad_top + max(0, (bubble.height - pad_top - pad_bottom - total_text_height) // 2)

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = pad_left + (text_area_width - text_width) / 2
        draw.text((x, y), line, font=font, fill=(32, 32, 32, 255))
        y += line_height

    alpha = bubble.getchannel('A')
    bbox = alpha.getbbox()
    if bbox:
        bubble = bubble.crop(bbox)

    width, height = bubble.size
    alpha = bubble.getchannel('A')
    bottom_y = height - 1
    tail_x = width // 2
    for y in range(height - 1, -1, -1):
        xs = [x for x in range(width) if alpha.getpixel((x, y)) > 0]
        if xs:
            bottom_y = y
            tail_x = xs[len(xs) // 2]
            break

    return {
        'image': bubble,
        'size': bubble.size,
        'tail_tip': (tail_x, bottom_y),
    }

# ============================================================================
# Shared Base Class
# ============================================================================
class PetBase:
    """Shared logic for Mac and Windows pet implementations."""

    def __init__(self, parent_pid=None, window_title=DEFAULT_WINDOW_TITLE):
        self.parent_pid = parent_pid
        self.window_title = window_title or DEFAULT_WINDOW_TITLE
        self._screen_timer = None
        self._tracked_screen_rect = None

    def _schedule_main(self, fn):
        """Schedule fn on the GUI main thread. Subclasses must override."""
        raise NotImplementedError

    def set_state_safe(self, state):
        """Thread-safe wrapper for set_state."""
        self._schedule_main(lambda: self.set_state(state))

    def show_toast_safe(self, message):
        """Thread-safe wrapper for show_toast."""
        self._schedule_main(lambda m=message: self.show_toast(m))

    def _close(self):
        raise NotImplementedError

    def _current_position(self):
        raise NotImplementedError

    def _move_to(self, x_pos, y_pos):
        raise NotImplementedError

    def _sync_to_target_screen(self):
        raise NotImplementedError

    def _start_screen_tracking(self):
        def tick():
            if not _parent_alive(self.parent_pid):
                self._close()
                return
            self._sync_to_target_screen()
            self._screen_timer = self._schedule_delay(1000, tick)
        self._tracked_screen_rect = _rect_key(_find_streamlit_screen_rect(self.window_title))
        self._screen_timer = self._schedule_delay(1000, tick)

    def _schedule_delay(self, delay_ms, fn):
        raise NotImplementedError

    def _start_server(self):
        """Start HTTP control server."""
        pet = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)

                if 'state' in params:
                    state = params['state'][0]
                    pet.set_state_safe(state)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'ok')
                elif 'msg' in params:
                    msg = params['msg'][0]
                    pet.show_toast_safe(msg)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'ok')
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'?state=idle/walk/run/sprint or ?msg=hello')

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0))).decode()
                if body:
                    pet.show_toast_safe(body)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'ok')
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'empty body')

            def log_message(self, *a):
                pass

        try:
            HTTPServer.allow_reuse_address = True
            srv = HTTPServer(('127.0.0.1', PORT), Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            print(f'✓ Server: http://127.0.0.1:{PORT}/?state=walk')
        except OSError as e:
            if e.errno == 48:
                print(f'⚠ Port {PORT} already in use')
            else:
                raise


# ============================================================================
# macOS Implementation - Pure Cocoa with True Transparency
# ============================================================================
if sys.platform == 'darwin':
    from Cocoa import (
        NSApplication, NSWindow, NSImageView, NSImage, NSData, NSTimer,
        NSMenu, NSMenuItem, NSApp, NSFloatingWindowLevel, NSColor,
        NSBackingStoreBuffered, NSWindowStyleMaskBorderless,
        NSApplicationActivationPolicyAccessory
    )
    from Foundation import NSMakeRect, NSMakePoint, NSMakeSize
    from PyObjCTools import AppHelper
    import objc

    class MacPet(PetBase):
        def __init__(self, skin_name=None, parent_pid=None, window_title=DEFAULT_WINDOW_TITLE):
            super().__init__(parent_pid=parent_pid, window_title=window_title)
            self.app = NSApplication.sharedApplication()
            self.app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

            # Load skin
            self.load_skin(skin_name)

            # Get screen size
            from AppKit import NSScreen, NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorStationary
            screen = NSScreen.mainScreen() or NSScreen.screens()[0]
            rect = _find_streamlit_screen_rect(self.window_title)
            if rect:
                x_pos, y_pos = _pet_position(*rect, self.display_width, self.display_height)
            else:
                screen_frame = screen.visibleFrame()
                x_pos, y_pos = _pet_position(
                    screen_frame.origin.x,
                    screen_frame.origin.y,
                    screen_frame.size.width,
                    screen_frame.size.height,
                    self.display_width,
                    self.display_height,
                )

            # Create transparent window
            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(x_pos, y_pos, self.display_width, self.display_height),
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False
            )

            self.window.setOpaque_(False)
            self.window.setBackgroundColor_(NSColor.clearColor())
            self.window.setLevel_(NSFloatingWindowLevel)
            self.window.setMovableByWindowBackground_(True)
            self.window.setAcceptsMouseMovedEvents_(True)

            # Make window sticky across spaces (stays in fixed screen position)
            self.window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces |
                NSWindowCollectionBehaviorStationary
            )

            # Create custom view for handling mouse events
            from AppKit import NSView
            from objc import super as objc_super

            class DraggableImageView(NSView):
                """Custom view that handles dragging and double-click"""
                def initWithFrame_(self, frame):
                    self = objc_super(DraggableImageView, self).initWithFrame_(frame)
                    if self is None:
                        return None
                    self.image_view = NSImageView.alloc().initWithFrame_(self.bounds())
                    self.image_view.setImageScaling_(1)  # NSImageScaleProportionallyUpOrDown
                    self.addSubview_(self.image_view)

                    # Create overlay view for toast (always on top)
                    # Make it non-opaque so it doesn't block the image
                    self.overlay_view = NSView.alloc().initWithFrame_(self.bounds())
                    self.overlay_view.setWantsLayer_(True)
                    self.addSubview_(self.overlay_view)

                    self.drag_start = None
                    return self

                def mouseDown_(self, event):
                    """Handle mouse down for dragging"""
                    if event.clickCount() == 2:
                        # Double-click to quit
                        from AppKit import NSApp
                        NSApp.terminate_(None)
                    else:
                        # Start dragging
                        self.drag_start = event.locationInWindow()

                def mouseDragged_(self, event):
                    """Handle mouse drag"""
                    if self.drag_start:
                        current_location = event.locationInWindow()
                        window_frame = self.window().frame()

                        dx = current_location.x - self.drag_start.x
                        dy = current_location.y - self.drag_start.y

                        new_origin = NSMakePoint(
                            window_frame.origin.x + dx,
                            window_frame.origin.y + dy
                        )

                        self.window().setFrameOrigin_(new_origin)

                def acceptsFirstMouse_(self, event):
                    """Accept first mouse click"""
                    return True

            # Create draggable view
            self.content_view = DraggableImageView.alloc().initWithFrame_(
                NSMakeRect(0, 0, self.display_width, self.display_height)
            )
            self.image_view = self.content_view.image_view
            self.overlay_view = self.content_view.overlay_view
            self.window.setContentView_(self.content_view)

            # Animation state
            self.current_state = 'idle'
            self.frame_idx = 0

            # Toast state
            self.toast_label = None
            self.toast_timer = None
            self.toast_image = None
            self.toast_window = None

            # Start animation timer
            self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0 / self.animations[self.current_state]['fps'],
                self,
                'animate:',
                None,
                True
            )

            # Show window
            self.window.makeKeyAndOrderFront_(None)
            self._start_screen_tracking()

            # Start HTTP server
            self._start_server()

            print(f"✓ macOS Pet started at ({x_pos}, {y_pos})")
            print(f"  Animations: {', '.join(self.animations.keys())}")

        def load_skin(self, skin_name=None):
            """Load skin configuration and animations"""
            available_skins = SkinLoader.list_skins()
            if not available_skins:
                raise FileNotFoundError(f"No skins found in {SKINS_DIR}")

            if skin_name is None or skin_name not in available_skins:
                skin_name = available_skins[0]

            skin_path = os.path.join(SKINS_DIR, skin_name)
            self.skin_config = SkinLoader.load_skin(skin_path)

            # Get display size
            display_size = self.skin_config.get('size', {})
            self.display_width = display_size.get('width', 128)
            self.display_height = display_size.get('height', 128)

            # Load animations
            self.animations = {}
            for anim_name, anim_config in self.skin_config['animations'].items():
                pil_frames = AnimationLoader.load_sprite_frames(skin_path, anim_config)

                # Scale frames
                scaled_frames = []
                for frame in pil_frames:
                    if frame.mode != 'RGBA':
                        frame = frame.convert('RGBA')
                    scaled = frame.resize((self.display_width, self.display_height), Image.NEAREST)
                    scaled_frames.append(scaled)

                # Convert to NSImage with proper alpha handling
                ns_images = []
                for pil_img in scaled_frames:
                    # Ensure RGBA mode for transparency
                    if pil_img.mode != 'RGBA':
                        pil_img = pil_img.convert('RGBA')

                    # Convert PIL to PNG bytes (PNG preserves alpha channel)
                    png_buffer = io.BytesIO()
                    pil_img.save(png_buffer, format='PNG')
                    png_data = png_buffer.getvalue()

                    # Create NSImage from PNG data
                    ns_data = NSData.dataWithBytes_length_(png_data, len(png_data))
                    ns_image = NSImage.alloc().initWithData_(ns_data)
                    ns_images.append(ns_image)

                self.animations[anim_name] = {
                    'frames': ns_images,
                    'fps': anim_config.get('sprite', {}).get('fps', 6)
                }

        def animate_(self, timer):
            """Animation callback"""
            anim = self.animations[self.current_state]
            frames = anim['frames']

            if frames:
                self.image_view.setImage_(frames[self.frame_idx])
                self.frame_idx = (self.frame_idx + 1) % len(frames)

        def set_state(self, state):
            """Change animation state (must be called on main thread)"""
            if state in self.animations and state != self.current_state:
                self.current_state = state
                self.frame_idx = 0

                # Update timer interval
                self.timer.invalidate()
                self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                    1.0 / self.animations[self.current_state]['fps'],
                    self,
                    'animate:',
                    None,
                    True
                )
                print(f"→ State: {state}")

        def _schedule_main(self, fn):
            AppHelper.callAfter(fn)

        def _schedule_delay(self, delay_ms, fn):
            return NSTimer.scheduledTimerWithTimeInterval_repeats_block_(delay_ms / 1000.0, False, lambda _: fn())

        def _current_position(self):
            frame = self.window.frame()
            return int(frame.origin.x), int(frame.origin.y)

        def _move_to(self, x_pos, y_pos):
            self.window.setFrameOrigin_(NSMakePoint(x_pos, y_pos))

        def _close(self):
            if self.toast_timer:
                self.toast_timer.invalidate()
                self.toast_timer = None
            if self._screen_timer:
                self._screen_timer.invalidate()
                self._screen_timer = None
            if self.window:
                self.window.close()
            NSApp.terminate_(None)

        def _sync_to_target_screen(self):
            rect = _find_streamlit_screen_rect(self.window_title)
            rect_key = _rect_key(rect)
            if not rect_key:
                return
            current_x, current_y = self._current_position()
            if rect_key != self._tracked_screen_rect:
                self._tracked_screen_rect = rect_key
                x_pos, y_pos = _pet_position(*rect, self.display_width, self.display_height)
                if (current_x, current_y) != (x_pos, y_pos):
                    self._move_to(x_pos, y_pos)

        def show_toast(self, message):
            """Show toast message above pet"""
            from AppKit import NSImageView

            with open('/tmp/pet_toast_debug.log', 'a') as f:
                f.write(f"[DEBUG] show_toast called with: {message}\n")
                f.flush()

            if self.toast_window:
                self.toast_window.orderOut_(None)
                self.toast_window = None
                self.toast_label = None
            if self.toast_timer:
                self.toast_timer.invalidate()
                self.toast_timer = None

            bubble_info = build_bubble_image(message, max_width=max(180, min(260, self.display_width * 2)))
            bubble_pil = bubble_info['image']
            bubble_width, bubble_height = bubble_info['size']
            tail_x, tail_y = bubble_info['tail_tip']

            png_buffer = io.BytesIO()
            bubble_pil.save(png_buffer, format='PNG')
            png_data = png_buffer.getvalue()
            ns_data = NSData.dataWithBytes_length_(png_data, len(png_data))
            self.toast_image = NSImage.alloc().initWithData_(ns_data)

            pet_frame = self.window.frame()
            anchor_x = pet_frame.origin.x + self.display_width * 0.75
            anchor_y = pet_frame.origin.y + self.display_height * 1.65
            toast_x = anchor_x - tail_x
            toast_y = anchor_y - tail_y

            self.toast_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(toast_x, toast_y, bubble_width, bubble_height),
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False
            )
            self.toast_window.setOpaque_(False)
            self.toast_window.setBackgroundColor_(NSColor.clearColor())
            self.toast_window.setLevel_(NSFloatingWindowLevel)
            self.toast_window.setIgnoresMouseEvents_(True)
            self.toast_window.setHasShadow_(False)

            self.toast_label = NSImageView.alloc().initWithFrame_(
                NSMakeRect(0, 0, bubble_width, bubble_height)
            )
            self.toast_label.setImage_(self.toast_image)
            self.toast_label.setImageScaling_(0)
            self.toast_window.setContentView_(self.toast_label)
            self.toast_window.orderFrontRegardless()

            with open('/tmp/pet_toast_debug.log', 'a') as f:
                f.write(f"[DEBUG] Toast window shown at ({toast_x}, {toast_y}) size={bubble_info['size']} tail={bubble_info['tail_tip']}\n")
                f.flush()

            self.toast_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                3.0,
                self,
                'hideToast:',
                None,
                False
            )
            print(f"Toast: {message}")

        def hideToast_(self, timer):
            """Hide toast message"""
            if self.toast_window:
                self.toast_window.orderOut_(None)
                self.toast_window = None
            self.toast_label = None
            self.toast_image = None
            self.toast_timer = None

        def run(self):
            """Run the application"""
            AppHelper.runEventLoop()

# ============================================================================
# Windows Implementation - tkinter with transparentcolor
# ============================================================================
else:
    import tkinter as tk
    from PIL import ImageTk

    class WinPet(PetBase):
        def __init__(self, skin_name=None, parent_pid=None, window_title=DEFAULT_WINDOW_TITLE):
            super().__init__(parent_pid=parent_pid, window_title=window_title)
            self.root = tk.Tk()
            self.root.wm_attributes('-topmost', True)

            # Load skin
            self.load_skin(skin_name)

            # Setup window
            rect = _find_streamlit_screen_rect(self.window_title)
            if rect:
                x_pos, y_pos = _pet_position(*rect, self.display_width, self.display_height)
            else:
                screen_left = self.root.winfo_vrootx()
                screen_top = self.root.winfo_vrooty()
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                x_pos, y_pos = _pet_position(
                    screen_left,
                    screen_top,
                    screen_width,
                    screen_height,
                    self.display_width,
                    self.display_height,
                )

            self.root.geometry(f'{self.display_width}x{self.display_height}+{x_pos}+{y_pos}')
            self.root.overrideredirect(True)
            self.root.wm_attributes('-topmost', True)

            # Transparent background
            self.root.wm_attributes('-transparentcolor', '#F0F0F0')
            self.root.config(bg='#F0F0F0')

            # Create label
            self.label = tk.Label(self.root, bg='#F0F0F0', bd=0)
            self.label.pack()

            # Bind events
            self.label.bind('<Button-1>', lambda e: setattr(self, '_d', (e.x, e.y)))
            self.label.bind('<B1-Motion>', self._drag)
            self.label.bind('<Double-1>', lambda e: (self.root.destroy(), os._exit(0)))

            # Animation state
            self.current_state = 'idle'
            self.frame_idx = 0

            # Toast state
            self.toast_window = None
            self.toast_photo = None

            # Start animation
            self._animate()
            self._start_server()
            self._start_screen_tracking()

            print(f"✓ Windows Pet started at ({x_pos}, {y_pos})")
            print(f"  Animations: {', '.join(self.animations.keys())}")

            self.root.mainloop()

        def load_skin(self, skin_name=None):
            """Load skin configuration and animations"""
            available_skins = SkinLoader.list_skins()
            if not available_skins:
                raise FileNotFoundError(f"No skins found in {SKINS_DIR}")

            if skin_name is None or skin_name not in available_skins:
                skin_name = available_skins[0]

            skin_path = os.path.join(SKINS_DIR, skin_name)
            self.skin_config = SkinLoader.load_skin(skin_path)

            # Get display size
            display_size = self.skin_config.get('size', {})
            self.display_width = display_size.get('width', 128)
            self.display_height = display_size.get('height', 128)

            # Load animations
            self.animations = {}
            for anim_name, anim_config in self.skin_config['animations'].items():
                pil_frames = AnimationLoader.load_sprite_frames(skin_path, anim_config)

                # Scale and convert frames
                tk_frames = []
                for frame in pil_frames:
                    if frame.mode != 'RGBA':
                        frame = frame.convert('RGBA')
                    scaled = frame.resize((self.display_width, self.display_height), Image.NEAREST)
                    tk_frames.append(ImageTk.PhotoImage(scaled))

                self.animations[anim_name] = {
                    'frames': tk_frames,
                    'fps': anim_config.get('sprite', {}).get('fps', 6)
                }

        def set_state(self, state):
            """Change animation state"""
            if state in self.animations and state != self.current_state:
                self.current_state = state
                self.frame_idx = 0
                print(f"→ State: {state}")

        def _drag(self, e):
            x = self.root.winfo_x() + e.x - self._d[0]
            y = self.root.winfo_y() + e.y - self._d[1]
            self.root.geometry(f'+{x}+{y}')

        def _animate(self):
            """Animate current state"""
            if self.current_state not in self.animations:
                self.root.after(100, self._animate)
                return

            anim = self.animations[self.current_state]
            frames = anim['frames']

            if frames:
                self.label.config(image=frames[self.frame_idx])
                self.frame_idx = (self.frame_idx + 1) % len(frames)

            delay = int(1000 / anim['fps'])
            self.root.after(delay, self._animate)

        def show_toast(self, message):
            """Show toast message above pet"""
            if self.toast_window:
                try:
                    self.toast_window.destroy()
                except:
                    pass
                self.toast_window = None

            bubble_info = build_bubble_image(message, max_width=max(180, min(260, self.display_width * 2)))
            bubble_pil = bubble_info['image']
            bubble_width, bubble_height = bubble_info['size']
            tail_x, tail_y = bubble_info['tail_tip']

            self.toast_photo = ImageTk.PhotoImage(bubble_pil)

            self.toast_window = tk.Toplevel(self.root)
            self.toast_window.overrideredirect(True)
            self.toast_window.wm_attributes('-topmost', True)
            self.toast_window.wm_attributes('-transparentcolor', '#00ff01')
            self.toast_window.config(bg='#00ff01')

            toast_label = tk.Label(
                self.toast_window,
                image=self.toast_photo,
                bg='#00ff01',
                bd=0,
                highlightthickness=0
            )
            toast_label.pack()

            pet_x = self.root.winfo_x()
            pet_y = self.root.winfo_y()
            anchor_x = pet_x + int(self.display_width * 0.75)
            anchor_y = pet_y
            toast_x = anchor_x - tail_x
            toast_y = anchor_y - bubble_height

            self.toast_window.geometry(f'{bubble_width}x{bubble_height}+{toast_x}+{toast_y}')

            self.root.after(3000, self._hide_toast)
            print(f"Toast: {message}")

        def _hide_toast(self):
            """Hide toast message"""
            if self.toast_window:
                try:
                    self.toast_window.destroy()
                    self.toast_window = None
                except:
                    pass

        def _schedule_main(self, fn):
            self.root.after(0, fn)

        def _schedule_delay(self, delay_ms, fn):
            return self.root.after(delay_ms, fn)

        def _current_position(self):
            return self.root.winfo_x(), self.root.winfo_y()

        def _move_to(self, x_pos, y_pos):
            self.root.geometry(f'+{x_pos}+{y_pos}')

        def _close(self):
            if self.toast_window:
                try:
                    self.toast_window.destroy()
                except:
                    pass
                self.toast_window = None
            self.root.destroy()

        def _sync_to_target_screen(self):
            rect = _find_streamlit_screen_rect(self.window_title)
            rect_key = _rect_key(rect)
            if not rect_key:
                return
            current_x, current_y = self._current_position()
            if rect_key != self._tracked_screen_rect:
                self._tracked_screen_rect = rect_key
                x_pos, y_pos = _pet_position(*rect, self.display_width, self.display_height)
                if (current_x, current_y) != (x_pos, y_pos):
                    self._move_to(x_pos, y_pos)

        def run(self):
            """Run the application (already in mainloop)"""
            pass

if __name__ == '__main__':
    import argparse
    import socket

    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-pid', type=int, default=0)
    parser.add_argument('--window-title', default=DEFAULT_WINDOW_TITLE)
    args = parser.parse_args()

    # Singleton: if port already in use, another instance is running
    _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _s.connect(('127.0.0.1', PORT))
        _s.close()
        print(f'⚠ Pet already running on port {PORT}, exiting.')
        sys.exit(0)
    except ConnectionRefusedError:
        pass

    if sys.platform == 'darwin':
        pet = MacPet(parent_pid=args.parent_pid, window_title=args.window_title)
        pet.run()
    else:
        pet = WinPet(parent_pid=args.parent_pid, window_title=args.window_title)
