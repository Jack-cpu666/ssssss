# Client implementation (client.py) using ctypes for input control
# Runs on the Windows PC to capture screen and execute commands

import socketio
import mss
import io
import base64
import time
import threading
import os
import sys
from PIL import Image
import ctypes
import ctypes.wintypes
import math

# --- Configuration ---
SERVER_URL = os.environ.get('REMOTE_SERVER_URL', 'https://ssppoo.onrender.com')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too') # MUST MATCH SERVER

# Screen capture settings
FPS = 10  # Can increase slightly with ctypes potentially being faster
JPEG_QUALITY = 70 # Adjust quality/performance

# Mouse Smoothing settings
MOUSE_MOVE_DURATION = 0.05 # Time (seconds) for the smoothed move animation
MOUSE_MOVE_STEPS = 5      # Number of intermediate steps for smoothing

# --- CTypes Constants and Structures ---
# Constants for mouse_event
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000 # Horizontal wheel
MOUSEEVENTF_ABSOLUTE = 0x8000

# Constants for keybd_event
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001 # For keys like Right Ctrl, Right Alt, Arrow keys, etc.

# Basic Virtual-Key Code mapping (Expand as needed)
# Based on https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
VK_CODE_MAP = {
    # Modifiers (Special handling often needed for L/R versions)
    'Shift': 0x10, 'ShiftLeft': 0xA0, 'ShiftRight': 0xA1,
    'Control': 0x11, 'ControlLeft': 0xA2, 'ControlRight': 0xA3,
    'Alt': 0x12, 'AltLeft': 0xA4, 'AltRight': 0xA5,
    'Meta': 0x5B, 'MetaLeft': 0x5B, 'MetaRight': 0x5C, # Windows Key
    'CapsLock': 0x14,
    'Tab': 0x09,
    'Enter': 0x0D,
    'Escape': 0x1B,
    'Space': 0x20, ' ': 0x20,
    'Backspace': 0x08,
    'Delete': 0x2E,
    'Insert': 0x2D,
    'Home': 0x24,
    'End': 0x23,
    'PageUp': 0x21,
    'PageDown': 0x22,
    # Arrow Keys
    'ArrowUp': 0x26,
    'ArrowDown': 0x28,
    'ArrowLeft': 0x25,
    'ArrowRight': 0x27,
    # Function Keys
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
    'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    # Letters (Case insensitive mapping, VK codes are for uppercase)
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45, 'f': 0x46, 'g': 0x47,
    'h': 0x48, 'i': 0x49, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E,
    'o': 0x4F, 'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54, 'u': 0x55,
    'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
    # Numbers (Top row)
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    # Basic Punctuation (May vary with keyboard layout)
    '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
    # Numpad Keys (Example) - Need separate mapping if distinction required
    # 'Numpad0': 0x60, ...
}

# Extended key flag needed for certain keys
EXTENDED_KEYS = {
    0xA3, # Right Ctrl
    0xA5, # Right Alt
    0x2E, # Delete
    0x2D, # Insert
    0x24, # Home
    0x23, # End
    0x21, # PageUp
    0x22, # PageDown
    0x26, # ArrowUp
    0x28, # ArrowDown
    0x25, # ArrowLeft
    0x27, # ArrowRight
}


user32 = ctypes.windll.user32
# Get screen dimensions using ctypes (alternative to mss for this specific task)
screen_width = user32.GetSystemMetrics(0) # SM_CXSCREEN
screen_height = user32.GetSystemMetrics(1) # SM_CYSCREEN

# --- Global Variables ---
sio = socketio.Client(logger=False, engineio_logger=False, reconnection_attempts=5, reconnection_delay=3)
stop_event = threading.Event()
capture_thread = None
input_thread = None # Optional thread for input queue if needed
is_connected = False
monitor_dimensions = {"width": screen_width, "height": screen_height} # Use ctypes derived dimensions
last_mouse_pos = {'x': 0, 'y': 0} # Track last known mouse position for smooth move


# --- Input Simulation Functions (using CTypes) ---

