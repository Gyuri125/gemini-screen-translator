import os
import re
import ctypes
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from pynput import keyboard
from google import genai
import mss
from dotenv import load_dotenv

# Load configuration from .env
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HOTKEY_COMBINATION = os.getenv("HOTKEY", "<alt>+t")
DEFAULT_TARGET_LANG = os.getenv("TARGET_LANGUAGE", "English")

AVAILABLE_LANGUAGES = [
    "English",
    "Hungarian",
    "German",
    "Japanese",
    "French",
    "Spanish",
    "Italian",
    "Russian",
    "Chinese"
]

# Windows DPI awareness correction (pixel-perfect selection on 125%/150% scaling)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def get_sorted_flash_models(client: genai.Client) -> list[str]:
    """Retrieve and prioritize the newest available Gemini Flash models."""
    exclude = ["embed", "exp", "experimental", "preview", "omni", "audio", "tts", "thinking", "pro", "search"]
    valid = []
    try:
        for model in client.models.list():
            name = model.name.replace("models/", "").lower()
            if "flash" in name and not any(bad in name for bad in exclude):
                versions = re.findall(r"\d+\.\d+|\d+", name)
                ver = float(versions[0]) if versions else 0.0
                is_lite = 0.1 if "lite" in name else 0.2
                valid.append((ver + is_lite, name))
        valid.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in valid] or ["gemini-2.5-flash", "gemini-2.0-flash"]
    except Exception:
        return ["gemini-2.5-flash", "gemini-2.0-flash"]


class ScreenTranslatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.is_busy = False

        self.snip_win = None
        self.canvas = None
        self.screenshot_img = None
        self.tk_img = None

        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.box_coords = None  # [x1, y1, x2, y2]

        self.toolbar_frame = None
        self.lang_var = tk.StringVar(value=DEFAULT_TARGET_LANG)

    def trigger_snip(self):
        if self.is_busy:
            return
        self.is_busy = True
        self.root.after(0, self._start_snipping)

    def _capture_all_monitors(self) -> tuple[Image.Image, dict]:
        """Capture screenshot spanning across all connected displays."""
        with mss.MSS() as sct:
            all_screens = sct.monitors[0]
            sct_img = sct.grab(all_screens)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX"), all_screens

    def _start_snipping(self):
        self.box_coords = None
        self.screenshot_img, bounds = self._capture_all_monitors()

        self.snip_win = tk.Toplevel(self.root)
        self.snip_win.overrideredirect(True)
        self.snip_win.geometry(f"{bounds['width']}x{bounds['height']}+{bounds['left']}+{bounds['top']}")
        self.snip_win.attributes("-topmost", True)

        self.tk_img = ImageTk.PhotoImage(self.screenshot_img)
        self.canvas = tk.Canvas(self.snip_win, cursor="cross", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor="nw")

        # Top corner quick hint
        self._show_initial_hint()

        # Mouse bindings
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # Global overlay hotkeys
        self.snip_win.bind("<Escape>", lambda _: self._close_snip())
        self.snip_win.bind("<Return>", lambda _: self._approve_and_translate())

        # Move bindings (Arrow keys)
        self.snip_win.bind("<Left>", lambda _: self._move_box(-1, 0))
        self.snip_win.bind("<Right>", lambda _: self._move_box(1, 0))
        self.snip_win.bind("<Up>", lambda _: self._move_box(0, -1))
        self.snip_win.bind("<Down>", lambda _: self._move_box(0, 1))
        self.snip_win.bind("<Shift-Left>", lambda _: self._move_box(-10, 0))
        self.snip_win.bind("<Shift-Right>", lambda _: self._move_box(10, 0))
        self.snip_win.bind("<Shift-Up>", lambda _: self._move_box(0, -10))
        self.snip_win.bind("<Shift-Down>", lambda _: self._move_box(0, 10))

        # Resize bindings (Alt + Arrow keys)
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
        tk.Label(hint_frame, text="Drag to select region | Esc to cancel", fg="#e0e0e0", bg="#111111",
                 font=("Segoe UI", 9, "bold")).pack()

    def _close_snip(self):
        if self.snip_win:
            self.snip_win.destroy()
            self.snip_win = None
        self.is_busy = False

    def _on_press(self, event):
        if self.toolbar_frame:
            self.toolbar_frame.destroy()
            self.toolbar_frame = None

        self.start_x, self.start_y = event.x, event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        # Bold red selection outline (width=3)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y,
                                                    outline="#ff2222", width=3)

    def _on_drag(self, event):
        if self.start_x is not None and self.start_y is not None:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event):
        if self.start_x is None:
            return

        x1, x2 = min(self.start_x, event.x), max(self.start_x, event.x)
        y1, y2 = min(self.start_y, event.y), max(self.start_y, event.y)

        if (x2 - x1) > 10 and (y2 - y1) > 10:
            self.box_coords = [x1, y1, x2, y2]
            self._update_selection_visual()
            self._show_toolbar(x2, y2)
        else:
            if self.rect_id:
                self.canvas.delete(self.rect_id)
            self.box_coords = None

    def _move_box(self, dx, dy):
        if not self.box_coords:
            return
        self.box_coords[0] += dx
        self.box_coords[1] += dy
        self.box_coords[2] += dx
        self.box_coords[3] += dy
        self._update_selection_visual()
        self._show_toolbar(self.box_coords[2], self.box_coords[3])

    def _resize_box(self, dw, dh):
        if not self.box_coords:
            return
        self.box_coords[2] = max(self.box_coords[0] + 10, self.box_coords[2] + dw)
        self.box_coords[3] = max(self.box_coords[1] + 10, self.box_coords[3] + dh)
        self._update_selection_visual()
        self._show_toolbar(self.box_coords[2], self.box_coords[3])

    def _update_selection_visual(self):
        if not self.box_coords:
            return
        x1, y1, x2, y2 = self.box_coords
        if self.rect_id:
            self.canvas.coords(self.rect_id, x1, y1, x2, y2)
            self.canvas.itemconfig(self.rect_id, outline="#ff2222", width=3)

    def _show_toolbar(self, x, y):
        """Floating action bar and on-screen keyboard controls guide."""
        if self.toolbar_frame:
            self.toolbar_frame.destroy()

        self.toolbar_frame = tk.Frame(self.snip_win, bg="#1a1a1a", bd=1, relief="solid", padx=8, pady=6)

        # Row 1: Actions & Language Selector
        action_row = tk.Frame(self.toolbar_frame, bg="#1a1a1a")
        action_row.pack(fill="x")

        tk.Label(action_row, text="Target:", fg="#aaaaaa", bg="#1a1a1a", font=("Segoe UI", 9)).pack(side="left", padx=(2, 4))

        combo = ttk.Combobox(action_row, textvariable=self.lang_var, values=AVAILABLE_LANGUAGES, width=12, state="readonly")
        combo.pack(side="left", padx=4)

        btn_approve = tk.Button(action_row, text="✔ Translate (Enter)", command=self._approve_and_translate, bg="#2e7d32", fg="white", font=("Segoe UI", 9, "bold"), relief="flat", padx=8)
        btn_approve.pack(side="left", padx=4)

        btn_cancel = tk.Button(action_row, text="✖ Cancel (Esc)", command=self._close_snip, bg="#424242", fg="white", font=("Segoe UI", 9), relief="flat", padx=6)
        btn_cancel.pack(side="left", padx=2)

        # Row 2: Built-in Cheatsheet / Súgó
        help_row = tk.Frame(self.toolbar_frame, bg="#222222", bd=0, padx=6, pady=4)
        help_row.pack(fill="x", pady=(6, 0))

        help_text = "💡 Move: Arrows (Shift: 10px)  |  Resize: Alt + Arrows (Shift: 10px)"
        tk.Label(help_row, text=help_text, fg="#8bc34a", bg="#222222", font=("Consolas", 8)).pack(anchor="w")

        # Védelem bal és jobb szélső kilógás ellen is
        pos_x = max(10, min(x, self.screenshot_img.width - 430))
        pos_y = y + 10 if (y + 80) < self.screenshot_img.height else max(10, y - 75)
        self.toolbar_frame.place(x=pos_x, y=pos_y)

    def _approve_and_translate(self):
        if not self.box_coords:
            return

        x1, y1, x2, y2 = self.box_coords
        cropped = self.screenshot_img.crop((x1, y1, x2, y2))
        target_language = self.lang_var.get()

        self._close_snip()
        self._process_translation(cropped, target_language)

    def _process_translation(self, cropped_img: Image.Image, target_lang: str):
        loading = tk.Toplevel(self.root)
        loading.title("Processing...")
        loading.geometry("340x85")
        loading.attributes("-topmost", True)
        loading.config(bg="#1f1f1f")

        status_lbl = tk.Label(loading, text="🤖 Selecting model...", fg="#aaaaaa", bg="#1f1f1f", font=("Segoe UI", 9))
        status_lbl.pack(pady=(12, 2))
        tk.Label(loading, text=f"Translating to {target_lang}...", fg="#ffffff", bg="#1f1f1f",
                 font=("Segoe UI", 10, "bold")).pack()

        def worker():
            models = get_sorted_flash_models(self.client)
            prompt = (
                f"Extract the text verbatim from this image in its source language.\n"
                f"Then translate it into natural, fluent {target_lang}.\n\n"
                f"Strictly format your response as:\n"
                f"ORIGINAL:\n[extracted text]\n\n"
                f"TRANSLATED:\n[translated text]"
            )

            res_text = None
            err_msg = ""
            active_model = "unknown"

            for model in models:
                active_model = model
                loading.after(0, lambda m=model: status_lbl.config(text=f"🤖 Active Model: {m}"))
                try:
                    res = self.client.models.generate_content(model=model, contents=[cropped_img, prompt])
                    res_text = res.text.strip()
                    break
                except Exception as e:
                    err_msg = str(e)

            if res_text and "TRANSLATED:" in res_text:
                parts = res_text.split("TRANSLATED:")
                orig = parts[0].replace("ORIGINAL:", "").strip()
                trans = parts[1].strip()
            elif res_text:
                orig = "Detected"
                trans = res_text
            else:
                orig = "Error"
                trans = f"API Error: {err_msg}"

            self.root.after(0, lambda: self._show_result(loading, orig, trans, active_model, target_lang))

        threading.Thread(target=worker, daemon=True).start()

    def _show_result(self, loading_win: tk.Toplevel, orig: str, trans: str, used_model: str, target_lang: str):
        try:
            loading_win.destroy()
        except Exception:
            pass

        win = tk.Toplevel(self.root)
        win.title("Gemini Screen Translator")
        win.attributes("-topmost", True)
        win.geometry("780x560")
        win.minsize(540, 360)
        win.config(bg="#1a1a1a")

        # FONTOS: Központi bezáró logika az állapot visszaállításához
        def close():
            win.destroy()
            self.is_busy = False

        # Elfogjuk a Windows [X] gombjának kattintását!
        win.protocol("WM_DELETE_WINDOW", close)

        main_container = tk.Frame(win, bg="#1a1a1a", padx=16, pady=14)
        main_container.pack(fill="both", expand=True)

        bottom_row = tk.Frame(main_container, bg="#1a1a1a")
        bottom_row.pack(side="bottom", fill="x", pady=(12, 0))

        tk.Label(bottom_row, text=f"⚡ Model: {used_model}", fg="#777777", bg="#1a1a1a", font=("Consolas", 8)).pack(side="left")

        def copy_translation():
            win.clipboard_clear()
            win.clipboard_append(trans)
            btn_copy.config(text="Copied! ✔")
            win.after(1500, lambda: btn_copy.config(text="Copy Translation"))

        btn_close = tk.Button(bottom_row, text="Close (Esc)", command=close, bg="#333333", fg="white", relief="flat", padx=12, pady=5, font=("Segoe UI", 9))
        btn_close.pack(side="right")

        btn_copy = tk.Button(bottom_row, text="Copy Translation", command=copy_translation, bg="#2a2a2a", fg="#cccccc", relief="flat", padx=10, pady=5, font=("Segoe UI", 9))
        btn_copy.pack(side="right", padx=(0, 8))

        text_container = tk.Frame(main_container, bg="#1a1a1a")
        text_container.pack(side="top", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(text_container, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        text_area = tk.Text(
            text_container,
            wrap="word",
            bg="#222222",
            fg="#ffffff",
            bd=0,
            padx=14,
            pady=12,
            height=10,
            highlightthickness=1,
            highlightbackground="#333333",
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10)
        )
        text_area.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text_area.yview)

        text_area.tag_configure("header_orig", font=("Segoe UI", 9, "bold"), foreground="#888888", spacing3=6)
        text_area.tag_configure("body_orig", font=("Segoe UI", 10), foreground="#cccccc", spacing3=14)
        text_area.tag_configure("divider", font=("Segoe UI", 8), foreground="#444444", spacing3=12)
        text_area.tag_configure("header_trans", font=("Segoe UI", 10, "bold"), foreground="#4CAF50", spacing3=6)
        text_area.tag_configure("body_trans", font=("Segoe UI", 11, "bold"), foreground="#ffffff", spacing3=10)

        text_area.insert("end", "ORIGINAL TEXT:\n", "header_orig")
        text_area.insert("end", f"{orig}\n\n", "body_orig")
        text_area.insert("end", "―" * 65 + "\n\n", "divider")
        text_area.insert("end", f"TRANSLATION ({target_lang.upper()}):\n", "header_trans")
        text_area.insert("end", f"{trans}\n", "body_trans")

        text_area.config(state="disabled")
        text_area.see("1.0")

        win.bind("<Escape>", lambda _: close())
        win.focus_force()


if __name__ == "__main__":
    if not GEMINI_API_KEY:
        root_temp = tk.Tk()
        root_temp.withdraw()
        messagebox.showerror(
            "Missing API Key",
            "GEMINI_API_KEY was not found in environment variables!\n\n"
            "Please create a .env file next to main.py containing:\n"
            "GEMINI_API_KEY=your_key_here"
        )
        exit(1)

    main_root = tk.Tk()
    main_root.withdraw()

    app = ScreenTranslatorApp(main_root)

    print("=" * 60)
    print("Gemini Screen Translator (Multi-Monitor & Multi-Lang) is running.")
    print(f"Hotkey: [{HOTKEY_COMBINATION}]")
    print(f"Default Language: [{DEFAULT_TARGET_LANG}]")
    print("Exit: Close this terminal window (Ctrl + C).")
    print("=" * 60)

    hotkey_listener = keyboard.GlobalHotKeys({HOTKEY_COMBINATION: app.trigger_snip})
    hotkey_listener.start()

    try:
        main_root.mainloop()
    finally:
        hotkey_listener.stop()