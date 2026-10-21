# Gemini Screen Translator — Agent & Developer Guide

This document provides a technical walkthrough of the **Gemini Screen Translator** codebase. It is written specifically for AI agents and human developers maintaining, refactoring, or extending the application.

---

## 1. High-Level Architecture & Lifecycle

The application is a single-process, multi-threaded desktop utility running on Windows with **Tkinter** as the GUI engine and **Google Gemini Vision** as the multimodal translation backend.

```
                  ┌──────────────────────────────────────────────┐
                  │              Main Thread (GUI)               │
                  │       tk.Tk (hidden root window)             │
                  │            Event Loop (.mainloop())          │
                  └──────────────▲──────────────▲────────────────┘
                                 │              │
                   root.after(0) │              │ root.after(0)
                                 │              │
    ┌────────────────────────────┴─┐          ┌─┴────────────────────────────┐
    │     pynput Global Hotkey     │          │     pystray System Tray      │
    │        Daemon Thread         │          │        Daemon Thread         │
    │  Listens for Alt+T / Alt+H   │          │   Renders Tray Icon & Menu   │
    └──────────────────────────────┘          └──────────────────────────────┘
                                 │
                            triggers snip
                                 │
                  ┌──────────────▼──────────────────────────────┐
                  │              Worker Daemon Thread           │
                  │   1. PIL Image Resizing / RGB Optim         │
                  │   2. Gemini API Flash Vision Call           │
                  │   3. Pydantic Structured JSON Validation    │
                  │   4. History Buffer Update                  │
                  │   5. Optional Native SAPI TTS Trigger       │
                  └──────────────┬──────────────────────────────┘
                                 │ root.after(0)
                  ┌──────────────▼──────────────────────────────┐
                  │         Display Result (Main Thread)        │
                  │  In-Place Lens  /  Subtitle HUD  /  Window  │
                  └─────────────────────────────────────────────┘
```

---

## 2. Key Modules & Subsystems

### 2.1 Display Coordinate System & DPI Awareness
* **DPI Awareness:** Initialized at process launch via `ctypes.windll.shcore.SetProcessDpiAwareness(2)` (Per-Monitor v2). This prevents Windows from virtualizing/scaling coordinates, ensuring mouse events map 1:1 with hardware framebuffer pixels across 100%, 125%, 150%, and 4K displays.
* **Multi-Monitor Unification:** Captured via `mss.MSS().monitors[0]`.
  * `monitors[0]` covers the virtual bounding box of all connected monitors (including displays with negative coordinates, e.g., left secondary monitor at `x = -1920`).
  * The overlay window (`snip_win`) is an unbordered `Toplevel` with `geometry("{width}x{height}+{left}+{top}")` and `-topmost=True`.
  * In the Tkinter `Canvas`, `(0, 0)` maps directly to `bounds['left'], bounds['top']` in screen space.

### 2.2 Interactive Bounding Box & Handles Math
The user interacts with the canvas via mouse and keyboard:
* **Dimmed Mask:** Four `create_rectangle` elements (`mask_top`, `mask_bottom`, `mask_left`, `mask_right`) filled with `#000000` and `stipple="gray25"`. They dynamically carve out the active selection `(x1, y1, x2, y2)`, leaving the selected area bright and dimming the rest of the desktop.
* **8 Resize Handles:** Small 8x8 px squares (`nw`, `n`, `ne`, `e`, `se`, `s`, `sw`, `w`).
* **Hit-Testing (`_hit_test`):**
  * Proximity `≤ 6px` to a handle ➔ `"resize"` mode for that handle.
  * Inside bounding box ➔ `"move"` mode with cursor `fleur`.
  * Outside bounding box ➔ `"create"` mode with cursor `cross`.
* **Keyboard Fine-Tuning:**
  * Arrows: Move box by 1 px (`Shift + Arrows`: 10 px).
  * `Alt + Arrows`: Resize box by 1 px (`Alt + Shift + Arrows`: 10 px).

### 2.3 Gemini Multimodal Vision & Model Routing
* **SDK:** `google-genai` (official Google GenAI SDK).
* **Model Discovery & Caching:**
  * Initialized with `FALLBACK_FLASH_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]`.
  * `_refresh_models_async()` runs on startup in a background daemon thread, calls `client.models.list()`, sorts models by version and lite tier, and caches the result.
  * **Critical:** `client.models.list()` is NEVER invoked inside the snip/translate worker thread. This eliminates 1–2 seconds of network overhead on every translation.
