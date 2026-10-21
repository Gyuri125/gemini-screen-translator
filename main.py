import os
import re
import io
import json
import time
import ctypes
import threading
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageDraw
from pynput import keyboard
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
import mss
import pystray
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration & Environment
# ---------------------------------------------------------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HOTKEY_COMBINATION = os.getenv("HOTKEY", "<alt>+t")
HISTORY_HOTKEY = os.getenv("HISTORY_HOTKEY", "<alt>+h")
DEFAULT_TARGET_LANG = os.getenv("TARGET_LANGUAGE", "English")
DEFAULT_OVERLAY_MODE = os.getenv("OVERLAY_MODE", "compact").lower()  # "compact" | "lens" | "window"
DEFAULT_AUTO_COPY = os.getenv("AUTO_COPY", "false").lower() in ("true", "1", "yes")
DEFAULT_AUTO_TTS = os.getenv("AUTO_TTS", "false").lower() in ("true", "1", "yes")

AVAILABLE_LANGUAGES = [
    "English",
    "Hungarian",
    "German",
    "Japanese",
    "French",
    "Spanish",
    "Italian",
    "Russian",
    "Chinese",
    "Korean",
    "Portuguese"
]

FALLBACK_FLASH_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash"
]

# Windows DPI awareness correction (pixel-perfect selection across multi-monitor displays)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Structured AI Output Schema
# ---------------------------------------------------------------------------
class TranslationResult(BaseModel):
    detected_language: str = Field(
        default="Unknown",
        description="The source language detected from the text in the image (e.g. Japanese, English, Chinese, German)"
    )
    original_text: str = Field(
        default="",
        description="Verbatim transcribed text extracted from the image"
    )
    translated_text: str = Field(
        default="",
        description="Natural, fluent, context-aware translation into the requested target language"
    )


# ---------------------------------------------------------------------------
# TTS (Text-to-Speech) Native Windows Engine
# ---------------------------------------------------------------------------
def speak_text_async(text: str):
    """Asynchronously speak text using Windows SAPI TTS engine without blocking the GUI."""
    if not text or not text.strip():
        return

    clean_text = text.strip()

    def _speak():
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import win32com.client
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            # 3 = SVSFlagsAsync (1) | SVSFPurgeBeforeSpeak (2)
            speaker.Speak(clean_text, 3)
        except Exception:
            pass

    threading.Thread(target=_speak, daemon=True).start()