def get_vk_code(key_name_or_code):
    """ Tries to map browser key/code names to Windows VK codes. """
    # Prefer 'code' if available (e.g., 'KeyA', 'Digit1') as it's layout independent
    # Fallback to 'key' (e.g., 'a', ';', 'Enter')
    key_lower = key_name_or_code.lower()

    # Direct lookup using common names/codes
    if key_name_or_code in VK_CODE_MAP:
        return VK_CODE_MAP[key_name_or_code]
    if key_lower in VK_CODE_MAP:
        return VK_CODE_MAP[key_lower]

    # Handle 'KeyA', 'KeyB', etc.
    if key_name_or_code.startswith('Key'):
        char = key_name_or_code[3:].lower()
        if char in VK_CODE_MAP:
            return VK_CODE_MAP[char]

    # Handle 'Digit1', 'Digit2', etc.
    if key_name_or_code.startswith('Digit'):
        char = key_name_or_code[5:]
        if char in VK_CODE_MAP:
            return VK_CODE_MAP[char]

    # Add more specific mappings here if needed (Numpad keys, etc.)
    print(f"Warning: Unmapped key/code: {key_name_or_code}")
    return None


def press_key(vk_code):
    """ Sends a key down event using keybd_event. """
    if vk_code is None: return
    flags = KEYEVENTF_KEYDOWN
    if vk_code in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    # Use MapVirtualKey to get scan code (optional, 0 often works)
    # scan_code = user32.MapVirtualKeyW(vk_code, 0) # MAPVK_VK_TO_VSC
    user32.keybd_event(vk_code, 0, flags, 0)
    # print(f"Pressed VK: {hex(vk_code)}") # Debug

def release_key(vk_code):
    """ Sends a key up event using keybd_event. """
    if vk_code is None: return
    flags = KEYEVENTF_KEYUP
    if vk_code in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    # scan_code = user32.MapVirtualKeyW(vk_code, 0)
    user32.keybd_event(vk_code, 0, flags, 0)
    # print(f"Released VK: {hex(vk_code)}") # Debug


def mouse_move_to(x, y, smooth=True):
    """ Moves the mouse cursor to absolute coordinates (x, y). """
    global last_mouse_pos
    target_x = max(0, min(int(x), screen_width - 1))
    target_y = max(0, min(int(y), screen_height - 1))

    if not smooth or (target_x == last_mouse_pos['x'] and target_y == last_mouse_pos['y']):
        user32.SetCursorPos(target_x, target_y)
    else:
        start_x = last_mouse_pos['x']
        start_y = last_mouse_pos['y']
        start_time = time.monotonic()
        end_time = start_time + MOUSE_MOVE_DURATION

        while time.monotonic() < end_time:
            elapsed = time.monotonic() - start_time
            progress = min(elapsed / MOUSE_MOVE_DURATION, 1.0)
            # Simple linear interpolation (could use easing functions)
            current_x = int(start_x + (target_x - start_x) * progress)
            current_y = int(start_y + (target_y - start_y) * progress)
            user32.SetCursorPos(current_x, current_y)
            # Need a small sleep to allow steps, but too long makes it jerky
            step_sleep = MOUSE_MOVE_DURATION / MOUSE_MOVE_STEPS / 2 # Heuristic
            time.sleep(max(0.001, step_sleep)) # Minimum sleep

        # Ensure final position is exact
        user32.SetCursorPos(target_x, target_y)

    last_mouse_pos = {'x': target_x, 'y': target_y}


def mouse_click(button='left'):
    """ Performs a mouse click using mouse_event. """
    if button == 'left':
        down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button == 'right':
        down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    elif button == 'middle':
        down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
    else:
        print(f"Unsupported click button: {button}")
        return

    user32.mouse_event(down_flag, 0, 0, 0, 0)
    time.sleep(0.01) # Small delay between down/up
    user32.mouse_event(up_flag, 0, 0, 0, 0)

def mouse_scroll(dx=0, dy=0):
    """ Performs mouse wheel scroll using mouse_event. """
    # dy: positive down, negative up
    # dx: positive right, negative left
    wheel_delta_unit = 120 # Standard unit for wheel delta

    if dy != 0:
        scroll_amount = -int(dy * wheel_delta_unit) # Invert dy for MOUSEEVENTF_WHEEL
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, scroll_amount, 0)

    if dx != 0:
         scroll_amount = int(dx * wheel_delta_unit)
         user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, scroll_amount, 0)


