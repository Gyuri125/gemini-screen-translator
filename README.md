<div align="center">

# ⚡ Gemini Screen Translator

**Next-generation, real-time in-game screen capture & AI vision translation overlay.**  
*Powered by Google Gemini Multimodal Flash Models, MSS Framebuffer Capture & Tkinter HUD.*

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?logo=python&logoColor=white)](https://python.org)
[![AI Engine](https://img.shields.io/badge/AI-Google%20Gemini%202.5%20%2F%202.0%20Flash-4285F4?logo=google&logoColor=white)](https://aistudio.google.com)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://microsoft.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style](https://img.shields.io/badge/code%20style-PEP%208-brightgreen)](https://www.python.org/dev/peps/pep-0008/)

<br/>

[Key Features](#-key-features) •
[Interactive Controls](#-interactive-controls) •
[Installation](#-installation--setup) •
[Configuration](#-configuration) •
[Architecture](#-architecture) •
[Standalone Executable](#-standalone-executable-build)

</div>

---

## 🌟 Overview

Many games, visual novels, manga readers, and specialized software lack official translations or run in exclusive fullscreen DirectX environments where traditional desktop OCR fails. Furthermore, legacy local OCR engines (such as Tesseract) struggle with stylized typography, decorative game fonts, textures, and low-contrast backgrounds.

**Gemini Screen Translator** solves this completely:
1. **Raw Framebuffer Capture:** Direct DirectX/Desktop capture via MSS captures freeze-frame snips across any monitor without black-screen artifacts.
2. **End-to-End Multimodal Vision:** Streams the cropped region directly to **Google Gemini Flash Vision**, performing verbatim transcription, language identification, and natural translation in a **single low-latency operation**.
3. **Zero Local Weights:** Requires no bulky local OCR downloads or GPU model setup.

---

## 🚀 Key Features

### 🖥️ In-Game HUD & Display Integration
* **Floating Compact Subtitle Mode:** Displays translations as sleek, floating subtitles directly below the game dialogue without obscuring your screen.
* **Full Result Viewer:** Multi-pane detailed window displaying original transcribed text, detected language, translated text, model metrics, and quick clipboard copying.
* **Dimmed Snip Overlay:** Semi-transparent dark mask highlights your selected bounding box while dimming surrounding desktop elements.
* **8-Point Mouse Resize Handles:** Drag any corner or edge with the mouse to resize, or click inside the box to reposition.
* **Multi-Monitor Virtual Desktop:** Seamlessly captures multi-display setups, including secondary displays placed at negative virtual coordinates.
* **Per-Monitor DPI Awareness:** Built-in Windows Per-Monitor v2 DPI scaling guarantees pixel-perfect selection alignment on 100%, 125%, 150%, and 4K scaling.

### ⚡ Performance & AI Engine
* **High-Speed Model Caching:** Background model resolution and prioritized routing (`gemini-2.5-flash` ➔ `gemini-2.0-flash`) eliminates network delays on translate clicks.
* **Structured JSON Outputs:** Uses native `Pydantic` schema enforcement for 100% resilient parsing—no brittle string delimiters or markdown artifacts.
* **Bandwidth & Image Optimization:** Auto-scales large 4K crops and converts to optimized RGB, reducing network upload payload by up to 70%.

### 🎮 Gamer & Productivity Quality of Life
* **Translation History (`Alt + H`):** Keep track of your last 50 translations with instant search, timestamps, language indicators, and one-click copy.
* **Automatic Clipboard Copy:** Optionally auto-copies translation output to your clipboard immediately upon completion.
* **System Tray Companion (`pystray`):** Runs unobtrusively in the Windows taskbar notification area with a quick-access context menu.

---

## 🎮 Interactive Controls

| Input Action | Description |
|---|---|
| <kbd>Alt</kbd> + <kbd>T</kbd> | **Trigger Capture Overlay** (Configurable in `.env`) |
| <kbd>Alt</kbd> + <kbd>H</kbd> | **Open Translation History** (Configurable in `.env`) |
| **Mouse Left Drag** | Draw a new bounding box anywhere on screen |
| **Mouse Drag Handles** | Pull any of the 8 handles (`NW`, `N`, `NE`, `E`, `SE`, `S`, `SW`, `W`) to resize |
| **Mouse Drag Inside** | Move the entire selection box |
| <kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd> | Nudge selection by **1 px** |
| <kbd>Shift</kbd> + Arrows | Nudge selection by **10 px** |
| <kbd>Alt</kbd> + Arrows | Resize selection by **1 px** |
| <kbd>Alt</kbd> + <kbd>Shift</kbd> + Arrows | Resize selection by **10 px** |
| <kbd>Enter</kbd> | **Approve & Translate** selected region |
| <kbd>Escape</kbd> | Cancel snip, dismiss HUD, or close result window |

---

## 🌐 Supported Languages

The AI automatically transcribes and detects any source language appearing on screen, and translates into your target choice:

| Language | Language | Language | Language |
|---|---|---|---|
| 🇬🇧 English | 🇭🇺 Hungarian | 🇩🇪 German | 🇯🇵 Japanese |
| 🇫🇷 French | 🇪🇸 Spanish | 🇮🇹 Italian | 🇷🇺 Russian |
| 🇨🇳 Chinese | 🇰🇷 Korean | 🇵🇹 Portuguese | *Custom defined in `.env`* |

---

## 🛠️ Installation & Setup

### Prerequisites
* Windows 10 or 11 (64-bit)
* Python 3.10, 3.11, or 3.12
* Free Google Gemini API Key from [Google AI Studio](https://aistudio.google.com/)

### 1. Clone the repository
```bash
git clone https://github.com/Gyuri125/gemini-screen-translator.git
cd gemini-screen-translator
```

### 2. Create and activate a virtual environment
```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
Copy the sample environment file:
```bash
copy .env.example .env
```
Open `.env` in Notepad and insert your Gemini API Key:
```env
GEMINI_API_KEY=AIzaSyYourActualGeminiApiKeyHere
HOTKEY=<alt>+t
HISTORY_HOTKEY=<alt>+h
TARGET_LANGUAGE=English
OVERLAY_MODE=compact
AUTO_COPY=false
```

### 5. Launch the application
```bash
python main.py
```
*The app will minimize to the System Tray. Press <kbd>Alt + T</kbd> anytime to snip and translate!*

---

## ⚙️ Configuration

All settings can be customized in `.env` or adjusted live from the System Tray menu:

```env
# Google Gemini API Key (Required)
GEMINI_API_KEY=your_gemini_api_key_here

# Global Hotkeys (pynput syntax)
HOTKEY=<alt>+t
HISTORY_HOTKEY=<alt>+h

# Default Target Language
TARGET_LANGUAGE=English

# Result Overlay Mode: "compact" (floating in-game subtitle) or "window" (full detailed window)
OVERLAY_MODE=compact

# Automatically copy translated text to the system clipboard (true / false)
AUTO_COPY=false
```

---

## 🏛️ Architecture

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
                  │   1. PIL Image Resizing / JPEG Optim        │
                  │   2. Gemini API Flash Vision Call           │
                  │   3. Pydantic Structured JSON Validation    │
                  │   4. History Buffer Update                  │
                  └──────────────┬──────────────────────────────┘
                                 │ root.after(0)
                  ┌──────────────▼──────────────────────────────┐
                  │         Display Result (Main Thread)        │
                  │    Compact Subtitle HUD  OR  Full Window    │
                  └─────────────────────────────────────────────┘
```

---

## 📦 Standalone Executable Build

You can compile **Gemini Screen Translator** into a portable Windows executable using the included one-click build script or via PyInstaller:

### Option 1: One-Click Build Script (Recommended)
Simply double-click `build_exe.bat` or run in terminal:
```cmd
build_exe.bat
```
*This automatically cleans previous builds, ensures virtual environment activation, and compiles a fresh `dist/GeminiScreenTranslator.exe`.*

### Option 2: Manual PyInstaller Command
```bash
pip install pyinstaller
pyinstaller fordito.spec --noconfirm --clean
```

The resulting standalone executable will be generated at:
`dist/GeminiScreenTranslator.exe`


---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
Feel free to use, modify, and distribute it for personal and commercial projects.