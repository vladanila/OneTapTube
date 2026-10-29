# OneTapTube

<p align="center">
  <img src="app_icon.png" width="120" height="120" alt="OneTapTube Icon" />
</p>

<p align="center">
  <b>A high-performance Windows desktop audio downloader and archiver for YouTube & YouTube Music.</b><br>
  Features automated clipboard monitoring, direct M4A stream remuxing, batch album processing, in-app audio preview, and native system tray integration.
</p>

<p align="center">
  <a href="https://github.com/vladanila/OneTapTube/releases/latest">
    <img src="https://img.shields.io/github/v/release/vladanila/OneTapTube?style=flat-square&color=blue&label=Latest%20Release" alt="Latest Release" />
  </a>
  <a href="https://github.com/vladanila/OneTapTube/releases">
    <img src="https://img.shields.io/github/downloads/vladanila/OneTapTube/total?style=flat-square&color=success&label=Downloads" alt="Total Downloads" />
  </a>
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6?style=flat-square&logo=windows" alt="Platform" />
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python" alt="Python Version" />
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License" />
</p>

---

## Overview

OneTapTube is an offline audio extraction client tailored for speed, simplicity, and audio fidelity. By listening to Windows clipboard events, OneTapTube automatically captures YouTube and YouTube Music URLs the moment they are copied, immediately queuing them for background extraction without requiring manual application interaction.

---

## Key Features

- **Automated Clipboard Pipeline**: Real-time clipboard polling automatically detects YouTube and YouTube Music tracks and queues downloads instantly upon copying (`Ctrl + C`).
- **Native Win32 Clipboard Isolation**: Employs direct Windows API Unicode clipboard access, guaranteeing zero GUI thread contention or UI freezes during background polling.
- **Smart Intro & Skit Removal (SponsorBlock)**: Cleans downloaded audio tracks of non-music intro/outro dialogue, music video acting skits, and sponsor interruptions automatically.
- **Lightning M4A Audio Mode**: Remuxes native YouTube AAC streams (`format 140`) into `.m4a` containers in approximately one second with zero lossy transcoding.
- **Universal Format Selection**: Supports MP3 (custom bitrates from 64 kbps to 320 kbps), M4A (untouched stream), and FLAC (lossless).
- **Multi-Threaded Turbo Processing**: Concurrently processes up to 3 downloads with intelligent single-leader progress bar stabilization.
- **Batch Playlist & Album Downloader**: Automatically identifies playlist and album URLs, providing one-click batch queuing and download progress tracking for entire tracklists.
- **Integrated Audio Preview Player**: Features a lightweight native Windows audio preview engine directly within the download history table, enabling immediate track verification without third-party media players.
- **Intelligent Deduplication**: Scans target directories prior to downloading to skip existing tracks, conserving network bandwidth and avoiding redundant disk writes.
- **Interactive Contextual Tooltips**: Hover-activated contextual guides provide real-time explanations for all settings and toggles.
- **Native System Tray Integration**: Minimizes unobtrusively to the Windows system tray with active background monitoring and native Windows toast alerts.
- **Decoupled Engine Architecture**: Isolated executable architecture ensures continuous operation even when upstream extraction APIs evolve, featuring built-in one-click engine updates.
- **Zero-Configuration Provisioning**: Automatically detects, downloads, and provisions necessary extraction and encoding binaries (`yt-dlp` and `FFmpeg`) on clean systems.

---

## Technical Architecture

| Component | Technology | Description |
| :--- | :--- | :--- |
| **Graphical Interface** | CustomTkinter | Modern dark-themed user interface |
| **Extraction Engine** | Standalone `yt-dlp` | Headless, decoupled audio stream retrieval |
| **Audio Processing** | FFmpeg | Audio conversion, remuxing, and metadata embedding |
| **Audio Playback** | Windows MCI & PresentationCore | Hybrid low-latency native Windows audio preview |
| **Background Service** | Pystray / Win32 | Native system tray lifecycle and notification integration |
| **Packaging** | PyInstaller | Portable, single-file Windows executable |

---

## Installation & Usage

### Option 1: Standalone Binary (Recommended)

1. Download **`OneTapTube.exe`** from the [**Releases**](https://github.com/vladanila/OneTapTube/releases/latest) section.
2. Launch `OneTapTube.exe`. No installation, Python environment, or administrative privileges required.
3. On first startup, if extraction dependencies are absent, OneTapTube will automatically offer one-click dependency installation.

### Option 2: Running from Source

#### Prerequisites
- Windows 10 / 11 (64-bit)
- Python 3.10 or higher
- Git

#### Setup
1. Clone the repository:
   ```bash
   git clone https://github.com/vladanila/OneTapTube.git
   cd OneTapTube
   ```

2. Install dependencies:
   ```bash
   pip install customtkinter yt-dlp pyinstaller pillow pystray
   ```

3. Run the application:
   ```bash
   python gui_app.py
   ```

4. Build standalone executable:
   ```bash
   python build_exe.py
   ```

---

## Configuration

Settings are saved in `config.json` in the application directory:

```json
{
  "download_dir": "downloads",
  "audio_format": "mp3",
  "audio_quality": "160",
  "embed_metadata": true,
  "embed_thumbnail": true,
  "auto_clipboard": true,
  "skip_existing": true,
  "minimize_to_tray": true,
  "concurrent_downloads": "3"
}
```

---

## License

This project is open-source under the MIT License. Designed strictly for personal, private offline archiving of media.