# --- Utility Functions ---
def get_primary_monitor_dimensions_mss():
    """Gets the dimensions of the primary monitor using mss (as fallback)."""
    try:
        with mss.mss() as sct:
            if len(sct.monitors) > 1:
                monitor = sct.monitors[1]
                return {"width": monitor["width"], "height": monitor["height"]}
            elif len(sct.monitors) == 1:
                 monitor = sct.monitors[0]
                 if monitor["width"] > 0 and monitor["height"] > 0:
                      return {"width": monitor["width"], "height": monitor["height"]}
            return None
    except Exception as e:
        print(f"Error getting monitor dimensions via mss: {e}")
        return None

# --- Screen Capture Thread ---
def capture_and_send_screen():
    """Captures the screen and sends it to the server via SocketIO."""
    global is_connected, monitor_dimensions
    last_capture_time = 0
    interval = 1.0 / FPS

    if not monitor_dimensions:
        print("Error: Monitor dimensions not available. Trying mss fallback...")
        monitor_dimensions = get_primary_monitor_dimensions_mss()
        if not monitor_dimensions:
             print("FATAL: Could not determine monitor dimensions.")
             stop_event.set()
             return

    monitor_area = {"top": 0, "left": 0, "width": monitor_dimensions["width"], "height": monitor_dimensions["height"]}
    print(f"Capture thread starting for area: {monitor_area}")

    try:
        with mss.mss() as sct_instance:
            while not stop_event.is_set():
                if not is_connected:
                    time.sleep(0.5)
                    continue

                current_time = time.time()
                sleep_duration = interval - (current_time - last_capture_time)
                if sleep_duration > 0:
                    time.sleep(sleep_duration)

                last_capture_time = time.time()

                try:
                    img = sct_instance.grab(monitor_area)
                    pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                    buffer = io.BytesIO()
                    pil_img.save(buffer, format='JPEG', quality=JPEG_QUALITY)
                    buffer.seek(0)
                    img_base64 = base64.b64encode(buffer.read()).decode('utf-8')

                    if is_connected:
                        sio.emit('screen_data', {'image': img_base64})

                except mss.ScreenShotError as ex:
                    print(f"Screen capture error: {ex}. Retrying...")
                    time.sleep(1)
                except socketio.exceptions.BadNamespaceError:
                    print("SocketIO BadNamespaceError during send. Disconnected?")
                    is_connected = False
                    time.sleep(2)
                except Exception as e:
                    print(f"An error occurred in capture loop: {e}")
                    if not sio.connected:
                         is_connected = False
                    time.sleep(1)

    except Exception as e:
        print(f"FATAL: Failed to initialize mss within capture thread: {e}")
        stop_event.set()

    print("Screen capture thread stopped.")


# --- SocketIO Event Handlers ---
@sio.event
def connect():
    global is_connected, monitor_dimensions, last_mouse_pos
    print(f"Successfully connected to server: {SERVER_URL} (sid: {sio.sid})")

    # Use ctypes dimensions primarily
    monitor_dimensions = {"width": screen_width, "height": screen_height}
    print(f"Primary monitor dimensions (ctypes): {monitor_dimensions['width']}x{monitor_dimensions['height']}")

    # Get initial mouse position
    point = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    last_mouse_pos = {'x': point.x, 'y': point.y}
    print(f"Initial mouse position: {last_mouse_pos}")


    print("Registering with server...")
    is_connected = True
    try:
        sio.emit('register_client', {'token': ACCESS_PASSWORD})
    except Exception as e:
        print(f"Error emitting registration: {e}")
        is_connected = False
        if sio.connected:
            sio.disconnect()

@sio.event
def connect_error(data):
    global is_connected
    print(f"Connection failed: {data}")
    is_connected = False
    stop_event.set()

@sio.event
def disconnect():
    global is_connected
    print("Disconnected from server.")
    is_connected = False
    stop_event.set() # Signal capture thread to stop

@sio.on('registration_success')
def on_registration_success():
    global capture_thread
    print("Client registration successful.")
    if capture_thread is None or not capture_thread.is_alive():
        print("Starting screen capture thread...")
        stop_event.clear()
        try:
            capture_thread = threading.Thread(target=capture_and_send_screen, args=(), daemon=True)
            capture_thread.start()
        except Exception as e:
             print(f"Failed to start capture thread: {e}")
             stop_event.set()
             is_connected = False
             if sio.connected:
                 sio.disconnect()
    else:
        print("Capture thread already running.")

@sio.on('registration_fail')
def on_registration_fail(data):
    print(f"Client registration failed: {data.get('message', 'No reason given')}")
    is_connected = False
    sio.disconnect()

