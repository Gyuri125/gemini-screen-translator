# Gemini Screen Translator

Real-time, multi-monitor in-game screen capture and AI-powered translation overlay.

---

## Overview & Purpose

Many video games, visual novels, and specialized applications lack official translations or run in exclusive fullscreen environments that block traditional desktop OCR tools. Standard local OCR engines frequently misread stylized typography, game interface fonts, or low-contrast backgrounds.

Gemini Screen Translator addresses this by streaming a raw, high-resolution screen capture directly to Google Gemini's multimodal Flash models. The vision model analyzes the visual context, transcribes the original text verbatim, and produces an accurate translation in a single low-latency operation.

### Key Advantages
- In-Game Compatibility: Bypasses black-screen capture issues in fullscreen DirectX applications using direct framebuffer capture via MSS.
- Context-Aware Vision: Eliminates OCR transcription errors on decorative, stylized, or low-contrast fonts without local OCR training.
- Zero Local Overhead: Requires no local model weight downloads or third-party OCR software installations.
- Multi-Monitor Integration: Spans seamlessly across multi-display setups, including displays with negative virtual space coordinates.

---

## Supported Languages

The tool automatically identifies and transcribes any source language appearing on screen. The interactive HUD allows on-the-fly translation into:
- English (Default)
- Hungarian
- German
- Japanese
- French
- Spanish
- Italian
- Russian
- Chinese

Additional target languages can be defined in the configuration file.

---

## Key Features

- Multi-Monitor Capture: Maps unified coordinate spaces across all attached displays.
- DirectX Framebuffer Read: Captures freeze-frame snips instantly without tearing or display interruption.
- Interactive HUD & Language Switcher: Change target languages and verify selection borders before issuing API requests.
- Sub-Pixel Keyboard Fine-Tuning:
  - Move selection (1px): Arrow keys
  - Move selection (10px): Shift + Arrow keys
  - Resize selection (1px): Alt + Arrow keys
  - Resize selection (10px): Alt + Shift + Arrow keys
- Scrollable Result Viewer: Accommodates long paragraphs and multi-line dialogues with a dedicated clipboard copy button.
- Dynamic Flash Fallback: Automatically resolves and routes requests to the fastest available Gemini Flash model on your API tier.
- Windows DPI Awareness: Built-in per-monitor DPI awareness handles 100%, 125%, 150%, and 4K display scaling without alignment drift.

---

## Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/Gyuri125/gemini-screen-translator.git
cd gemini-screen-translator
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure your environment
1. Create a free API key at Google AI Studio: [https://aistudio.google.com/](https://aistudio.google.com/)
2. Copy the sample environment file:
   ```bash
   copy .env.example .env
   ```
3. Open `.env` and paste your key:
   ```env
   GEMINI_API_KEY=your_actual_api_key_here
   HOTKEY=<alt>+t
   TARGET_LANGUAGE=English
   ```

---

## Usage & Controls

1. Run the application:
   ```bash
   python main.py
   ```
2. Trigger the overlay anywhere: Press `Alt + T` (or your configured hotkey).
3. Draw a bounding box around the text you want translated.
4. Optional adjustments:
   - Fine-tune placement using Arrow keys or Alt + Arrow keys.
   - Change the target language via the dropdown menu.
5. Press `Enter` or click "Translate" to submit.
6. The detected original text and its translation will appear in the result window.
7. Dismiss overlays or close windows anytime using `Escape`.

---

## Tech Stack

- Language: Python 3.10+
- AI Provider: Google Gemini API (google-genai SDK)
- Screen Capture: MSS
- GUI Engine: Tkinter, Pillow (PIL)
- Global Input Hook: Pynput

---

## License

This project is licensed under the MIT License.