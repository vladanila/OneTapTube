import os
import re
import sys
import json
import time
import queue
import shutil
import zipfile
import threading
import urllib.request
import subprocess
import multiprocessing
from tkinter import filedialog
import unicodedata

# 1. Base Application Directory (Guaranteed to be project folder, never Temp/_MEI)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
DEFAULT_DOWNLOAD_DIR = os.path.join(APP_DIR, "downloads")
BIN_DIR = os.path.join(APP_DIR, "bin")

os.makedirs(BIN_DIR, exist_ok=True)
os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)

# Add BIN_DIR to PATH so any sub-process can find binaries
if BIN_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")

import customtkinter as ctk

# Appearance setup
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

YOUTUBE_REGEX = re.compile(r'(?:https?:\/\/)?(?:music\.)?youtu(?:be\.com\/(?:watch\?v=|shorts\/)|\.be\/)([a-zA-Z0-9_-]{11})')
YTDLP_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_DOWNLOAD_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

def get_ytdlp_path() -> str:
    """Finds yt-dlp.exe in bin/, root, or system PATH."""
    local_bin = os.path.join(BIN_DIR, "yt-dlp.exe")
    if os.path.exists(local_bin):
        return local_bin
    local_root = os.path.join(APP_DIR, "yt-dlp.exe")
    if os.path.exists(local_root):
        return local_root
    sys_path = shutil.which("yt-dlp")
    if sys_path:
        return sys_path
    return None