# ---------------------------------------------------------------------------
# Image Optimization Helper
# ---------------------------------------------------------------------------
def optimize_image_for_vision(image: Image.Image, max_dimension: int = 1600) -> Image.Image:
    """Resize high-res images and convert to RGB to minimize network upload latency."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    width, height = image.size
    if max(width, height) > max_dimension:
        ratio = max_dimension / max(width, height)
        new_size = (int(width * ratio), int(height * ratio))
        image = image.resize(new_size, Image.Resampling.LANCZOS)
    return image


def create_app_icon(size: int = 64) -> Image.Image:
    """Generate a high-contrast tray/window icon with a rounded background and cyan glyph."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, size - 3, size - 3], radius=size // 4, fill="#18181b", outline="#00e5ff", width=3)
    # Draw letter 'T'
    bar_h = max(3, size // 8)
    stem_w = max(4, size // 8)
    draw.rectangle([size // 4, size // 4, size - size // 4, size // 4 + bar_h], fill="#00e5ff")
    draw.rectangle([size // 2 - stem_w // 2, size // 4 + bar_h, size // 2 + stem_w // 2, size - size // 4], fill="#00e5ff")
    return img


# ---------------------------------------------------------------------------
# Main Application Controller
# ---------------------------------------------------------------------------
class ScreenTranslatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
        self.is_busy = False

        # State settings
        self.target_language = tk.StringVar(value=DEFAULT_TARGET_LANG)
        self.overlay_mode = tk.StringVar(value=DEFAULT_OVERLAY_MODE)  # "compact" | "lens" | "window"
        self.auto_copy = tk.BooleanVar(value=DEFAULT_AUTO_COPY)
        self.auto_tts = tk.BooleanVar(value=DEFAULT_AUTO_TTS)

        # Cached models list (populated once at startup)
        self.cached_models: list[str] = list(FALLBACK_FLASH_MODELS)
        self._refresh_models_async()

        # Translation History (in-memory rolling buffer, max 50 items)
        self.history: list[dict] = []
        self.history_window = None

        # Snipping overlay state
        self.snip_win = None
        self.canvas = None
        self.screenshot_img = None
        self.tk_img = None
        self.bounds = None

        # Box coordinates: [x1, y1, x2, y2]
        self.box_coords = None
        self.rect_id = None
        self.mask_top = None
        self.mask_bottom = None
        self.mask_left = None
        self.mask_right = None
        self.handle_ids = {}

        # Interaction drag state: None, "create", ("resize", handle_name), or ("move", start_x, start_y, orig_coords)
        self.drag_mode = None
        self.drag_start = (0, 0)
        self.orig_box_on_drag = None

        self.toolbar_frame = None
        self.current_hud_win = None

        # Tray icon reference
        self.tray_icon = None

    # -----------------------------------------------------------------------
    # Model Cache
    # -----------------------------------------------------------------------
    def _refresh_models_async(self):
        """Fetch available models in the background once without blocking UI or snip clicks."""
        def fetch():
            if not self.client:
                return
            exclude = ["embed", "exp", "experimental", "preview", "omni", "audio", "tts", "thinking", "pro", "search"]
            valid = []
            try:
                for model in self.client.models.list():
                    name = model.name.replace("models/", "").lower()
                    if "flash" in name and not any(bad in name for bad in exclude):
                        versions = re.findall(r"\d+\.\d+|\d+", name)
                        ver = float(versions[0]) if versions else 0.0
                        is_lite = 0.1 if "lite" in name else 0.2
                        valid.append((ver + is_lite, name))
                valid.sort(key=lambda x: x[0], reverse=True)
                sorted_models = [m[1] for m in valid]
                if sorted_models:
                    self.cached_models = sorted_models
            except Exception:
                pass  # Fallback to FALLBACK_FLASH_MODELS
        threading.Thread(target=fetch, daemon=True).start()

    # -----------------------------------------------------------------------
    # Snipping & Capture
    # -----------------------------------------------------------------------
    def trigger_snip(self):
        """Public trigger invoked by global hotkey or tray icon."""
        if self.is_busy:
            return
        self.is_busy = True
        self.root.after(0, self._start_snipping)

    def _capture_all_monitors(self) -> tuple[Image.Image, dict]:
        """Capture screenshot spanning across all connected displays."""
        with mss.MSS() as sct:
            all_screens = sct.monitors[0]
            sct_img = sct.grab(all_screens)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            return img, all_screens

    def _start_snipping(self):
        self.box_coords = None
        self.drag_mode = None
        self.screenshot_img, self.bounds = self._capture_all_monitors()

        self.snip_win = tk.Toplevel(self.root)
        self.snip_win.overrideredirect(True)
        self.snip_win.geometry(f"{self.bounds['width']}x{self.bounds['height']}+{self.bounds['left']}+{self.bounds['top']}")
        self.snip_win.attributes("-topmost", True)

        self.tk_img = ImageTk.PhotoImage(self.screenshot_img)
        self.canvas = tk.Canvas(self.snip_win, cursor="cross", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")

        # Create dimmed screen mask elements
        w, h = self.bounds['width'], self.bounds['height']
        self.mask_top = self.canvas.create_rectangle(0, 0, w, h, fill="#000000", stipple="gray25", width=0)
        self.mask_bottom = self.canvas.create_rectangle(0, 0, 0, 0, fill="#000000", stipple="gray25", width=0)
        self.mask_left = self.canvas.create_rectangle(0, 0, 0, 0, fill="#000000", stipple="gray25", width=0)
        self.mask_right = self.canvas.create_rectangle(0, 0, 0, 0, fill="#000000", stipple="gray25", width=0)

        # Selection rectangle & handles
        self.rect_id = self.canvas.create_rectangle(0, 0, 0, 0, outline="#00e5ff", width=2)
        self.handle_ids = {
            name: self.canvas.create_rectangle(0, 0, 0, 0, fill="#ffffff", outline="#00e5ff", width=1)
            for name in ["nw", "n", "ne", "e", "se", "s", "sw", "w"]
        }

        # Show quick guide badge in top corner
        self._show_initial_hint()

        # Canvas Mouse events
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # Global overlay keyboard shortcuts
        self.snip_win.bind("<Escape>", lambda _: self._close_snip())
        self.snip_win.bind("<Return>", lambda _: self._approve_and_translate())

        # Fine-tune positioning (Arrow keys)
        self.snip_win.bind("<Left>", lambda _: self._move_box(-1, 0))
        self.snip_win.bind("<Right>", lambda _: self._move_box(1, 0))
        self.snip_win.bind("<Up>", lambda _: self._move_box(0, -1))
        self.snip_win.bind("<Down>", lambda _: self._move_box(0, 1))
        self.snip_win.bind("<Shift-Left>", lambda _: self._move_box(-10, 0))
        self.snip_win.bind("<Shift-Right>", lambda _: self._move_box(10, 0))
        self.snip_win.bind("<Shift-Up>", lambda _: self._move_box(0, -10))
        self.snip_win.bind("<Shift-Down>", lambda _: self._move_box(0, 10))

        # Fine-tune resizing (Alt + Arrow keys)
        self.snip_win.bind("<Alt-Left>", lambda _: self._resize_box(-1, 0))
        self.snip_win.bind("<Alt-Right>", lambda _: self._resize_box(1, 0))
        self.snip_win.bind("<Alt-Up>", lambda _: self._resize_box(0, -1))
        self.snip_win.bind("<Alt-Down>", lambda _: self._resize_box(0, 1))
        self.snip_win.bind("<Alt-Shift-Left>", lambda _: self._resize_box(-10, 0))
        self.snip_win.bind("<Alt-Shift-Right>", lambda _: self._resize_box(10, 0))
        self.snip_win.bind("<Alt-Shift-Up>", lambda _: self._resize_box(0, -10))
        self.snip_win.bind("<Alt-Shift-Down>", lambda _: self._resize_box(0, 10))

        self.snip_win.focus_force()

    def _show_initial_hint(self):
        hint_frame = tk.Frame(self.snip_win, bg="#111111", bd=1, relief="solid", padx=10, pady=6)
        hint_frame.place(x=20, y=20)
        tk.Label(
            hint_frame,
            text="Drag to select region | Esc to cancel | Enter to translate",
            fg="#e0e0e0",
            bg="#111111",
            font=("Segoe UI", 9, "bold")
        ).pack()

    def _close_snip(self):
        if self.snip_win:
            self.snip_win.destroy()
            self.snip_win = None
        self.is_busy = False

    # -----------------------------------------------------------------------
    # Interactive Selection & Handles Math
    # -----------------------------------------------------------------------
    def _hit_test(self, x: int, y: int) -> str | None:
        """Identify which handle or region is hovered/clicked."""
        if not self.box_coords:
            return None
        x1, y1, x2, y2 = self.box_coords
        handle_size = 8
        margin = 6

        handles = {
            "nw": (x1, y1),
            "n": ((x1 + x2) // 2, y1),
            "ne": (x2, y1),
            "e": (x2, (y1 + y2) // 2),
            "se": (x2, y2),
            "s": ((x1 + x2) // 2, y2),
            "sw": (x1, y2),
            "w": (x1, (y1 + y2) // 2),
        }

        for name, (hx, hy) in handles.items():
            if abs(x - hx) <= margin and abs(y - hy) <= margin:
                return name

        if x1 < x < x2 and y1 < y < y2:
            return "inside"
        return None

    def _on_mouse_move(self, event):
        hit = self._hit_test(event.x, event.y)
        cursor_map = {
            "nw": "size_nw_se",
            "se": "size_nw_se",
            "ne": "size_ne_sw",
            "sw": "size_ne_sw",
            "n": "size_ns",
            "s": "size_ns",
            "e": "size_we",
            "w": "size_we",
            "inside": "fleur"
        }
        self.canvas.config(cursor=cursor_map.get(hit, "cross"))

    def _on_press(self, event):
        if self.toolbar_frame:
            self.toolbar_frame.destroy()
            self.toolbar_frame = None

        hit = self._hit_test(event.x, event.y)
        if hit in ["nw", "n", "ne", "e", "se", "s", "sw", "w"]:
            self.drag_mode = ("resize", hit)
            self.drag_start = (event.x, event.y)
            self.orig_box_on_drag = list(self.box_coords)
        elif hit == "inside":
            self.drag_mode = ("move", event.x, event.y)
            self.drag_start = (event.x, event.y)
            self.orig_box_on_drag = list(self.box_coords)
        else:
            self.drag_mode = "create"
            self.drag_start = (event.x, event.y)
            self.box_coords = [event.x, event.y, event.x, event.y]
            self._update_selection_visual()

    def _on_drag(self, event):
        if not self.drag_mode:
            return

        if self.drag_mode == "create":
            sx, sy = self.drag_start
            self.box_coords = [min(sx, event.x), min(sy, event.y), max(sx, event.x), max(sy, event.y)]
            self._update_selection_visual()

        elif isinstance(self.drag_mode, tuple) and self.drag_mode[0] == "move":
            dx = event.x - self.drag_start[0]
            dy = event.y - self.drag_start[1]
            ox1, oy1, ox2, oy2 = self.orig_box_on_drag
            w = ox2 - ox1
            h = oy2 - oy1
            max_w, max_h = self.bounds['width'], self.bounds['height']
            nx1 = max(0, min(ox1 + dx, max_w - w))
            ny1 = max(0, min(oy1 + dy, max_h - h))
            self.box_coords = [nx1, ny1, nx1 + w, ny1 + h]
            self._update_selection_visual()

        elif isinstance(self.drag_mode, tuple) and self.drag_mode[0] == "resize":
            handle = self.drag_mode[1]
            x1, y1, x2, y2 = self.orig_box_on_drag
            dx = event.x - self.drag_start[0]
            dy = event.y - self.drag_start[1]

            if "w" in handle:
                x1 = min(x2 - 15, x1 + dx)
            if "e" in handle:
                x2 = max(x1 + 15, x2 + dx)
            if "n" in handle:
                y1 = min(y2 - 15, y1 + dy)
            if "s" in handle:
                y2 = max(y1 + 15, y2 + dy)

            self.box_coords = [x1, y1, x2, y2]
            self._update_selection_visual()

    def _on_release(self, event):
        if not self.box_coords:
            self.drag_mode = None
            return

        x1, y1, x2, y2 = self.box_coords
        if (x2 - x1) > 15 and (y2 - y1) > 15:
            self._update_selection_visual()
            self._show_toolbar(x2, y2)
        else:
            self._reset_box()

        self.drag_mode = None

    def _reset_box(self):
        self.box_coords = None
        self.canvas.coords(self.rect_id, 0, 0, 0, 0)
        for hid in self.handle_ids.values():
            self.canvas.coords(hid, 0, 0, 0, 0)
        # Restore full mask
        w, h = self.bounds['width'], self.bounds['height']
        self.canvas.coords(self.mask_top, 0, 0, w, h)
        self.canvas.coords(self.mask_bottom, 0, 0, 0, 0)
        self.canvas.coords(self.mask_left, 0, 0, 0, 0)
        self.canvas.coords(self.mask_right, 0, 0, 0, 0)

    def _move_box(self, dx: int, dy: int):
        if not self.box_coords:
            return
        w, h = self.bounds['width'], self.bounds['height']
        bw = self.box_coords[2] - self.box_coords[0]
        bh = self.box_coords[3] - self.box_coords[1]
        nx1 = max(0, min(self.box_coords[0] + dx, w - bw))
        ny1 = max(0, min(self.box_coords[1] + dy, h - bh))
        self.box_coords = [nx1, ny1, nx1 + bw, ny1 + bh]
        self._update_selection_visual()
        self._show_toolbar(self.box_coords[2], self.box_coords[3])

    def _resize_box(self, dw: int, dh: int):
        if not self.box_coords:
            return
        self.box_coords[2] = max(self.box_coords[0] + 15, self.box_coords[2] + dw)
        self.box_coords[3] = max(self.box_coords[1] + 15, self.box_coords[3] + dh)
        self._update_selection_visual()
        self._show_toolbar(self.box_coords[2], self.box_coords[3])

    def _update_selection_visual(self):
        if not self.box_coords:
            return
        x1, y1, x2, y2 = self.box_coords
        w, h = self.bounds['width'], self.bounds['height']

        # Update 4-segment darkened mask outside the selection
        self.canvas.coords(self.mask_top, 0, 0, w, y1)
        self.canvas.coords(self.mask_bottom, 0, y2, w, h)
        self.canvas.coords(self.mask_left, 0, y1, x1, y2)
        self.canvas.coords(self.mask_right, x2, y1, w, y2)

        # Update selection border
        self.canvas.coords(self.rect_id, x1, y1, x2, y2)

        # Update 8 handles
        hs = 4
        handles_pos = {
            "nw": (x1, y1),
            "n": ((x1 + x2) // 2, y1),
            "ne": (x2, y1),
            "e": (x2, (y1 + y2) // 2),
            "se": (x2, y2),
            "s": ((x1 + x2) // 2, y2),
            "sw": (x1, y2),
            "w": (x1, (y1 + y2) // 2),
        }
        for name, (hx, hy) in handles_pos.items():
            self.canvas.coords(self.handle_ids[name], hx - hs, hy - hs, hx + hs, hy + hs)

    def _show_toolbar(self, x: int, y: int):
        """Floating action bar with language selection, mode toggle, and control guide."""
        if self.toolbar_frame:
            self.toolbar_frame.destroy()

        self.toolbar_frame = tk.Frame(self.snip_win, bg="#18181b", bd=1, relief="solid", padx=10, pady=8)

        # Row 1: Actions & Configuration
        action_row = tk.Frame(self.toolbar_frame, bg="#18181b")
        action_row.pack(fill="x")

        tk.Label(action_row, text="Target:", fg="#a1a1aa", bg="#18181b", font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))
        combo = ttk.Combobox(action_row, textvariable=self.target_language, values=AVAILABLE_LANGUAGES, width=11, state="readonly")
        combo.pack(side="left", padx=4)

        # Mode button (cycles: compact -> lens -> window -> compact)
        mode_order = ["compact", "lens", "window"]

        def toggle_mode():
            current = self.overlay_mode.get()
            idx = mode_order.index(current) if current in mode_order else 0
            new_mode = mode_order[(idx + 1) % len(mode_order)]
            self.overlay_mode.set(new_mode)
            btn_mode.config(text=f"Mode: {new_mode.capitalize()}")

        btn_mode = tk.Button(
            action_row,
            text=f"Mode: {self.overlay_mode.get().capitalize()}",
            command=toggle_mode,
            bg="#27272a",
            fg="#e4e4e7",
            font=("Segoe UI", 8),
            relief="flat",
            padx=6
        )
        btn_mode.pack(side="left", padx=4)

        btn_approve = tk.Button(
            action_row,
            text="✔ Translate (Enter)",
            command=self._approve_and_translate,
            bg="#16a34a",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            cursor="hand2"
        )
        btn_approve.pack(side="left", padx=4)

        btn_cancel = tk.Button(
            action_row,
            text="✖ Cancel (Esc)",
            command=self._close_snip,
            bg="#3f3f46",
            fg="white",
            font=("Segoe UI", 9),
            relief="flat",
            padx=8,
            cursor="hand2"
        )
        btn_cancel.pack(side="left", padx=2)

        # Row 2: Cheatsheet / Guide
        help_row = tk.Frame(self.toolbar_frame, bg="#27272a", bd=0, padx=6, pady=4)
        help_row.pack(fill="x", pady=(6, 0))
        tts_status = "ON" if self.auto_tts.get() else "OFF"
        help_text = f"💡 Move/Resize: Mouse or Arrows | Mode: {self.overlay_mode.get().capitalize()} | TTS: {tts_status}"
        tk.Label(help_row, text=help_text, fg="#a3e635", bg="#27272a", font=("Consolas", 8)).pack(anchor="w")

        # Position clamping
        tb_width = 470
        pos_x = max(10, min(x, self.bounds['width'] - tb_width))
        pos_y = y + 10 if (y + 90) < self.bounds['height'] else max(10, y - 85)
        self.toolbar_frame.place(x=pos_x, y=pos_y)

    # -----------------------------------------------------------------------
    # Translation Processing (Vision AI)
    # -----------------------------------------------------------------------
    def _approve_and_translate(self):
        if not self.box_coords:
            return

        x1, y1, x2, y2 = self.box_coords
        cropped = self.screenshot_img.crop((x1, y1, x2, y2))
        target_lang = self.target_language.get()
        mode = self.overlay_mode.get()

        # Save screen position of crop box for placement
        box_screen_coords = (
            self.bounds['left'] + x1,
            self.bounds['top'] + y1,
            self.bounds['left'] + x2,
            self.bounds['top'] + y2
        )

        self._close_snip()
        self._process_translation(cropped, target_lang, mode, box_screen_coords)

    def _process_translation(self, cropped_img: Image.Image, target_lang: str, mode: str, box_screen_coords: tuple):
        # Loading indicator window
        loading = tk.Toplevel(self.root)
        loading.title("Processing...")
        loading.geometry("340x85")
        loading.attributes("-topmost", True)
        loading.config(bg="#18181b")

        status_lbl = tk.Label(loading, text=f"⚡ Initializing fast Flash model...", fg="#a1a1aa", bg="#18181b", font=("Segoe UI", 9))
        status_lbl.pack(pady=(12, 2))
        tk.Label(loading, text=f"Translating to {target_lang}...", fg="#ffffff", bg="#18181b", font=("Segoe UI", 10, "bold")).pack()

        # Keyboard cancel on loading window
        loading.bind("<Escape>", lambda _: loading.destroy())

        def worker():
            optimized_img = optimize_image_for_vision(cropped_img, max_dimension=1600)

            prompt = (
                f"You are an expert game and visual screen translator.\n"
                f"1. Transcribe the text verbatim in its source language.\n"
                f"2. Accurately detect the source language.\n"
                f"3. Translate into natural, fluent {target_lang}."
            )

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TranslationResult,
                temperature=0.2,
            )

            orig = ""
            trans = ""
            detected_lang = "Unknown"
            active_model = self.cached_models[0] if self.cached_models else "gemini-2.5-flash"
            err_msg = ""
            success = False

            # Try cached prioritized models
            models_to_try = self.cached_models or FALLBACK_FLASH_MODELS
            for model in models_to_try:
                active_model = model
                loading.after(0, lambda m=model: status_lbl.config(text=f"🤖 Model: {m}"))
                try:
                    res = self.client.models.generate_content(
                        model=model,
                        contents=[optimized_img, prompt],
                        config=config
                    )
                    if res and res.text:
                        raw_text = res.text.strip()
                        try:
                            parsed = TranslationResult.model_validate_json(raw_text)
                            orig = parsed.original_text.strip()
                            trans = parsed.translated_text.strip()
                            detected_lang = parsed.detected_language.strip()
                        except Exception:
                            # Fallback standard json parsing
                            raw_data = json.loads(raw_text)
                            orig = raw_data.get("original_text", "")
                            trans = raw_data.get("translated_text", raw_text)
                            detected_lang = raw_data.get("detected_language", "Unknown")

                        success = True
                        break
                except Exception as e:
                    err_msg = str(e)

            if not success:
                orig = "Error"
                trans = f"API Error: {err_msg}"
                detected_lang = "N/A"

            # Auto-copy to clipboard if enabled
            if success and self.auto_copy.get() and trans:
                self.root.clipboard_clear()
                self.root.clipboard_append(trans)

            # Auto-TTS speech if enabled
            if success and self.auto_tts.get() and trans:
                speak_text_async(trans)

            # Record in history
            history_item = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "source_lang": detected_lang,
                "target_lang": target_lang,
                "original": orig,
                "translated": trans,
                "model": active_model
            }
            self.history.insert(0, history_item)
            if len(self.history) > 50:
                self.history.pop()

            self.root.after(0, lambda: self._dispatch_result(loading, orig, trans, detected_lang, active_model, target_lang, mode, box_screen_coords))

        threading.Thread(target=worker, daemon=True).start()

    def _dispatch_result(self, loading_win: tk.Toplevel, orig: str, trans: str, detected_lang: str, used_model: str, target_lang: str, mode: str, box_screen_coords: tuple):
        try:
            loading_win.destroy()
        except Exception:
            pass

        if mode == "lens":
            self._show_lens_overlay(orig, trans, detected_lang, used_model, target_lang, box_screen_coords)
        elif mode == "compact":
            self._show_compact_hud(orig, trans, detected_lang, used_model, target_lang, box_screen_coords)
        else:
            self._show_detailed_window(orig, trans, detected_lang, used_model, target_lang)

    # -----------------------------------------------------------------------
    # Result UI: 1) In-Place Lens Mode (Covers original text directly)
    # -----------------------------------------------------------------------
    def _show_lens_overlay(self, orig: str, trans: str, detected_lang: str, used_model: str, target_lang: str, box_screen_coords: tuple):
        """Displays translated text directly on top of the original text area (Google Lens style)."""
        if self.current_hud_win:
            try:
                self.current_hud_win.destroy()
            except Exception:
                pass

        bx1, by1, bx2, by2 = box_screen_coords
        w = max(200, bx2 - bx1)
        h = max(60, by2 - by1)

        lens = tk.Toplevel(self.root)
        self.current_hud_win = lens
        lens.overrideredirect(True)
        lens.attributes("-topmost", True)
        # Translucent dark background matching game ambiance
        lens.attributes("-alpha", 0.94)
        lens.config(bg="#121214")
        lens.geometry(f"{w}x{h}+{bx1}+{by1}")

        container = tk.Frame(lens, bg="#121214", bd=1, relief="solid", highlightthickness=1, highlightbackground="#00e5ff", padx=6, pady=4)
        container.pack(fill="both", expand=True)

        # Micro Top Bar
        top_bar = tk.Frame(container, bg="#121214")
        top_bar.pack(fill="x", pady=(0, 2))

        lbl_badge = tk.Label(top_bar, text=f"{detected_lang} ➔ {target_lang}", fg="#00e5ff", bg="#121214", font=("Segoe UI", 7, "bold"))
        lbl_badge.pack(side="left")

        btn_close = tk.Label(top_bar, text="✖", fg="#71717a", bg="#121214", font=("Segoe UI", 8, "bold"), cursor="hand2")
        btn_close.pack(side="right", padx=(4, 0))
        btn_close.bind("<Button-1>", lambda _: self._close_hud(lens))

        btn_expand = tk.Label(top_bar, text="🔍", fg="#a1a1aa", bg="#121214", font=("Segoe UI", 8), cursor="hand2")
        btn_expand.pack(side="right", padx=4)
        btn_expand.bind("<Button-1>", lambda _: [self._close_hud(lens), self._show_detailed_window(orig, trans, detected_lang, used_model, target_lang)])

        btn_speak = tk.Label(top_bar, text="🔊", fg="#a1a1aa", bg="#121214", font=("Segoe UI", 8), cursor="hand2")
        btn_speak.pack(side="right", padx=4)
        btn_speak.bind("<Button-1>", lambda _: speak_text_async(trans))

        btn_copy = tk.Label(top_bar, text="📋", fg="#a1a1aa", bg="#121214", font=("Segoe UI", 8), cursor="hand2")
        btn_copy.pack(side="right", padx=4)

        def copy_lens():
            lens.clipboard_clear()
            lens.clipboard_append(trans)
            btn_copy.config(text="✔")
            lens.after(1200, lambda: btn_copy.config(text="📋"))
        btn_copy.bind("<Button-1>", lambda _: copy_lens())

        # Main In-Place Translated Text
        # Dynamic font size adapting to height
        font_size = 11 if h >= 80 else (10 if h >= 50 else 9)
        text_lbl = tk.Label(
            container,
            text=trans,
            fg="#ffffff",
            bg="#121214",
            font=("Segoe UI", font_size, "bold"),
            wraplength=w - 16,
            justify="center"
        )
        text_lbl.pack(fill="both", expand=True, padx=4, pady=2)

        lens.bind("<Escape>", lambda _: self._close_hud(lens))
        container.bind("<Button-1>", lambda _: self._close_hud(lens))
        text_lbl.bind("<Button-1>", lambda _: self._close_hud(lens))

        # Auto-dismiss after 15 seconds
        lens.after(15000, lambda: self._close_hud(lens))

    # -----------------------------------------------------------------------
    # Result UI: 2) Compact Floating Subtitle HUD
    # -----------------------------------------------------------------------
    def _show_compact_hud(self, orig: str, trans: str, detected_lang: str, used_model: str, target_lang: str, box_screen_coords: tuple):
        if self.current_hud_win:
            try:
                self.current_hud_win.destroy()
            except Exception:
                pass

        bx1, by1, bx2, by2 = box_screen_coords
        box_w = max(380, bx2 - bx1)
        hud_w = min(620, max(380, box_w))

        hud = tk.Toplevel(self.root)
        self.current_hud_win = hud
        hud.overrideredirect(True)
        hud.attributes("-topmost", True)
        hud.config(bg="#18181b")

        container = tk.Frame(hud, bg="#18181b", bd=1, relief="solid", highlightthickness=1, highlightbackground="#00e5ff", padx=12, pady=10)
        container.pack(fill="both", expand=True)

        # Header Row
        header_row = tk.Frame(container, bg="#18181b")
        header_row.pack(fill="x", pady=(0, 6))

        lang_badge = f"🌐 {detected_lang} ➔ {target_lang}"
        tk.Label(header_row, text=lang_badge, fg="#00e5ff", bg="#18181b", font=("Segoe UI", 9, "bold")).pack(side="left")

        btn_close = tk.Label(header_row, text="✖", fg="#71717a", bg="#18181b", font=("Segoe UI", 10, "bold"), cursor="hand2")
        btn_close.pack(side="right", padx=(6, 0))
        btn_close.bind("<Button-1>", lambda _: self._close_hud(hud))

        btn_expand = tk.Label(header_row, text="🔍 Full", fg="#a1a1aa", bg="#18181b", font=("Segoe UI", 8), cursor="hand2")
        btn_expand.pack(side="right", padx=6)
        btn_expand.bind("<Button-1>", lambda _: [self._close_hud(hud), self._show_detailed_window(orig, trans, detected_lang, used_model, target_lang)])

        btn_hist = tk.Label(header_row, text="📜 History", fg="#a1a1aa", bg="#18181b", font=("Segoe UI", 8), cursor="hand2")
        btn_hist.pack(side="right", padx=6)
        btn_hist.bind("<Button-1>", lambda _: self.show_history_window())

        # Translation Text
        text_lbl = tk.Label(
            container,
            text=trans,
            fg="#ffffff",
            bg="#18181b",
            font=("Segoe UI", 11, "bold"),
            wraplength=hud_w - 30,
            justify="left"
        )
        text_lbl.pack(fill="x", pady=(2, 8), anchor="w")

        # Footer Row (Copy, Speak action & status)
        footer_row = tk.Frame(container, bg="#18181b")
        footer_row.pack(fill="x")

        status_text = "Auto-copied ✔" if self.auto_copy.get() else f"⚡ {used_model}"
        lbl_status = tk.Label(footer_row, text=status_text, fg="#71717a", bg="#18181b", font=("Consolas", 8))
        lbl_status.pack(side="left")

        def copy_hud():
            hud.clipboard_clear()
            hud.clipboard_append(trans)
            btn_cp.config(text="Copied! ✔")
            hud.after(1500, lambda: btn_cp.config(text="📋 Copy"))

        btn_cp = tk.Button(footer_row, text="📋 Copy", command=copy_hud, bg="#27272a", fg="#e4e4e7", font=("Segoe UI", 8), relief="flat", padx=8, pady=2, cursor="hand2")
        btn_cp.pack(side="right")

        btn_speak = tk.Button(footer_row, text="🔊 Listen", command=lambda: speak_text_async(trans), bg="#27272a", fg="#e4e4e7", font=("Segoe UI", 8), relief="flat", padx=8, pady=2, cursor="hand2")
        btn_speak.pack(side="right", padx=(0, 6))

        # Positioning: place directly below the cropped box, or above if close to screen bottom
        hud.update_idletasks()
        hud_h = hud.winfo_reqheight()
        pos_x = max(10, min(bx1, self.bounds['left'] + self.bounds['width'] - hud_w - 10))
        pos_y = by2 + 8 if (by2 + hud_h + 10) < (self.bounds['top'] + self.bounds['height']) else max(10, by1 - hud_h - 8)

        hud.geometry(f"{hud_w}x{hud_h}+{pos_x}+{pos_y}")

        hud.bind("<Escape>", lambda _: self._close_hud(hud))
        # Auto-dismiss after 15 seconds
        hud.after(15000, lambda: self._close_hud(hud))

    def _close_hud(self, hud_win):
        try:
            hud_win.destroy()
        except Exception:
            pass
        self.is_busy = False

    # -----------------------------------------------------------------------
    # Result UI: 3) Detailed Full Window
    # -----------------------------------------------------------------------
    def _show_detailed_window(self, orig: str, trans: str, detected_lang: str, used_model: str, target_lang: str):
        win = tk.Toplevel(self.root)
        win.title("Gemini Screen Translator - Full Result")
        win.attributes("-topmost", True)
        win.geometry("780x560")
        win.minsize(540, 360)
        win.config(bg="#18181b")

        def close():
            win.destroy()
            self.is_busy = False

        win.protocol("WM_DELETE_WINDOW", close)

        main_container = tk.Frame(win, bg="#18181b", padx=16, pady=14)
        main_container.pack(fill="both", expand=True)

        # Bottom Action Bar
        bottom_row = tk.Frame(main_container, bg="#18181b")
        bottom_row.pack(side="bottom", fill="x", pady=(12, 0))

        tk.Label(bottom_row, text=f"⚡ Model: {used_model} | {detected_lang} ➔ {target_lang}", fg="#71717a", bg="#18181b", font=("Consolas", 8)).pack(side="left")

        def copy_translation():
            win.clipboard_clear()
            win.clipboard_append(trans)
            btn_copy.config(text="Copied! ✔")
            win.after(1500, lambda: btn_copy.config(text="Copy Translation"))

        btn_close = tk.Button(bottom_row, text="Close (Esc)", command=close, bg="#27272a", fg="white", relief="flat", padx=12, pady=5, font=("Segoe UI", 9), cursor="hand2")
        btn_close.pack(side="right")

        btn_copy = tk.Button(bottom_row, text="Copy Translation", command=copy_translation, bg="#3f3f46", fg="#ffffff", relief="flat", padx=10, pady=5, font=("Segoe UI", 9), cursor="hand2")
        btn_copy.pack(side="right", padx=(0, 8))

        btn_speak = tk.Button(bottom_row, text="🔊 Listen", command=lambda: speak_text_async(trans), bg="#27272a", fg="#38bdf8", relief="flat", padx=10, pady=5, font=("Segoe UI", 9), cursor="hand2")
        btn_speak.pack(side="right", padx=(0, 8))

        btn_history = tk.Button(bottom_row, text="📜 History", command=self.show_history_window, bg="#27272a", fg="#a1a1aa", relief="flat", padx=10, pady=5, font=("Segoe UI", 9), cursor="hand2")
        btn_history.pack(side="right", padx=(0, 8))

        # Text View Area
        text_container = tk.Frame(main_container, bg="#18181b")
        text_container.pack(side="top", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_container, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        text_area = tk.Text(
            text_container,
            wrap="word",
            bg="#27272a",
            fg="#ffffff",
            bd=0,
            padx=14,
            pady=12,
            height=10,
            highlightthickness=1,
            highlightbackground="#3f3f46",
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10)
        )
        text_area.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_area.yview)

        text_area.tag_configure("header_orig", font=("Segoe UI", 9, "bold"), foreground="#a1a1aa", spacing3=6)
        text_area.tag_configure("body_orig", font=("Segoe UI", 10), foreground="#d4d4d8", spacing3=14)
        text_area.tag_configure("divider", font=("Segoe UI", 8), foreground="#52525b", spacing3=12)
        text_area.tag_configure("header_trans", font=("Segoe UI", 10, "bold"), foreground="#00e5ff", spacing3=6)
        text_area.tag_configure("body_trans", font=("Segoe UI", 11, "bold"), foreground="#ffffff", spacing3=10)

        text_area.insert("end", f"ORIGINAL TEXT ({detected_lang.upper()}):\n", "header_orig")
        text_area.insert("end", f"{orig}\n\n", "body_orig")
        text_area.insert("end", "―" * 65 + "\n\n", "divider")
        text_area.insert("end", f"TRANSLATION ({target_lang.upper()}):\n", "header_trans")
        text_area.insert("end", f"{trans}\n", "body_trans")

        text_area.config(state="disabled")
        text_area.see("1.0")

        win.bind("<Escape>", lambda _: close())
        win.focus_force()

    # -----------------------------------------------------------------------
    # Translation History Window
    # -----------------------------------------------------------------------
    def show_history_window(self):
        """Displays rolling history of past translations with search, TTS, and quick copy."""
        if self.history_window and tk.Toplevel.winfo_exists(self.history_window):
            self.history_window.lift()
            self.history_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self.history_window = win
        win.title("Translation History (Előzmények)")
        win.attributes("-topmost", True)
        win.geometry("680x520")
        win.minsize(480, 320)
        win.config(bg="#18181b")

        container = tk.Frame(win, bg="#18181b", padx=16, pady=14)
        container.pack(fill="both", expand=True)

        # Header with Search & Clear
        top_bar = tk.Frame(container, bg="#18181b")
        top_bar.pack(fill="x", pady=(0, 10))

        tk.Label(top_bar, text="📜 History", fg="#00e5ff", bg="#18181b", font=("Segoe UI", 12, "bold")).pack(side="left")

        def clear_history():
            self.history.clear()
            render_items("")

        btn_clear = tk.Button(top_bar, text="Clear All", command=clear_history, bg="#27272a", fg="#ef4444", font=("Segoe UI", 8), relief="flat", padx=8, cursor="hand2")
        btn_clear.pack(side="right", padx=(8, 0))

        search_var = tk.StringVar()
        entry_search = tk.Entry(top_bar, textvariable=search_var, bg="#27272a", fg="white", insertbackground="white", bd=1, relief="solid", font=("Segoe UI", 9), width=24)
        entry_search.pack(side="right")
        tk.Label(top_bar, text="🔍 Search:", fg="#a1a1aa", bg="#18181b", font=("Segoe UI", 9)).pack(side="right", padx=(0, 4))

        # Scrollable items area
        list_frame = tk.Frame(container, bg="#18181b")
        list_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_frame, bg="#18181b", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#18181b")

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def render_items(filter_query: str):
            for child in scrollable_frame.winfo_children():
                child.destroy()

            query = filter_query.lower().strip()
            displayed = [
                item for item in self.history
                if not query or query in item["original"].lower() or query in item["translated"].lower() or query in item["source_lang"].lower()
            ]

            if not displayed:
                empty_lbl = tk.Label(scrollable_frame, text="No translation records found.", fg="#71717a", bg="#18181b", font=("Segoe UI", 10), pady=40)
                empty_lbl.pack(fill="x")
                return

            for item in displayed:
                card = tk.Frame(scrollable_frame, bg="#27272a", bd=1, relief="solid", padx=12, pady=10)
                card.pack(fill="x", pady=5)

                card_top = tk.Frame(card, bg="#27272a")
                card_top.pack(fill="x")

                badge = f"🕒 {item['time']} | 🌐 {item['source_lang']} ➔ {item['target_lang']}"
                tk.Label(card_top, text=badge, fg="#00e5ff", bg="#27272a", font=("Segoe UI", 8, "bold")).pack(side="left")

                def copy_item(t=item["translated"]):
                    win.clipboard_clear()
                    win.clipboard_append(t)

                btn_cp = tk.Button(card_top, text="📋 Copy", command=copy_item, bg="#3f3f46", fg="white", font=("Segoe UI", 7), relief="flat", padx=6, cursor="hand2")
                btn_cp.pack(side="right")

                btn_spk = tk.Button(card_top, text="🔊 Listen", command=lambda t=item["translated"]: speak_text_async(t), bg="#3f3f46", fg="#38bdf8", font=("Segoe UI", 7), relief="flat", padx=6, cursor="hand2")
                btn_spk.pack(side="right", padx=(0, 6))

                tk.Label(card, text=item["original"], fg="#a1a1aa", bg="#27272a", font=("Segoe UI", 9), wraplength=580, justify="left").pack(fill="x", pady=(4, 2), anchor="w")
                tk.Label(card, text=item["translated"], fg="#ffffff", bg="#27272a", font=("Segoe UI", 10, "bold"), wraplength=580, justify="left").pack(fill="x", anchor="w")

        search_var.trace_add("write", lambda *_: render_items(search_var.get()))
        render_items("")

        win.bind("<Escape>", lambda _: win.destroy())

    # -----------------------------------------------------------------------
    # System Tray Integration (pystray)
    # -----------------------------------------------------------------------
    def setup_tray_icon(self):
        """Initializes and runs the System Tray icon in a dedicated daemon thread."""
        icon_img = create_app_icon(64)

        def make_lang_setter(lang_name: str):
            return lambda: self.target_language.set(lang_name)

        lang_menu_items = [
            pystray.MenuItem(lang, make_lang_setter(lang), checked=lambda item, l=lang: self.target_language.get() == l, radio=True)
            for lang in AVAILABLE_LANGUAGES
        ]

        def set_overlay_mode(m: str):
            return lambda: self.overlay_mode.set(m)

        mode_menu_items = [
            pystray.MenuItem("Compact Subtitle HUD", set_overlay_mode("compact"), checked=lambda item: self.overlay_mode.get() == "compact", radio=True),
            pystray.MenuItem("In-Place Lens Overlay", set_overlay_mode("lens"), checked=lambda item: self.overlay_mode.get() == "lens", radio=True),
            pystray.MenuItem("Full Detailed Window", set_overlay_mode("window"), checked=lambda item: self.overlay_mode.get() == "window", radio=True)
        ]

        def toggle_auto_copy():
            self.auto_copy.set(not self.auto_copy.get())

        def toggle_auto_tts():
            self.auto_tts.set(not self.auto_tts.get())

        def open_config_file():
            env_path = os.path.abspath(".env")
            if os.path.exists(env_path):
                subprocess.Popen(["notepad.exe", env_path])
            else:
                self.root.after(0, lambda: messagebox.showinfo("Settings", f"Could not find .env file at:\n{env_path}"))

        tray_menu = pystray.Menu(
            pystray.MenuItem("Gemini Screen Translator (Running)", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"⚡ Translate Screen ({HOTKEY_COMBINATION})", lambda: self.root.after(0, self.trigger_snip)),
            pystray.MenuItem(f"📜 History ({HISTORY_HOTKEY})", lambda: self.root.after(0, self.show_history_window)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🌐 Target Language", pystray.Menu(*lang_menu_items)),
            pystray.MenuItem("🎛 Display Mode", pystray.Menu(*mode_menu_items)),
            pystray.MenuItem("🔊 Auto-Speak Translation (TTS)", toggle_auto_tts, checked=lambda item: self.auto_tts.get()),
            pystray.MenuItem("📋 Auto-Copy to Clipboard", toggle_auto_copy, checked=lambda item: self.auto_copy.get()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙ Open Settings (.env)", open_config_file),
            pystray.MenuItem("❌ Exit", lambda: self.root.after(0, self.quit_application))
        )

        self.tray_icon = pystray.Icon("GeminiTranslator", icon_img, "Gemini Screen Translator", tray_menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def quit_application(self):
        """Clean shutdown handler."""
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not GEMINI_API_KEY:
        root_temp = tk.Tk()
        root_temp.withdraw()
        messagebox.showerror(
            "Missing API Key",
            "GEMINI_API_KEY was not found in environment variables!\n\n"
            "Please create a .env file next to main.py containing:\n"
            "GEMINI_API_KEY=your_key_here\n\n"
            "You can copy from .env.example."
        )
        exit(1)

    main_root = tk.Tk()
    main_root.withdraw()

    app = ScreenTranslatorApp(main_root)
    app.setup_tray_icon()

    print("=" * 65)
    print("Gemini Screen Translator (v1.2 - In-Place Lens, TTS & Vision) is running.")
    print(f"Hotkey: [{HOTKEY_COMBINATION}] (Snip & Translate)")
    print(f"History: [{HISTORY_HOTKEY}] (Open Translation History)")
    print(f"Default Language: [{DEFAULT_TARGET_LANG}]")
    print(f"Overlay Mode: [{DEFAULT_OVERLAY_MODE.capitalize()}] (compact / lens / window)")
    print(f"Auto-Copy: [{'Enabled' if DEFAULT_AUTO_COPY else 'Disabled'}]")
    print(f"Auto-TTS: [{'Enabled' if DEFAULT_AUTO_TTS else 'Disabled'}]")
    print("System Tray: Active in Windows notification area.")
    print("=" * 65)

    # Register global hotkeys
    hotkeys = {
        HOTKEY_COMBINATION: app.trigger_snip,
        HISTORY_HOTKEY: lambda: main_root.after(0, app.show_history_window)
    }
    hotkey_listener = keyboard.GlobalHotKeys(hotkeys)
    hotkey_listener.start()

    try:
        main_root.mainloop()
    finally:
        hotkey_listener.stop()
        if app.tray_icon:
            app.tray_icon.stop()