* **Structured Output (`Pydantic` Schema):**
  ```python
  class TranslationResult(BaseModel):
      detected_language: str
      original_text: str
      translated_text: str
  ```
  Passed to `types.GenerateContentConfig(response_mime_type="application/json", response_schema=TranslationResult, temperature=0.2)`.
  This guarantees that response text is 100% valid JSON without fragile regex or string delimiters.

### 2.4 Three Display Modes
1. **In-Place Lens Overlay (`_show_lens_overlay`):**
   * Inspired by Google Lens camera translation.
   * Renders directly on top of the original crop coordinates `(bx1, by1, bx2, by2)` with `-alpha 0.94` dark translucent glass.
   * Directly masks foreign dialogue text with native typography in the translated language.
   * Auto-dismisses on click, `Escape`, or after 15 seconds.
2. **Compact Subtitle HUD (`_show_compact_hud`):**
   * Designed for games and visual novels where original art should remain unobstructed.
   * Floats directly beneath (or above if constrained by screen boundary) the cropped region.
   * Auto-dismisses after 15 seconds, or closes on `Esc` / click.
   * Provides quick `🔊 Listen`, `📋 Copy`, `🔍 Full View`, and `📜 History` buttons.
3. **Detailed Window (`_show_detailed_window`):**
   * Traditional 780x560 multi-pane text view with original transcription, translation, model telemetry, TTS, and copy button.

### 2.5 Text-to-Speech Subsystem (Native Windows SAPI)
* Implemented via Windows native COM `SAPI.SpVoice` (`speak_text_async`).
* Operates in an asynchronous worker thread with `pythoncom.CoInitialize()`.
* Flag `3` (`SVSFlagsAsync | SVSFPurgeBeforeSpeak`) cancels active utterances and immediately speaks without blocking the Tkinter event loop.
* Zero external audio binaries or internet bandwidth required.

### 2.6 History System (`show_history_window`)
* In-memory rolling buffer (last 50 translations).
* Searchable via real-time Tkinter text filter.
* Shows timestamp, detected language pair (`JP ➔ EN`), original, and translated text with per-item copy and TTS speak buttons.
* Triggerable via hotkey (`Alt + H`), tray icon, or HUD buttons.

### 2.7 System Tray Integration (`pystray`)
* Runs in a daemon thread via `pystray.Icon`.
* Uses dynamic in-memory PIL icon (`create_app_icon`).
* Thread-safe interaction: All GUI triggers dispatch back to the Tkinter main thread using `self.root.after(0, callback)`.

---

## 3. Environment Variables Reference

| Variable | Type | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | `string` | *(Required)* | Google AI Studio API key |
| `HOTKEY` | `string` | `<alt>+t` | Global hotkey to trigger screen capture |
| `HISTORY_HOTKEY` | `string` | `<alt>+h` | Global hotkey to open translation history |
| `TARGET_LANGUAGE` | `string` | `English` | Default target translation language |
| `OVERLAY_MODE` | `string` | `compact` | Display mode: `"compact"` (HUD), `"lens"` (In-place), or `"window"` (Full) |
| `AUTO_COPY` | `boolean` | `false` | Automatically copy translated text to clipboard |
| `AUTO_TTS` | `boolean` | `false` | Automatically speak translated text aloud via Windows native TTS |

---

## 4. Maintenance & Modification Rules for Agents

1. **Thread Safety with Tkinter:**
   * Never modify Tkinter widgets or canvas objects directly from background threads (`worker()`, `pystray`, or `pynput`).
   * Always wrap UI updates in `self.root.after(0, lambda: ...)`.
2. **Do Not Reintroduce OCR Engines:**
   * Do NOT add Tesseract, pytesseract, or local EasyOCR dependencies. Gemini Vision Flash handles transcription and translation natively in a single API call with higher accuracy on stylized game fonts.
3. **Structured Outputs:**
   * Keep `TranslationResult` Pydantic model intact. If adding metadata, add fields to `TranslationResult` and let Gemini fill them via JSON schema.
4. **PyInstaller Packaging:**
   * Always build using `build_exe.bat` or `fordito.spec` (`pyinstaller fordito.spec --noconfirm --clean`).
   * Target executable is `dist/GeminiScreenTranslator.exe`.
