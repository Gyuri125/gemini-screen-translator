<div align="center">

# Gemini Screen Translator

**Real-time, multi-monitor in-game screen capture and AI vision translation overlay.**  
*Powered by Google Gemini Multimodal Flash, MSS Framebuffer Capture, and Tkinter.*

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python&logoColor=white)](https://python.org)
[![AI Engine](https://img.shields.io/badge/AI-Google%20Gemini%20Flash-4285F4?logo=google&logoColor=white)](https://aistudio.google.com)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://microsoft.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

<br/>

[Overview](#overview) •
[Features](#features) •
[Controls](#controls) •
[Installation](#installation) •
[Configuration](#configuration) •
[Architecture](#architecture) •
[Building Executable](#building-executable)

</div>

---

## Overview

Many video games, visual novels, manga readers, and specialized desktop applications lack official translations or run in exclusive fullscreen DirectX environments where traditional desktop OCR utilities fail. Additionally, legacy local OCR engines frequently produce transcription errors when confronted with stylized typography, game interface fonts, textures, or low-contrast backgrounds.

Gemini Screen Translator addresses this through a modern multimodal pipeline:

1. **Direct Framebuffer Capture:** Captures freeze-frame snips across any connected display via MSS, bypassing DirectX black-screen capture issues.
2. **Native Multimodal Vision:** Streams cropped screen regions directly to Google Gemini Flash Vision. The vision model performs verbatim transcription, source language detection, and context-aware translation in a single low-latency call.
3. **Zero Local Model Overhead:** Requires no heavy local OCR binaries, model weights, or specialized GPU setup.

---

## Features

### Display and HUD Integration
* **Compact Subtitle HUD:** Renders translations as a borderless, floating subtitle card positioned directly below the cropped region. Ideal for games and visual novels without cluttering the screen.
* **Full Result Viewer:** Multi-pane detailed window containing original transcribed text, detected source language, translation output, and model telemetry.
* **Dimmed Snip Overlay:** Semi-transparent dark mask dynamically highlights your selection while dimming surrounding screen content.
* **8-Point Mouse Resize Handles:** Adjust active selections using 8 corner and edge handles, or drag the inside of the box to reposition.
* **Multi-Monitor Coordinate Space:** Maps seamless coordinate spaces across multiple displays, including secondary screens with negative virtual coordinates.
* **Per-Monitor DPI Awareness:** Windows Per-Monitor v2 DPI handling ensures 1:1 pixel accuracy across 100%, 125%, 150%, and 4K displays.

### Performance and AI Engine
* **Model Discovery Caching:** Resolves available Gemini Flash models on startup in the background. Snip requests route immediately without runtime list latency.
* **Structured JSON Schema:** Enforces response schema via Pydantic (`detected_language`, `original_text`, `translated_text`), preventing formatting anomalies and string-parsing failures.
* **Image Optimization:** Downsamples oversized captures (such as 4K dialogue boxes) to max 1600 px RGB, reducing upload payload size by up to 70%.

### User Experience
* **Translation History (Alt + H):** In-memory rolling log of past translations with real-time text search, timestamps, and per-item clipboard copy.
* **Automatic Clipboard Copy:** Optionally copies translations directly to the Windows clipboard upon completion.
* **System Tray Integration:** Unobtrusive system tray icon with quick menus for language selection, display mode toggle, settings, and graceful exit.

---

## Controls

| Action | Control |
|---|---|
| **Trigger Snip & Translate** | `Alt + T` *(Configurable in `.env`)* |
| **Open Translation History** | `Alt + H` *(Configurable in `.env`)* |
| **Select Screen Area** | Left Click + Drag mouse |
| **Resize Selection** | Drag any of the 8 handles (`NW`, `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`) |
| **Move Selection Box** | Click and drag inside the selection box |
| **Nudge Selection (1 px)** | Arrow keys (`Left`, `Right`, `Up`, `Down`) |
| **Nudge Selection (10 px)** | `Shift` + Arrow keys |
| **Resize Selection (1 px)** | `Alt` + Arrow keys |
| **Resize Selection (10 px)** | `Alt` + `Shift` + Arrow keys |
| **Approve & Translate** | `Enter` or click "Translate" button |
| **Dismiss / Cancel** | `Escape` |

---

## Supported Languages

The application automatically detects the source language in the image and supports on-the-fly translation into:

* English *(Default)*
* Hungarian
* German
* Japanese
* French
* Spanish
* Italian
* Russian
* Chinese
* Korean
* Portuguese

*Additional languages can be set directly in `.env`.*

---

## Installation

### Prerequisites
* Windows 10 or Windows 11 (64-bit)
* Python 3.10, 3.11, or 3.12
* Free Google Gemini API Key ([Google AI Studio](https://aistudio.google.com/))

### Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Gyuri125/gemini-screen-translator.git
   cd gemini-screen-translator
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables:**
   ```bash
   copy .env.example .env
   ```
   Open `.env` in a text editor and add your API key:
   ```env
   GEMINI_API_KEY=your_actual_api_key_here
   HOTKEY=<alt>+t
   HISTORY_HOTKEY=<alt>+h
   TARGET_LANGUAGE=English
   OVERLAY_MODE=compact
   AUTO_COPY=false
   ```

5. **Start the application:**
   ```bash
   python main.py
   ```
   *The application will minimize to the Windows system tray. Press `Alt + T` anywhere to capture and translate.*

---

## Configuration

All application settings are stored in `.env` and can also be modified through the System Tray menu:

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(Required)* | Google AI Studio API key |
| `HOTKEY` | `<alt>+t` | Global hotkey to trigger screen capture overlay |
| `HISTORY_HOTKEY` | `<alt>+h` | Global hotkey to open translation history |
| `TARGET_LANGUAGE` | `English` | Target translation language |
| `OVERLAY_MODE` | `compact` | Display mode: `compact` (floating subtitle HUD) or `window` (detailed window) |
| `AUTO_COPY` | `false` | Automatically copy translated text to the system clipboard |

---

## Architecture

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
                  │   1. PIL Image Resizing / RGB Optimization   │
                  │   2. Gemini Flash Vision API Call           │
                  │   3. Pydantic Structured JSON Validation    │
                  │   4. History Rolling Buffer Update          │
                  └──────────────┬──────────────────────────────┘
                                 │ root.after(0)
                  ┌──────────────▼──────────────────────────────┐
                  │         Display Result (Main Thread)        │
                  │    Compact Subtitle HUD  OR  Full Window    │
                  └─────────────────────────────────────────────┘
```

---

## Building Executable

You can compile Gemini Screen Translator into a standalone Windows executable.

### Method 1: Automated Script (Recommended)
Double-click `build_exe.bat` or run:
```cmd
build_exe.bat
```
This script cleans previous build artifacts, verifies virtual environment dependencies, and generates a fresh build at:
`dist\GeminiScreenTranslator.exe`

### Method 2: Manual PyInstaller
```bash
pip install pyinstaller
pyinstaller fordito.spec --noconfirm --clean
```

---

## License

This project is licensed under the [MIT License](LICENSE).