# --- MODIFIED Command Handler ---
@sio.on('command')
def handle_command(data):
    action = data.get('action')
    # print(f"Received command: {action}", data) # Debug

    if not is_connected:
        print("Cannot execute command, not connected/registered.")
        return

    try:
        if action == 'move':
            x = data.get('x')
            y = data.get('y')
            if x is not None and y is not None:
                mouse_move_to(x, y, smooth=True) # Use smooth move

        elif action == 'click':
            button = data.get('button', 'left')
            x = data.get('x') # Optional coordinates for click
            y = data.get('y')
            if x is not None and y is not None:
                mouse_move_to(x, y, smooth=False) # Move instantly before click
            mouse_click(button)

        elif action == 'keydown':
            key_name = data.get('key') # e.g., 'A', 'Enter', 'Shift'
            key_code_str = data.get('code') # e.g., 'KeyA', 'Enter', 'ShiftLeft'
            # Prefer 'code' for mapping if available, fallback to 'key'
            map_key = key_code_str if key_code_str else key_name
            vk_code = get_vk_code(map_key)
            if vk_code:
                 press_key(vk_code)
            else:
                 print(f"Could not map keydown: key='{key_name}', code='{key_code_str}'")

        elif action == 'keyup':
            key_name = data.get('key')
            key_code_str = data.get('code')
            map_key = key_code_str if key_code_str else key_name
            vk_code = get_vk_code(map_key)
            if vk_code:
                 release_key(vk_code)
            else:
                 print(f"Could not map keyup: key='{key_name}', code='{key_code_str}'")

        elif action == 'scroll':
            dx = data.get('dx', 0) # Horizontal scroll clicks
            dy = data.get('dy', 0) # Vertical scroll clicks (positive=down from browser)
            mouse_scroll(dx=dx, dy=dy)

        # Removed 'keypress' action as we now handle keydown/keyup
        # Need to handle double_click if required (sequence of clicks)

        else:
            print(f"Unknown command action: {action}")

    except Exception as e:
        print(f"Error executing command {data}: {e}")
        print(traceback.format_exc())


# --- Main Execution ---
def main():
    global capture_thread, is_connected
    print("Starting Remote Control Client (CTypes Mode)...")
    print(f"Server URL: {SERVER_URL}")
    print(f"Using Password: {'*' * len(ACCESS_PASSWORD) if ACCESS_PASSWORD else 'None'}")
    print(f"Detected Screen Resolution (CTypes): {screen_width}x{screen_height}")

    while not stop_event.is_set():
        if is_connected:
             time.sleep(1)
             continue

        is_connected = False

        try:
            print(f"Attempting connection to {SERVER_URL}...")
            sio.connect(SERVER_URL,
                        transports=['websocket'],
                        wait_timeout=10)
            sio.wait() # Blocks until disconnect
            print("sio.wait() finished (disconnected).")

        except socketio.exceptions.ConnectionError as e:
            print(f"Connection Error: {e}. Retrying in {sio.reconnection_delay}s...")
        except Exception as e:
             print(f"An unexpected error occurred in connection loop: {e}. Retrying in {sio.reconnection_delay}s...")

        # Cleanup after disconnect or failure
        print("Performing cleanup...")
        is_connected = False
        stop_event.set() # Signal capture thread
        if capture_thread and capture_thread.is_alive():
            print("Waiting for capture thread to join...")
            capture_thread.join(timeout=2)
        capture_thread = None

        if not stop_event.is_set(): # Check if exit requested during cleanup/wait
            print(f"Waiting {sio.reconnection_delay}s before retrying connection...")
            stop_event.wait(timeout=sio.reconnection_delay)
            if stop_event.is_set():
                 print("Exit requested during retry wait.")
                 break
            else:
                 stop_event.clear() # Clear for next attempt
        else:
             print("Stop event set, exiting connection loop.")
             break


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Initiating shutdown...")
        stop_event.set()
    finally:
        print("Performing final client cleanup...")
        stop_event.set()
        if sio and sio.connected:
            print("Attempting final disconnection...")
            sio.disconnect()

        if capture_thread and capture_thread.is_alive():
             print("Waiting for capture thread final exit...")
             capture_thread.join(timeout=3)

        print("Client shutdown complete.")
        sys.exit(0)