def get_ytdlp_version(ytdlp_path: str = None) -> str:
    """Executes yt-dlp --version cleanly in the background."""
    if not ytdlp_path:
        ytdlp_path = get_ytdlp_path()
    if not ytdlp_path or not os.path.exists(ytdlp_path):
        return None

    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        res = subprocess.run(
            [ytdlp_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None

def get_ffmpeg_path() -> str:
    """Finds ffmpeg.exe in bin/, root, or system PATH."""
    local_bin = os.path.join(BIN_DIR, "ffmpeg.exe")
    if os.path.exists(local_bin):
        return local_bin
    local_root = os.path.join(APP_DIR, "ffmpeg.exe")
    if os.path.exists(local_root):
        return local_root
    sys_path = shutil.which("ffmpeg")
    if sys_path:
        return sys_path
    return None


class MusicDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("OneTapTube - 1-Click Music Downloader")
        self.geometry("740x730")
        self.minsize(700, 680)

        # Set Window Icon
        icon_path = os.path.join(APP_DIR, "icon.ico")
        if not os.path.exists(icon_path) and getattr(sys, '_MEIPASS', None):
            icon_path = os.path.join(sys._MEIPASS, "icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Engine Version Tracking
        self.current_engine_version = get_ytdlp_version() or "Not Installed"
        self.latest_engine_version = None

        # Load Configuration
        self.config = self.load_config()

        # Threading & Queue
        self.download_queue = queue.Queue()
        self.currently_queued = set()
        self.lock = threading.Lock()
        self.running = True

        # Build UI
        self.create_widgets()

        # Check Dependencies (yt-dlp & FFmpeg) on startup
        self.check_dependencies_startup()

        # Start Background Download Worker Thread
        self.worker_thread = threading.Thread(target=self.download_worker, daemon=True)
        self.worker_thread.start()

        # Start Background Clipboard Poller Thread
        self.clipboard_thread = threading.Thread(target=self.clipboard_monitor, daemon=True)
        self.clipboard_thread.start()

        # Background update check on startup
        threading.Thread(target=self.check_for_updates_background, daemon=True).start()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_config(self):
        defaults = {
            "download_dir": DEFAULT_DOWNLOAD_DIR,
            "audio_quality": "160",
            "embed_metadata": True,
            "embed_thumbnail": False,
            "auto_clipboard": True
        }
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    defaults.update(saved)
            except Exception:
                pass

        # Protect against old Temp/_MEI paths
        saved_dir = defaults.get("download_dir", "")
        if not saved_dir or "_MEI" in saved_dir or saved_dir == "./downloads":
            defaults["download_dir"] = DEFAULT_DOWNLOAD_DIR
        else:
            defaults["download_dir"] = os.path.abspath(saved_dir)

        os.makedirs(defaults["download_dir"], exist_ok=True)
        return defaults

    def save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception:
            pass

    def create_widgets(self):
        # 1. Header Frame
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(15, 4))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        title_label = ctk.CTkLabel(
            title_box,
            text="OneTapTube",
            font=ctk.CTkFont(size=22, weight="bold")
        )
        title_label.pack(anchor="w")

        v_text = f"Engine: yt-dlp v{self.current_engine_version}" if self.current_engine_version != "Not Installed" else "Engine: Not Installed"
        self.engine_label = ctk.CTkLabel(
            title_box,
            text=v_text,
            font=ctk.CTkFont(size=11),
            text_color="#90CAF9" if self.current_engine_version != "Not Installed" else "#FFB74D"
        )
        self.engine_label.pack(anchor="w")

        # Top Right Actions (Update Button & Open Folder)
        actions_box = ctk.CTkFrame(header, fg_color="transparent")
        actions_box.pack(side="right")

        self.update_btn = ctk.CTkButton(
            actions_box,
            text="🔄 Check Updates",
            width=140,
            height=30,
            fg_color="#1E88E5",
            hover_color="#1565C0",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.on_check_update_clicked
        )
        self.update_btn.pack(side="left", padx=(0, 10))

        open_folder_btn = ctk.CTkButton(
            actions_box,
            text="📂 Open Folder",
            width=110,
            height=30,
            fg_color="#37474F",
            hover_color="#455A64",
            font=ctk.CTkFont(size=12),
            command=self.on_open_folder
        )
        open_folder_btn.pack(side="left")

        # First-Time Setup Banner (Visible ONLY if yt-dlp or FFmpeg is missing on a new PC)
        self.setup_banner = ctk.CTkFrame(self, fg_color="#C62828", corner_radius=8)
        self.setup_banner_label = ctk.CTkLabel(
            self.setup_banner,
            text="⚙ First-Time Setup: Required audio engines are missing.",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FFFFFF"
        )
        self.setup_banner_label.pack(side="left", padx=15, pady=8)

        self.setup_dl_btn = ctk.CTkButton(
            self.setup_banner,
            text="⬇ Auto-Install Components",
            height=26,
            fg_color="#FFFFFF",
            text_color="#C62828",
            hover_color="#EEEEEE",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.download_missing_components_auto
        )
        self.setup_dl_btn.pack(side="right", padx=15, pady=8)

        # 2. Auto-Clipboard Feature Card (Clear Explanation & Instant Feedback)
        clip_card = ctk.CTkFrame(self, corner_radius=10, border_width=1, border_color="#37474F")
        clip_card.pack(fill="x", padx=20, pady=6)

        c_top = ctk.CTkFrame(clip_card, fg_color="transparent")
        c_top.pack(fill="x", padx=15, pady=(10, 2))

        self.clip_switch = ctk.CTkSwitch(
            c_top,
            text="Auto-Download from Clipboard",
            command=self.on_clip_toggle,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        if self.config.get("auto_clipboard", True):
            self.clip_switch.select()
        else:
            self.clip_switch.deselect()
        self.clip_switch.pack(side="left")

        self.clip_status_badge = ctk.CTkLabel(
            c_top,
            text="● ACTIVE (Listening)",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#81C784" if self.config.get("auto_clipboard", True) else "#9E9E9E"
        )
        self.clip_status_badge.pack(side="right")

        # Explanation Text
        hint_text = ctk.CTkLabel(
            clip_card,
            text="💡 How it works: Simply copy any song link (Ctrl + C or Share → Copy Link) on YouTube Music.\nThe app automatically reads the clipboard and queues the download instantly!",
            font=ctk.CTkFont(size=11),
            text_color="#B0BEC5",
            justify="left"
        )
        hint_text.pack(anchor="w", padx=15, pady=(2, 6))

        # Dynamic Notification Banner (Lights up green when a song is copied)
        self.toast_banner = ctk.CTkLabel(
            clip_card,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FFFFFF",
            corner_radius=6,
            fg_color="transparent",
            height=0
        )
        self.toast_banner.pack(fill="x", padx=15, pady=(0, 6))

        # 3. Settings Card
        settings_frame = ctk.CTkFrame(self, corner_radius=10)
        settings_frame.pack(fill="x", padx=20, pady=5)

        # Row 1: Audio Quality & Metadata Toggles
        r1 = ctk.CTkFrame(settings_frame, fg_color="transparent")
        r1.pack(fill="x", padx=15, pady=(10, 6))

        q_label = ctk.CTkLabel(r1, text="Audio Quality:", font=ctk.CTkFont(weight="bold"))
        q_label.pack(side="left", padx=(0, 8))

        qualities = ["64", "128", "160", "192", "256", "320"]
        current_q = self.config.get("audio_quality", "160")
        if current_q not in qualities:
            current_q = "160"

        self.quality_menu = ctk.CTkOptionMenu(
            r1,
            values=[f"{q} kbps" for q in qualities],
            command=self.on_quality_change,
            width=115
        )
        self.quality_menu.set(f"{current_q} kbps")
        self.quality_menu.pack(side="left", padx=(0, 20))

        self.meta_checkbox = ctk.CTkCheckBox(
            r1,
            text="Embed Artist/Title Tags",
            command=self.on_meta_toggle
        )
        if self.config.get("embed_metadata", True):
            self.meta_checkbox.select()
        else:
            self.meta_checkbox.deselect()
        self.meta_checkbox.pack(side="left", padx=(0, 15))

        self.art_checkbox = ctk.CTkCheckBox(
            r1,
            text="Embed Cover Art",
            command=self.on_art_toggle
        )
        if self.config.get("embed_thumbnail", False):
            self.art_checkbox.select()
        else:
            self.art_checkbox.deselect()
        self.art_checkbox.pack(side="left")

        # Row 2: Download Folder
        r2 = ctk.CTkFrame(settings_frame, fg_color="transparent")
        r2.pack(fill="x", padx=15, pady=(4, 10))

        f_label = ctk.CTkLabel(r2, text="Save Folder:", font=ctk.CTkFont(weight="bold"))
        f_label.pack(side="left", padx=(0, 8))

        self.folder_entry = ctk.CTkEntry(r2)
        self.folder_entry.insert(0, self.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        self.folder_entry.configure(state="readonly")
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        browse_btn = ctk.CTkButton(r2, text="Browse...", width=85, command=self.on_browse_folder)
        browse_btn.pack(side="left")

        # 4. Manual URL Input Row
        manual_frame = ctk.CTkFrame(self, fg_color="transparent")
        manual_frame.pack(fill="x", padx=20, pady=4)

        self.url_entry = ctk.CTkEntry(
            manual_frame,
            placeholder_text="Or paste a YouTube / YouTube Music link manually here..."
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.url_entry.bind("<Return>", lambda e: self.on_manual_download())

        dl_btn = ctk.CTkButton(
            manual_frame,
            text="⬇ Download",
            width=110,
            fg_color="#CC0000",
            hover_color="#AA0000",
            font=ctk.CTkFont(weight="bold"),
            command=self.on_manual_download
        )
        dl_btn.pack(side="left")

        # 5. Live Download Progress & Status Card
        status_card = ctk.CTkFrame(self, corner_radius=10, fg_color="#1E1E1E")
        status_card.pack(fill="x", padx=20, pady=(6, 8))

        s_head = ctk.CTkFrame(status_card, fg_color="transparent")
        s_head.pack(fill="x", padx=15, pady=(12, 4))

        self.song_title_label = ctk.CTkLabel(
            s_head,
            text="Ready — Waiting for song...",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#FFFFFF"
        )
        self.song_title_label.pack(side="left")

        self.queue_badge = ctk.CTkLabel(
            s_head,
            text="Queue: 0 songs",
            font=ctk.CTkFont(size=12),
            text_color="#90CAF9"
        )
        self.queue_badge.pack(side="right")

        self.status_detail_label = ctk.CTkLabel(
            status_card,
            text="Status: Idle",
            font=ctk.CTkFont(size=12),
            text_color="#B0BEC5"
        )
        self.status_detail_label.pack(anchor="w", padx=15, pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(status_card, height=12, corner_radius=6)
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=15, pady=(0, 14))

        # 6. Recent Completed Downloads History
        history_frame = ctk.CTkFrame(self, corner_radius=10)
        history_frame.pack(fill="both", expand=True, padx=20, pady=(0, 15))

        h_head = ctk.CTkFrame(history_frame, fg_color="transparent")
        h_head.pack(fill="x", padx=15, pady=(8, 4))

        ctk.CTkLabel(
            h_head,
            text="Recent Downloads (Session):",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left")

        clear_hist_btn = ctk.CTkButton(
            h_head,
            text="Clear",
            width=50,
            height=20,
            fg_color="transparent",
            text_color="#90A4AE",
            hover_color="#37474F",
            command=self.on_clear_history
        )
        clear_hist_btn.pack(side="right")

        self.history_box = ctk.CTkScrollableFrame(history_frame, fg_color="transparent")
        self.history_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    # --- Dependency Scanning & Auto-Provisioning ---
    def check_dependencies_startup(self):
        ytdlp = get_ytdlp_path()
        ffmpeg = get_ffmpeg_path()

        missing = []
        if not ytdlp:
            missing.append("yt-dlp engine")
        if not ffmpeg:
            missing.append("FFmpeg audio converter")

        if missing:
            msg = f"⚙ First-Time Setup: Missing {', '.join(missing)} on this PC."
            self.setup_banner_label.configure(text=msg)
            self.setup_banner.pack(fill="x", padx=20, pady=(0, 6), before=self.clip_switch.master.master)
            return False
        else:
            self.setup_banner.pack_forget()
            self.current_engine_version = get_ytdlp_version() or "Available"
            self.engine_label.configure(
                text=f"Engine: yt-dlp v{self.current_engine_version}",
                text_color="#90CAF9"
            )
            return True

    def download_missing_components_auto(self):
        self.setup_dl_btn.configure(state="disabled", text="Installing...")
        threading.Thread(target=self._run_dependency_install_thread, daemon=True).start()

    def _run_dependency_install_thread(self):
        try:
            # 1. Check & Install yt-dlp.exe
            if not get_ytdlp_path():
                self.after(0, lambda: self.setup_banner_label.configure(text="Downloading yt-dlp engine (~22 MB)..."))
                ytdlp_dest = os.path.join(BIN_DIR, "yt-dlp.exe")
                req = urllib.request.Request(YTDLP_DOWNLOAD_URL, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(ytdlp_dest + ".tmp", "wb") as out_f:
                    total = int(resp.headers.get('content-length', 0))
                    downloaded = 0
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int((downloaded / total) * 100)
                            self.after(0, lambda p=pct: self.setup_dl_btn.configure(text=f"yt-dlp {p}%..."))

                if os.path.exists(ytdlp_dest):
                    try: os.remove(ytdlp_dest)
                    except Exception: pass
                os.replace(ytdlp_dest + ".tmp", ytdlp_dest)

            # 2. Check & Install ffmpeg.exe
            if not get_ffmpeg_path():
                self.after(0, lambda: self.setup_banner_label.configure(text="Downloading FFmpeg converter (~30 MB)..."))
                zip_path = os.path.join(BIN_DIR, "ffmpeg_portable.zip")
                req = urllib.request.Request(FFMPEG_DOWNLOAD_URL, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=90) as resp, open(zip_path, "wb") as out_f:
                    total = int(resp.headers.get('content-length', 0))
                    downloaded = 0
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int((downloaded / total) * 100)
                            self.after(0, lambda p=pct: self.setup_dl_btn.configure(text=f"FFmpeg {p}%..."))

                self.after(0, lambda: self.setup_banner_label.configure(text="Extracting ffmpeg.exe..."))
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    for member in zip_ref.namelist():
                        if member.endswith("ffmpeg.exe"):
                            with zip_ref.open(member) as source, open(os.path.join(BIN_DIR, "ffmpeg.exe"), "wb") as target:
                                shutil.copyfileobj(source, target)
                            break

                if os.path.exists(zip_path):
                    try: os.remove(zip_path)
                    except Exception: pass

            self.after(0, self._on_components_install_success)
        except Exception as e:
            self.after(0, lambda: self.setup_banner_label.configure(text=f"Setup error: {e}"))
            self.after(0, lambda: self.setup_dl_btn.configure(state="normal", text="Retry Setup"))

    def _on_components_install_success(self):
        self.setup_banner.pack_forget()
        self.current_engine_version = get_ytdlp_version() or "Ready"
        self.engine_label.configure(
            text=f"Engine: yt-dlp v{self.current_engine_version}",
            text_color="#90CAF9"
        )
        self.show_clipboard_toast("All components installed! OneTapTube is ready.")

    # Visual Clipboard Toast Banner Notification
    def show_clipboard_toast(self, text: str, is_success: bool = True):
        self.toast_banner.configure(
            text=f"  📋 {text}  ",
            fg_color="#2E7D32" if is_success else "#C62828",
            height=26
        )
        self.after(3500, self._hide_clipboard_toast)

    def _hide_clipboard_toast(self):
        self.toast_banner.configure(text="", fg_color="transparent", height=0)

    def add_history_entry(self, artist: str, title: str, quality: str):
        row = ctk.CTkFrame(self.history_box, fg_color="#263238", corner_radius=6)
        row.pack(fill="x", pady=2, padx=4)

        icon_label = ctk.CTkLabel(row, text="✓", font=ctk.CTkFont(size=13, weight="bold"), text_color="#66BB6A", width=25)
        icon_label.pack(side="left", padx=(6, 2))

        song_info = ctk.CTkLabel(row, text=f"{artist} - {title}", font=ctk.CTkFont(weight="bold"), anchor="w")
        song_info.pack(side="left", fill="x", expand=True, padx=4)

        tag = ctk.CTkLabel(row, text=f"{quality} kbps", font=ctk.CTkFont(size=11), text_color="#B0BEC5")
        tag.pack(side="right", padx=(4, 10))

    def on_clear_history(self):
        for widget in self.history_box.winfo_children():
            widget.destroy()

    def update_queue_badge(self):
        size = self.download_queue.qsize()
        self.queue_badge.configure(text=f"Queue: {size} song{'s' if size != 1 else ''}")

    # Settings Event Handlers
    def on_quality_change(self, val: str):
        kbps = val.replace(" kbps", "").strip()
        self.config["audio_quality"] = kbps
        self.save_config()

    def on_meta_toggle(self):
        enabled = bool(self.meta_checkbox.get())
        self.config["embed_metadata"] = enabled
        self.save_config()

    def on_art_toggle(self):
        enabled = bool(self.art_checkbox.get())
        self.config["embed_thumbnail"] = enabled
        self.save_config()

    def on_clip_toggle(self):
        enabled = bool(self.clip_switch.get())
        self.config["auto_clipboard"] = enabled
        self.save_config()
        if enabled:
            self.clip_status_badge.configure(text="● ACTIVE (Listening)", text_color="#81C784")
        else:
            self.clip_status_badge.configure(text="○ PAUSED", text_color="#9E9E9E")

    def on_browse_folder(self):
        selected = filedialog.askdirectory(initialdir=self.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        if selected:
            norm = os.path.normpath(selected)
            self.config["download_dir"] = norm
            self.save_config()
            self.folder_entry.configure(state="normal")
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, norm)
            self.folder_entry.configure(state="readonly")

    def on_open_folder(self):
        target = self.config.get("download_dir", DEFAULT_DOWNLOAD_DIR)
        os.makedirs(target, exist_ok=True)
        try:
            os.startfile(target)
        except Exception:
            pass

    def on_manual_download(self):
        raw = self.url_entry.get().strip()
        if not raw:
            return
        matches = YOUTUBE_REGEX.findall(raw)
        if matches:
            for vid in matches:
                self.queue_video(vid, source="Manual")
            self.url_entry.delete(0, "end")
        else:
            self.show_clipboard_toast("Please enter a valid YouTube or YouTube Music song link", is_success=False)

    def queue_video(self, video_id: str, source: str = "Clipboard"):
        with self.lock:
            if video_id not in self.currently_queued:
                self.currently_queued.add(video_id)
                self.download_queue.put(video_id)
                self.after(0, self.update_queue_badge)
                if source == "Clipboard":
                    self.after(0, lambda: self.show_clipboard_toast(f"Song copied & queued: https://music.youtube.com/watch?v={video_id}"))

    # Clipboard Monitoring: Triggers ONLY on actual clipboard change
    def clipboard_monitor(self):
        last_clipboard_text = ""
        try:
            last_clipboard_text = self.clipboard_get().strip()
        except Exception:
            pass

        while self.running:
            if self.config.get("auto_clipboard", True):
                try:
                    clip = ""
                    try:
                        clip = self.clipboard_get().strip()
                    except Exception:
                        pass

                    if clip and clip != last_clipboard_text:
                        last_clipboard_text = clip
                        matches = YOUTUBE_REGEX.findall(clip)
                        for vid in matches:
                            self.queue_video(vid, source="Clipboard")
                except Exception:
                    pass
            time.sleep(0.2)

    # Background Download Processing
    def download_worker(self):
        while self.running:
            try:
                video_id = self.download_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self.process_download(video_id)
            finally:
                with self.lock:
                    self.currently_queued.discard(video_id)
                self.download_queue.task_done()
                self.after(0, self.update_queue_badge)

    def process_download(self, video_id: str):
        target_dir = self.config.get("download_dir", DEFAULT_DOWNLOAD_DIR)
        quality = self.config.get("audio_quality", "160")
        embed_meta = self.config.get("embed_metadata", True)
        embed_art = self.config.get("embed_thumbnail", False)

        ytdlp_bin = get_ytdlp_path()
        ffmpeg_bin = get_ffmpeg_path()

        if not ytdlp_bin or not ffmpeg_bin:
            self.after(0, self.check_dependencies_startup)
            self.after(0, lambda: self.status_detail_label.configure(
                text="Status: Missing yt-dlp or FFmpeg. Please click 'Auto-Install' above."
            ))
            return

        url = f"https://music.youtube.com/watch?v={video_id}"

        self.after(0, lambda: self.song_title_label.configure(text=f"🎵 Song ID: {video_id}"))
        self.after(0, lambda: self.status_detail_label.configure(text="Status: Fetching song details & starting download..."))
        self.after(0, lambda: self.progress_bar.set(0.08))

        os.makedirs(target_dir, exist_ok=True)

        # Build yt-dlp command
        out_template = os.path.join(target_dir, "%(artist,creator,channel,uploader)s - %(title)s.%(ext)s")
        cmd = [
            ytdlp_bin,
            "--ffmpeg-location", os.path.dirname(ffmpeg_bin),
            "--no-simulate",
            "--progress",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", f"{quality}K",
            "--windows-filenames",
            "--no-playlist",
            "-o", out_template,
            "--newline",
            "--progress-template", "download:PROGRESS:%(progress._percent_str)s",
            "--print", "before_dl:METADATA:%(artist,creator,channel,uploader)s|||%(title)s"
        ]

        if embed_meta:
            cmd.append("--embed-metadata")
        if embed_art:
            cmd.append("--embed-thumbnail")

        cmd.append(url)

        # Run invisibly in background
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

        artist_name = "Unknown Artist"
        song_title = "Unknown Title"
        last_error_line = ""

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                if line.startswith("METADATA:"):
                    raw_meta = line.replace("METADATA:", "").strip()
                    parts = raw_meta.split("|||")
                    if len(parts) >= 2:
                        artist_name = parts[0].strip() or "Unknown Artist"
                        song_title = parts[1].strip() or "Unknown Title"
                        self.after(0, lambda a=artist_name, t=song_title: self.song_title_label.configure(text=f"🎵 {a} - {t}"))

                elif line.startswith("PROGRESS:"):
                    pct_str = line.replace("PROGRESS:", "").replace("%", "").strip()
                    try:
                        pct = float(pct_str) / 100.0
                        pct_clamped = min(max(pct, 0.05), 0.95)
                        self.after(0, lambda p=pct_clamped: self.progress_bar.set(p))
                        self.after(0, lambda ps=pct_str: self.status_detail_label.configure(
                            text=f"Status: Downloading audio stream ({ps}%)..."
                        ))
                    except ValueError:
                        pass

                elif "[ExtractAudio]" in line or "[Metadata]" in line or "[ThumbnailsConvertor]" in line:
                    self.after(0, lambda: self.progress_bar.set(0.96))
                    self.after(0, lambda: self.status_detail_label.configure(text="Status: Converting audio to MP3 & tagging..."))

                elif "ERROR:" in line or "error:" in line:
                    last_error_line = line

            proc.wait()

            if proc.returncode == 0:
                self.after(0, lambda a=artist_name, t=song_title: self.song_title_label.configure(text=f"🎵 {a} - {t}"))
                self.after(0, lambda: self.status_detail_label.configure(text=f"Status: ✓ Successfully Saved ({quality} kbps MP3)"))
                self.after(0, lambda: self.progress_bar.set(1.0))
                self.after(0, lambda a=artist_name, t=song_title, q=quality: self.add_history_entry(a, t, q))
            else:
                err_text = f"Status: ✕ Download failed. {last_error_line}" if last_error_line else "Status: ✕ Download failed. Check link or connection."
                self.after(0, lambda et=err_text: self.status_detail_label.configure(text=et))
                self.after(0, lambda: self.progress_bar.set(0.0))

        except Exception as e:
            self.after(0, lambda err=str(e): self.status_detail_label.configure(text=f"Status: ✕ Error: {err}"))
            self.after(0, lambda: self.progress_bar.set(0.0))

    # --- Standalone & Environment-Aware Update Management ---
    def fetch_latest_release(self) -> str:
        # Check GitHub official release tag
        try:
            req = urllib.request.Request(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                tag = data.get("tag_name", "")
                return tag.lstrip("v")
        except Exception:
            pass

        # Fallback to PyPI check
        try:
            req = urllib.request.Request(
                "https://pypi.org/pypi/yt-dlp/json",
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get("info", {}).get("version")
        except Exception:
            return None

    def check_for_updates_background(self):
        latest = self.fetch_latest_release()
        current = get_ytdlp_version()
        if current:
            self.current_engine_version = current

        if latest and latest != self.current_engine_version and self.current_engine_version != "Not Installed":
            self.latest_engine_version = latest
            self.after(0, lambda: self.update_btn.configure(
                text=f"🔔 Update Available ({latest})",
                fg_color="#F57C00",
                hover_color="#E65100"
            ))
        elif self.current_engine_version != "Not Installed":
            self.after(0, lambda: self.update_btn.configure(
                text="✓ Up to Date",
                fg_color="#37474F",
                hover_color="#455A64"
            ))

    def on_check_update_clicked(self):
        self.update_btn.configure(text="Checking...", state="disabled")
        threading.Thread(target=self._run_check_and_prompt_update, daemon=True).start()

    def _run_check_and_prompt_update(self):
        latest = self.fetch_latest_release()
        current = get_ytdlp_version()
        if current:
            self.current_engine_version = current

        self.after(0, lambda: self.update_btn.configure(state="normal"))

        if latest and latest != self.current_engine_version:
            self.latest_engine_version = latest
            self.after(0, self._show_update_modal)
        else:
            self.after(0, lambda: self.update_btn.configure(text="✓ Up to Date", fg_color="#37474F"))
            self.after(0, lambda: self.show_clipboard_toast(f"yt-dlp engine is on the latest version ({self.current_engine_version})!"))

    def _show_update_modal(self):
        modal = ctk.CTkToplevel(self)
        modal.title("Update Available")
        modal.geometry("440x240")
        modal.resizable(False, False)
        modal.attributes('-topmost', True)

        ctk.CTkLabel(
            modal,
            text="🔔 yt-dlp Engine Update Available!",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            modal,
            text=f"Current version: v{self.current_engine_version}\nLatest version: v{self.latest_engine_version}\n\nUpdating fixes YouTube extraction and throttled speeds.",
            justify="center",
            font=ctk.CTkFont(size=12)
        ).pack(pady=4)

        btn_box = ctk.CTkFrame(modal, fg_color="transparent")
        btn_box.pack(pady=(15, 10))

        def perform_update():
            modal.destroy()
            self.update_btn.configure(text="Updating...", state="disabled")
            self.status_detail_label.configure(text="Status: Downloading latest yt-dlp engine...")
            threading.Thread(target=self._execute_standalone_update, daemon=True).start()

        ctk.CTkButton(
            btn_box,
            text="Update Now",
            fg_color="#2E7D32",
            hover_color="#1B5E20",
            font=ctk.CTkFont(weight="bold"),
            command=perform_update
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            btn_box,
            text="Later",
            fg_color="#455A64",
            hover_color="#37474F",
            command=modal.destroy
        ).pack(side="left", padx=10)

    def _execute_standalone_update(self):
        # Download official latest standalone binary into bin/yt-dlp.exe directly
        target_binary = os.path.join(BIN_DIR, "yt-dlp.exe")
        temp_binary = target_binary + ".new"

        try:
            req = urllib.request.Request(YTDLP_DOWNLOAD_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp, open(temp_binary, "wb") as out_f:
                shutil.copyfileobj(resp, out_f)

            if os.path.exists(target_binary):
                try:
                    os.remove(target_binary)
                except Exception:
                    # Rename old if locked
                    old_bin = target_binary + ".old"
                    if os.path.exists(old_bin):
                        try: os.remove(old_bin)
                        except Exception: pass
                    os.rename(target_binary, old_bin)

            os.replace(temp_binary, target_binary)

            # Re-read version
            new_version = get_ytdlp_version(target_binary) or self.latest_engine_version
            self.current_engine_version = new_version

            self.after(0, lambda: self.engine_label.configure(
                text=f"Engine: yt-dlp v{self.current_engine_version}",
                text_color="#90CAF9"
            ))
            self.after(0, lambda: self.update_btn.configure(
                text="✓ Up to Date",
                fg_color="#37474F",
                hover_color="#455A64",
                state="normal"
            ))
            self.after(0, lambda: self.status_detail_label.configure(text=f"Status: ✓ Successfully updated to yt-dlp v{new_version}!"))
            self.after(0, lambda: self.show_clipboard_toast(f"Engine updated to v{new_version}!"))
        except Exception as e:
            if os.path.exists(temp_binary):
                try: os.remove(temp_binary)
                except Exception: pass
            self.after(0, lambda: self.status_detail_label.configure(text=f"Status: Update error: {e}"))
            self.after(0, lambda: self.update_btn.configure(text="🔄 Check Updates", state="normal"))

    def on_close(self):
        self.running = False
        self.destroy()
        sys.exit(0)

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = MusicDownloaderApp()
    app.mainloop()
