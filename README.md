# OneTapTube

<p align="center">
  <img src="icon.ico" width="128" height="128" alt="OneTapTube Icon" />
</p>

<p align="center">
  <b>A modern, 1-click Windows desktop music downloader for YouTube & YouTube Music with automatic clipboard capture, high-bitrate MP3 conversion, and ID3 tag embedding.</b>
</p>

<p align="center">
  <a href="https://github.com/vladanila/OneTapTube/releases/latest">
    <img src="https://img.shields.io/badge/Download-OneTapTube%20v1.0.0-blue?style=for-the-badge&logo=windows" alt="Download OneTapTube" />
  </a>
</p>

---

## ✨ Features

- **⚡ Automatic Clipboard Detection**: Simply copy any song link (`Ctrl + C` or `Share → Copy Link`) in YouTube Music, and OneTapTube automatically reads the clipboard and queues the download instantly.
- **🎵 Selectable Audio Quality**: Choose from 64, 128, 160, 192, 256, or 320 kbps MP3.
- **🏷️ ID3 Metadata & Album Art**: Embeds song title, artist name, and optional album cover art directly into the MP3 tags.
- **📂 Clean File Naming**: Songs are automatically saved as `Artist - Title.mp3` in your chosen destination folder.
- **📊 Real-Time Progress Bar**: Smooth percentage indicator showing live audio streaming and conversion status.
- **🛡️ Future-Proof & Self-Healing**:
  - **Decoupled Engine**: Built-in 1-click `yt-dlp` updater ensures fast downloads whenever YouTube changes streaming algorithms.
  - **Zero-Setup on Clean PCs**: Auto-detects and provisions required audio engines (`yt-dlp` and `FFmpeg`) on first launch with 1-click installation.

---

## 🚀 Download & Installation

1. Go to the [**Releases**](https://github.com/vladanila/OneTapTube/releases/latest) page.
2. Download **`OneTapTube.exe`**.
3. Double-click `OneTapTube.exe` to run. No installer or Python environment required!

---

## 🛠️ Building from Source

If you want to run or build the application from source code:

1. Clone the repository:
   ```bash
   git clone https://github.com/vladanila/OneTapTube.git
   cd OneTapTube
   ```

2. Install Python dependencies:
   ```bash
   pip install customtkinter yt-dlp pyinstaller pillow
   ```

3. Run the application:
   ```bash
   python gui_app.py
   ```

4. Compile a standalone `.exe`:
   ```bash
   python build_exe.py
   ```

---

## 📄 License
This project is open-source and intended for personal offline audio archiving.
