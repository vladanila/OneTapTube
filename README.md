# OneTapTube

<p align="center">
  <img src="icon.ico" width="128" height="128" alt="OneTapTube Icon" />
</p>

<p align="center">
  <b>A modern, high-speed Windows desktop music downloader for YouTube & YouTube Music with automatic clipboard capture, album/playlist batch downloading, in-app audio preview, and native system tray integration.</b>
</p>

<p align="center">
  <a href="https://github.com/vladanila/OneTapTube/releases/latest">
    <img src="https://img.shields.io/badge/Download-OneTapTube%20v1.1.0-blue?style=for-the-badge&logo=windows" alt="Download OneTapTube" />
  </a>
</p>

---

## ✨ Features

- **⚡ Automatic Clipboard Detection**: Simply copy any song or album link (`Ctrl + C`) in YouTube Music, and OneTapTube automatically reads the clipboard and queues the download instantly.
- **💿 Full Album & Playlist Downloader**: Detects albums and playlists automatically and offers a 1-click batch download for all tracks with live progress.
- **▶️ In-App Mini Player**: Preview your downloaded songs directly inside OneTapTube using the native 1-click `▶ Preview` / `⏹ Stop` button without opening File Explorer.
- **⏩ Auto-Skip Existing Songs**: Checks your destination folder and skips already downloaded tracks in 0.1s to save time and bandwidth.
- **🚀 Multi-Threaded Concurrent Downloads**: Configurable speed settings (Sequential, Fast 2x, or Turbo 3x) to download multiple songs simultaneously.
- **🔔 System Tray & Native Toast Notifications**: Minimizes to the Windows system tray to silently monitor clipboard while you work or game, sending native Windows toasts when downloads finish.
- **🎵 Selectable Audio Quality**: Choose from 64, 128, 160, 192, 256, or 320 kbps MP3.
- **🏷️ ID3 Metadata & Album Art**: Embeds track title, artist name, and optional album cover art directly into the MP3 tags.
- **📂 Clean File Naming**: Songs are automatically saved as `Artist - Title.mp3` in your chosen destination folder.
- **🛡️ Future-Proof & Self-Healing**:
  - **Decoupled Engine**: Built-in 1-click `yt-dlp` updater ensures fast downloads whenever YouTube updates.
  - **Zero-Setup on Clean PCs**: Auto-detects and provisions required audio engines (`yt-dlp` and `FFmpeg`) on first launch with 1-click installation.

---

## 🚀 Download & Installation

1. Go to the [**Releases**](https://github.com/vladanila/OneTapTube/releases/latest) page.
2. Download **`OneTapTube.exe`**.
3. Double-click `OneTapTube.exe` to run. No installer or Python environment required!

---

## 🛠️ Building from Source

1. Clone the repository:
   ```bash
   git clone https://github.com/vladanila/OneTapTube.git
   cd OneTapTube
   ```

2. Install Python dependencies:
   ```bash
   pip install customtkinter yt-dlp pyinstaller pillow pystray
   ```

3. Run the application:
   ```bash
   python gui_app.py
   ```

4. Compile standalone executable:
   ```bash
   python build_exe.py
   ```

---

## 📄 License
This project is open-source and intended for personal offline audio archiving.
