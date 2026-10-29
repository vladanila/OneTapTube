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
import ctypes
import webbrowser
import tkinter as tk
from tkinter import filedialog
import unicodedata
from PIL import Image
import pystray

GITHUB_REPO_URL = "https://github.com/vladanila/OneTapTube"

# 1. Base Application Directory (Guaranteed to be project folder, never Temp/_MEI)
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
DEFAULT_DOWNLOAD_DIR = os.path.join(APP_DIR, "downloads")
BIN_DIR = os.path.join(APP_DIR, "bin")
ICON_ICO_PATH = os.path.join(APP_DIR, "icon.ico")
if not os.path.exists(ICON_ICO_PATH) and getattr(sys, '_MEIPASS', None):
    ICON_ICO_PATH = os.path.join(sys._MEIPASS, "icon.ico")

APP_ICON_PNG_PATH = os.path.join(APP_DIR, "app_icon.png")
if not os.path.exists(APP_ICON_PNG_PATH) and getattr(sys, '_MEIPASS', None):
    APP_ICON_PNG_PATH = os.path.join(sys._MEIPASS, "app_icon.png")

os.makedirs(BIN_DIR, exist_ok=True)
os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)

# Add BIN_DIR to PATH so any sub-process can find binaries
if BIN_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = BIN_DIR + os.pathsep + os.environ.get("PATH", "")

import customtkinter as ctk

# Appearance setup
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Regular Expressions (Bulletproof matching for modern YouTube share URLs, shorts, music, and playlists)
YOUTUBE_VIDEO_REGEX = re.compile(
    r'(?:https?:\/\/)?(?:[a-zA-Z0-9_-]+\.)?youtu(?:be\.com\/(?:watch\?.*?\bv=|(?:shorts|live|embed)\/)|(?:\.be\/))([a-zA-Z0-9_-]{11})'
)
YOUTUBE_PLAYLIST_REGEX = re.compile(
    r'(?:https?:\/\/)?(?:[a-zA-Z0-9_-]+\.)?youtu(?:be\.com|\.be).*?[?&]list=([a-zA-Z0-9_-]+)'
)

YTDLP_DOWNLOAD_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_DOWNLOAD_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


# --- Native Windows Clipboard Access (Thread-Safe & Immune to Tkinter GUI Locking) ---
def get_native_clipboard_text() -> str:
    """Reads text directly from the Windows OS clipboard without touching Tkinter GUI threads."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = ctypes.c_bool
        user32.GetClipboardData.argtypes = [ctypes.c_uint]
        user32.GetClipboardData.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_bool

        CF_UNICODETEXT = 13
        if user32.OpenClipboard(None):
            try:
                h_mem = user32.GetClipboardData(CF_UNICODETEXT)
                if h_mem:
                    p_mem = kernel32.GlobalLock(h_mem)
                    if p_mem:
                        try:
                            val = ctypes.c_wchar_p(p_mem).value
                            return (val or "").strip()
                        finally:
                            kernel32.GlobalUnlock(h_mem)
            finally:
                user32.CloseClipboard()
    except Exception:
        pass
    return ""


# --- Native Windows Audio Player (Hybrid MCI + PresentationCore) ---
class WindowsAudioPlayer:
    """Ultra-lightweight native Windows audio player supporting MP3, M4A, AAC, and FLAC."""
    def __init__(self):
        self.winmm = ctypes.windll.winmm
        self.alias = "onetaptube_preview"
        self.is_playing = False
        self.current_path = None
        self.ps_proc = None

    def play(self, file_path: str) -> bool:
        self.stop()
        if not file_path or not os.path.exists(file_path):
            return False

        ext = os.path.splitext(file_path)[1].lower()

        # If MP3, first attempt ultra-fast native MCI
        if ext == ".mp3":
            try:
                buf = ctypes.create_unicode_buffer(1024)
                ctypes.windll.kernel32.GetShortPathNameW(file_path, buf, 1024)
                short_path = buf.value or file_path

                cmd_open = f'open "{short_path}" type mpegvideo alias {self.alias}'
                res = self.winmm.mciSendStringW(cmd_open, None, 0, None)
                if res == 0:
                    self.winmm.mciSendStringW(f'play {self.alias}', None, 0, None)
                    self.is_playing = True
                    self.current_path = file_path
                    return True
            except Exception:
                pass

        # For M4A/FLAC/AAC (or MP3 fallback if MCI fails), use Windows PresentationCore MediaPlayer
        try:
            clean_path = os.path.abspath(file_path).replace("\\", "/").replace("'", "''")
            ps_cmd = (
                "Add-Type -AssemblyName WindowsBase; "
                "Add-Type -AssemblyName PresentationCore; "
                "$p = New-Object System.Windows.Media.MediaPlayer; "
                f"$p.Open([System.Uri]'{clean_path}'); "
                "$p.Play(); "
                "Start-Sleep -Seconds 600"
            )
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            self.ps_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.is_playing = True
            self.current_path = file_path
            return True
        except Exception:
            return False

    def stop(self):
        try:
            self.winmm.mciSendStringW(f'stop {self.alias}', None, 0, None)
            self.winmm.mciSendStringW(f'close {self.alias}', None, 0, None)
        except Exception:
            pass
        if self.ps_proc:
            try:
                self.ps_proc.terminate()
            except Exception:
                pass
            self.ps_proc = None
        self.is_playing = False
        self.current_path = None


# --- Modern Interactive ToolTip (Hover Help Box) ---
class ModernToolTip:
    """Sleek hover tooltip that appears when hovering over settings/text and vanishes when the mouse leaves."""
    def __init__(self, widget, text: str, delay_ms: int = 250):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window = None
        self.after_id = None
        self.hide_after_id = None
        self.last_x = None
        self.last_y = None
        self._bind_events(self.widget)

    def _bind_events(self, target):
        for evt in ('<Enter>', '<Motion>'):
            try:
                target.bind(evt, self.schedule_show, add='+')
            except Exception:
                pass
        for evt in ('<Leave>', '<FocusOut>'):
            try:
                target.bind(evt, self.check_and_hide, add='+')
            except Exception:
                pass
        try:
            target.bind('<ButtonPress>', lambda e: self.hide_tip(immediate=True), add='+')
        except Exception:
            pass

        # Also bind internal CTk component widgets (e.g. checkbox text label and canvas)
        for child_name in ('_text_label', '_canvas', '_entry', '_label'):
            if hasattr(target, child_name):
                child = getattr(target, child_name)
                if child:
                    for evt in ('<Enter>', '<Motion>'):
                        try:
                            child.bind(evt, self.schedule_show, add='+')
                        except Exception:
                            pass
                    for evt in ('<Leave>', '<FocusOut>'):
                        try:
                            child.bind(evt, self.check_and_hide, add='+')
                        except Exception:
                            pass
                    try:
                        child.bind('<ButtonPress>', lambda e: self.hide_tip(immediate=True), add='+')
                    except Exception:
                        pass

    def schedule_show(self, event=None):
        if self.hide_after_id:
            try:
                self.widget.after_cancel(self.hide_after_id)
            except Exception:
                pass
            self.hide_after_id = None

        if event:
            self.last_x = event.x_root
            self.last_y = event.y_root

        if not self.tip_window and not self.after_id:
            self.after_id = self.widget.after(self.delay_ms, self.show_tip)

    def cancel_schedule(self):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def show_tip(self):
        self.after_id = None
        if self.tip_window or not self.widget.winfo_exists():
            return
        try:
            if not self.widget.winfo_viewable():
                return
        except Exception:
            return
        try:
            if self.last_x is not None and self.last_y is not None:
                x = self.last_x + 10
                y = self.last_y + 18
            else:
                x = self.widget.winfo_rootx() + 10
                y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4

            # Screen boundary clamp so tooltip never appears off-screen
            sw = self.widget.winfo_screenwidth()
            sh = self.widget.winfo_screenheight()
            if x + 280 > sw:
                x = max(10, sw - 290)
            if y + 80 > sh:
                y = max(10, (self.last_y or y) - 80)

            self.tip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.attributes('-topmost', True)

            container = ctk.CTkFrame(
                tw,
                fg_color='#1E272E',
                border_color='#485460',
                border_width=1,
                corner_radius=6
            )
            container.pack(fill='both', expand=True)

            label = ctk.CTkLabel(
                container,
                text=self.text,
                font=ctk.CTkFont(size=11),
                text_color='#ECEFF1',
                justify='left',
                wraplength=260
            )
            label.pack(padx=10, pady=6)
            tw.wm_geometry(f'+{x}+{y}')
        except Exception:
            self.hide_tip(immediate=True)

    def check_and_hide(self, event=None):
        self.cancel_schedule()
        if self.tip_window and not self.hide_after_id:
            self.hide_after_id = self.widget.after(80, self._destroy_tip)

    def _destroy_tip(self):
        self.hide_after_id = None
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None

    def hide_tip(self, immediate=False):
        self.cancel_schedule()
        if self.hide_after_id:
            try:
                self.widget.after_cancel(self.hide_after_id)
            except Exception:
                pass
            self.hide_after_id = None
        if immediate:
            self._destroy_tip()
        else:
            self.check_and_hide()


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
        self.geometry("760x810")
        self.minsize(720, 750)
        self.configure(fg_color="#0B0F19")

        # Load Application Logo Image
        self.app_logo_img = None
        if os.path.exists(APP_ICON_PNG_PATH):
            try:
                logo_pil = Image.open(APP_ICON_PNG_PATH)
                self.app_logo_img = ctk.CTkImage(light_image=logo_pil, dark_image=logo_pil, size=(42, 42))
            except Exception:
                pass

        # Set Window Taskbar Icon
        if os.path.exists(ICON_ICO_PATH):
            try:
                self.iconbitmap(ICON_ICO_PATH)
            except Exception:
                pass

        # Audio Player Instance
        self.audio_player = WindowsAudioPlayer()
        self.active_play_btn = None

        # Engine Version Tracking
        self.current_engine_version = get_ytdlp_version() or "Not Installed"
        self.latest_engine_version = None

        # Load Configuration
        self.config = self.load_config()

        # Threading & Concurrency
        self.download_queue = queue.Queue()
        self.currently_queued = set()
        self.lock = threading.Lock()
        self.running = True
        self.active_workers_count = 0
        self.active_display_worker = None

        # Build UI
        self.create_widgets()

        # Check Dependencies (yt-dlp & FFmpeg) on startup
        self.check_dependencies_startup()

        # Start Background Download Worker Threads Pool (Multi-threaded)
        self.init_download_workers()

        # Start Background Clipboard Poller Thread
        self.clipboard_thread = threading.Thread(target=self.clipboard_monitor, daemon=True)
        self.clipboard_thread.start()

        # Setup System Tray Icon
        self.tray_icon = None
        self.init_system_tray()

        # Background update check on startup
        threading.Thread(target=self.check_for_updates_background, daemon=True).start()

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_config(self):
        defaults = {
            "download_dir": DEFAULT_DOWNLOAD_DIR,
            "audio_format": "mp3",
            "audio_quality": "160",
            "embed_metadata": True,
            "embed_thumbnail": False,
            "auto_clipboard": True,
            "skip_existing": True,
            "minimize_to_tray": True,
            "concurrent_downloads": "3"
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

    def init_download_workers(self):
        """Initializes concurrent background download workers using max turbo performance (3 workers)."""
        num_workers = 3
        for i in range(num_workers):
            t = threading.Thread(target=self.download_worker, args=(i + 1,), daemon=True)
            t.start()

    # --- System Tray Setup ---
    def init_system_tray(self):
        try:
            if os.path.exists(ICON_ICO_PATH):
                tray_image = Image.open(ICON_ICO_PATH)
            else:
                tray_image = Image.new('RGB', (64, 64), color=(30, 136, 229))

            menu = pystray.Menu(
                pystray.MenuItem("OneTapTube v1.3.0", lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open OneTapTube", self.restore_from_tray, default=True),
                pystray.MenuItem("Open Downloads Folder", lambda: self.after(0, self.on_open_folder)),
                pystray.MenuItem("Visit GitHub Repository", self.open_github_repo),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit Completely", self.quit_app)
            )

            self.tray_icon = pystray.Icon("OneTapTube", tray_image, "OneTapTube - 1-Click Music Downloader", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            self.tray_icon = None

    def restore_from_tray(self):
        self.after(0, self._do_restore)

    def _do_restore(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def show_tray_notification(self, title: str, message: str):
        if self.tray_icon:
            try:
                self.tray_icon.notify(message, title)
            except Exception:
                pass

    def create_widgets(self):
        # 1. Header Frame
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        # App Icon inside the app header
        if self.app_logo_img:
            logo_label = ctk.CTkLabel(title_box, text="", image=self.app_logo_img)
            logo_label.pack(side="left", padx=(0, 12))

        brand_text_box = ctk.CTkFrame(title_box, fg_color="transparent")
        brand_text_box.pack(side="left")

        title_label = ctk.CTkLabel(
            brand_text_box,
            text="OneTapTube",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#F8FAFC"
        )
        title_label.pack(anchor="w")

        v_text = f"yt-dlp v{self.current_engine_version} • Ready" if self.current_engine_version != "Not Installed" else "Engine: Not Installed"
        self.engine_label = ctk.CTkLabel(
            brand_text_box,
            text=v_text,
            font=ctk.CTkFont(size=11),
            text_color="#38BDF8" if self.current_engine_version != "Not Installed" else "#F59E0B"
        )
        self.engine_label.pack(anchor="w")

        # Top Right Actions (GitHub Link, Open Folder & Update Button)
        actions_box = ctk.CTkFrame(header, fg_color="transparent")
        actions_box.pack(side="right")

        github_btn = ctk.CTkButton(
            actions_box,
            text="⭐ GitHub",
            width=88,
            height=32,
            fg_color="#1E293B",
            border_color="#334155",
            border_width=1,
            hover_color="#334155",
            text_color="#F8FAFC",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self.open_github_repo
        )
        github_btn.pack(side="left", padx=(0, 10))
        ModernToolTip(github_btn, "Visit OneTapTube on GitHub (Repository & Releases)")

        open_folder_btn = ctk.CTkButton(
            actions_box,
            text="📂 Downloads",
            width=110,
            height=32,
            fg_color="#1E293B",
            border_color="#334155",
            border_width=1,
            hover_color="#334155",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self.on_open_folder
        )
        open_folder_btn.pack(side="left", padx=(0, 10))

        self.update_btn = ctk.CTkButton(
            actions_box,
            text="🔄 Check Updates",
            width=135,
            height=32,
            fg_color="#0284C7",
            hover_color="#0369A1",
            font=ctk.CTkFont(size=12, weight="bold"),
            corner_radius=8,
            command=self.on_check_update_clicked
        )
        self.update_btn.pack(side="left")

        # First-Time Setup Banner (Visible ONLY if yt-dlp or FFmpeg is missing on a new PC)
        self.setup_banner = ctk.CTkFrame(self, fg_color="#7F1D1D", border_color="#991B1B", border_width=1, corner_radius=10)
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
        clip_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#111827", border_width=1, border_color="#1F2937")
        clip_card.pack(fill="x", padx=20, pady=(0, 8))

        c_top = ctk.CTkFrame(clip_card, fg_color="transparent")
        c_top.pack(fill="x", padx=16, pady=(12, 4))

        self.clip_switch = ctk.CTkSwitch(
            c_top,
            text="Auto-Download from Clipboard",
            command=self.on_clip_toggle,
            font=ctk.CTkFont(size=14, weight="bold"),
            progress_color="#10B981",
            button_color="#34D399",
            button_hover_color="#6EE7B7"
        )
        if self.config.get("auto_clipboard", True):
            self.clip_switch.select()
        else:
            self.clip_switch.deselect()
        self.clip_switch.pack(side="left")

        is_active = self.config.get("auto_clipboard", True)
        self.clip_status_badge = ctk.CTkLabel(
            c_top,
            text="● ACTIVE (Auto-Capture)" if is_active else "○ PAUSED",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#064E3B" if is_active else "#1E293B",
            text_color="#34D399" if is_active else "#64748B",
            corner_radius=8,
            padx=10,
            pady=3
        )
        self.clip_status_badge.pack(side="right")

        # Instruction Text
        hint_text = ctk.CTkLabel(
            clip_card,
            text="💡 Copy any song or album link (Ctrl + C) on YouTube / YouTube Music. OneTapTube captures & saves it instantly!",
            font=ctk.CTkFont(size=11),
            text_color="#94A3B8",
            justify="left"
        )
        hint_text.pack(anchor="w", padx=16, pady=(0, 8))

        # Dynamic Notification Banner (Lights up green when a song is copied)
        self.toast_banner = ctk.CTkLabel(
            clip_card,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FFFFFF",
            corner_radius=8,
            fg_color="transparent",
            height=0
        )
        self.toast_banner.pack(fill="x", padx=16, pady=(0, 8))

        # 3. Settings Card
        settings_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="#111827", border_width=1, border_color="#1F2937")
        settings_frame.pack(fill="x", padx=20, pady=(0, 8))

        # Row 1: Format Selector & Bitrate (Default: MP3)
        r1 = ctk.CTkFrame(settings_frame, fg_color="transparent")
        r1.pack(fill="x", padx=16, pady=(12, 6))

        fmt_label = ctk.CTkLabel(r1, text="Format:", font=ctk.CTkFont(weight="bold"), text_color="#E2E8F0")
        fmt_label.pack(side="left", padx=(0, 8))

        current_fmt = self.config.get("audio_format", "mp3")
        fmt_display_map = {
            "mp3": "MP3 (Universal)",
            "m4a": "⚡ M4A (Lightning Fast)",
            "flac": "FLAC (Lossless)"
        }

        self.format_menu = ctk.CTkOptionMenu(
            r1,
            values=["MP3 (Universal)", "⚡ M4A (Lightning Fast)", "FLAC (Lossless)"],
            command=self.on_format_change,
            width=165,
            height=28,
            fg_color="#1E293B",
            button_color="#334155",
            button_hover_color="#475569",
            corner_radius=8
        )
        self.format_menu.set(fmt_display_map.get(current_fmt, "MP3 (Universal)"))
        self.format_menu.pack(side="left", padx=(0, 18))

        self.q_label = ctk.CTkLabel(r1, text="Bitrate:", font=ctk.CTkFont(weight="bold"), text_color="#E2E8F0")
        self.q_label.pack(side="left", padx=(0, 8))

        qualities = ["64", "128", "160", "192", "256", "320"]
        current_q = self.config.get("audio_quality", "160")
        if current_q not in qualities:
            current_q = "160"

        self.quality_menu = ctk.CTkOptionMenu(
            r1,
            values=[f"{q} kbps" for q in qualities],
            command=self.on_quality_change,
            width=100,
            height=28,
            fg_color="#1E293B",
            button_color="#334155",
            button_hover_color="#475569",
            corner_radius=8
        )
        self.quality_menu.set(f"{current_q} kbps")
        self.quality_menu.pack(side="left", padx=(0, 15))

        if current_fmt in ["m4a", "flac"]:
            self.quality_menu.configure(state="disabled")
            self.q_label.configure(text_color="#64748B")
        else:
            self.quality_menu.configure(state="normal")
            self.q_label.configure(text_color="#E2E8F0")

        # Row 2: Tag, Artwork & Auto-Skip Checkboxes
        r2 = ctk.CTkFrame(settings_frame, fg_color="transparent")
        r2.pack(fill="x", padx=16, pady=(4, 6))

        self.meta_checkbox = ctk.CTkCheckBox(
            r2,
            text="Embed Tags",
            command=self.on_meta_toggle,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            border_color="#475569",
            corner_radius=6,
            text_color="#E2E8F0"
        )
        if self.config.get("embed_metadata", True):
            self.meta_checkbox.select()
        else:
            self.meta_checkbox.deselect()
        self.meta_checkbox.pack(side="left", padx=(0, 20))

        self.art_checkbox = ctk.CTkCheckBox(
            r2,
            text="Embed Cover Art",
            command=self.on_art_toggle,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            border_color="#475569",
            corner_radius=6,
            text_color="#E2E8F0"
        )
        if self.config.get("embed_thumbnail", False):
            self.art_checkbox.select()
        else:
            self.art_checkbox.deselect()
        self.art_checkbox.pack(side="left", padx=(0, 20))

        self.skip_checkbox = ctk.CTkCheckBox(
            r2,
            text="Auto-Skip Existing Songs",
            command=self.on_skip_toggle,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
            border_color="#475569",
            corner_radius=6,
            text_color="#E2E8F0"
        )
        if self.config.get("skip_existing", True):
            self.skip_checkbox.select()
        else:
            self.skip_checkbox.deselect()
        self.skip_checkbox.pack(side="left")

        # Row 3: Download Folder
        r3 = ctk.CTkFrame(settings_frame, fg_color="transparent")
        r3.pack(fill="x", padx=16, pady=(4, 12))

        f_label = ctk.CTkLabel(r3, text="Save Folder:", font=ctk.CTkFont(weight="bold"), text_color="#E2E8F0")
        f_label.pack(side="left", padx=(0, 8))

        self.folder_entry = ctk.CTkEntry(
            r3,
            fg_color="#0B0F19",
            border_color="#1E293B",
            border_width=1,
            corner_radius=8,
            height=28
        )
        self.folder_entry.insert(0, self.config.get("download_dir", DEFAULT_DOWNLOAD_DIR))
        self.folder_entry.configure(state="readonly")
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        browse_btn = ctk.CTkButton(
            r3,
            text="Browse...",
            width=85,
            height=28,
            fg_color="#1E293B",
            border_color="#334155",
            border_width=1,
            hover_color="#334155",
            corner_radius=8,
            command=self.on_browse_folder
        )
        browse_btn.pack(side="left")

        # Interactive Hover Help Tooltips
        ModernToolTip(
            self.meta_checkbox,
            "Adds artist, track title, album, and release date metadata directly into the audio file (ID3 tags)."
        )
        ModernToolTip(
            self.art_checkbox,
            "Embeds high-resolution album cover artwork into the audio file so it appears on phones, cars, and media players."
        )
        ModernToolTip(
            self.skip_checkbox,
            "Checks your save folder and skips downloading songs that already exist, saving time and internet data."
        )
        ModernToolTip(
            self.format_menu,
            "Audio Format:\n• MP3: Universal compatibility for phones and car audio.\n• ⚡ M4A: Lightning-fast 1-sec download (untouched YouTube stream).\n• FLAC: High-fidelity lossless audio."
        )
        ModernToolTip(
            fmt_label,
            "Audio Format:\n• MP3: Universal compatibility for phones and car audio.\n• ⚡ M4A: Lightning-fast 1-sec download (untouched YouTube stream).\n• FLAC: High-fidelity lossless audio."
        )
        ModernToolTip(
            self.quality_menu,
            "MP3 Bitrate (Audio Quality):\n160 kbps matches YouTube's source audio without wasted file size. 320 kbps offers maximum MP3 fidelity."
        )
        ModernToolTip(
            self.q_label,
            "MP3 Bitrate (Audio Quality):\n160 kbps matches YouTube's source audio without wasted file size. 320 kbps offers maximum MP3 fidelity."
        )
        ModernToolTip(
            self.clip_switch,
            "Automatic Clipboard Monitor:\nWhen active, copying (Ctrl + C) any song or playlist link in YouTube Music instantly queues the download in the background."
        )

        # 4. Manual URL Input Row
        manual_frame = ctk.CTkFrame(self, fg_color="transparent")
        manual_frame.pack(fill="x", padx=20, pady=(0, 8))

        self.url_entry = ctk.CTkEntry(
            manual_frame,
            placeholder_text="🔗 Paste a YouTube or YouTube Music song / album link here...",
            fg_color="#111827",
            border_color="#1F2937",
            border_width=1,
            text_color="#F8FAFC",
            placeholder_text_color="#64748B",
            corner_radius=10,
            height=38
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.url_entry.bind("<Return>", lambda e: self.on_manual_download())

        dl_btn = ctk.CTkButton(
            manual_frame,
            text="⬇ Download",
            width=120,
            height=38,
            fg_color="#E11D48",
            hover_color="#BE123C",
            font=ctk.CTkFont(size=13, weight="bold"),
            corner_radius=10,
            command=self.on_manual_download
        )
        dl_btn.pack(side="left")

        # 5. Live Download Progress & Status Card
        status_card = ctk.CTkFrame(self, corner_radius=12, fg_color="#111827", border_width=1, border_color="#1F2937")
        status_card.pack(fill="x", padx=20, pady=(0, 8))

        s_head = ctk.CTkFrame(status_card, fg_color="transparent")
        s_head.pack(fill="x", padx=16, pady=(12, 4))

        self.song_title_label = ctk.CTkLabel(
            s_head,
            text="Ready — Waiting for song...",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#F8FAFC"
        )
        self.song_title_label.pack(side="left")

        self.queue_badge = ctk.CTkLabel(
            s_head,
            text="Queue: 0 songs",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1E293B",
            text_color="#38BDF8",
            corner_radius=8,
            padx=10,
            pady=3
        )
        self.queue_badge.pack(side="right")

        self.status_detail_label = ctk.CTkLabel(
            status_card,
            text="Status: Idle",
            font=ctk.CTkFont(size=12),
            text_color="#94A3B8"
        )
        self.status_detail_label.pack(anchor="w", padx=16, pady=(0, 6))

        self.progress_bar = ctk.CTkProgressBar(
            status_card,
            height=10,
            corner_radius=5,
            progress_color="#2563EB",
            fg_color="#1E293B"
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=16, pady=(0, 14))

        # 6. Recent Completed Downloads History with In-App Preview Mini Player
        history_frame = ctk.CTkFrame(self, corner_radius=12, fg_color="#111827", border_width=1, border_color="#1F2937")
        history_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        h_head = ctk.CTkFrame(history_frame, fg_color="transparent")
        h_head.pack(fill="x", padx=16, pady=(10, 4))

        ctk.CTkLabel(
            h_head,
            text="Recent Downloads & In-App Preview:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F8FAFC"
        ).pack(side="left")

        clear_hist_btn = ctk.CTkButton(
            h_head,
            text="Clear",
            width=50,
            height=22,
            fg_color="transparent",
            text_color="#64748B",
            hover_color="#1E293B",
            corner_radius=6,
            command=self.on_clear_history
        )
        clear_hist_btn.pack(side="right")

        self.history_box = ctk.CTkScrollableFrame(history_frame, fg_color="transparent")
        self.history_box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.empty_history_label = ctk.CTkLabel(
            self.history_box,
            text="🎵 No songs downloaded yet.\nCopy any song link (Ctrl + C) on YouTube Music to get started!",
            font=ctk.CTkFont(size=12),
            text_color="#64748B",
            justify="center"
        )
        self.empty_history_label.pack(pady=40)

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
                text=f"yt-dlp v{self.current_engine_version} • Ready",
                text_color="#38BDF8"
            )
            return True

    def download_missing_components_auto(self):
        self.setup_dl_btn.configure(state="disabled", text="Installing...")
        threading.Thread(target=self._run_dependency_install_thread, daemon=True).start()

    def _run_dependency_install_thread(self):
        try:
            # 1. Check & Install yt-dlp.exe
            if not get_ytdlp_path():
                self.after(0, lambda: self.setup_banner_label.configure(text="Downloading yt-dlp engine (~23 MB)..."))
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
            text=f"yt-dlp v{self.current_engine_version} • Ready",
            text_color="#38BDF8"
        )
        self.show_clipboard_toast("All components installed! OneTapTube is ready.")

    # Visual Clipboard Toast Banner Notification
    def show_clipboard_toast(self, text: str, is_success: bool = True, on_click=None):
        self.toast_banner.configure(
            text=f"  ✓ {text}  " if is_success else f"  ✕ {text}  ",
            fg_color="#064E3B" if is_success else "#7F1D1D",
            text_color="#34D399" if is_success else "#FCA5A5",
            height=28
        )
        try:
            self.toast_banner.unbind("<Button-1>")
        except Exception:
            pass
        if on_click:
            self.toast_banner.bind("<Button-1>", lambda e: on_click())
            try:
                self.toast_banner.configure(cursor="hand2")
            except Exception:
                pass
        else:
            try:
                self.toast_banner.configure(cursor="")
            except Exception:
                pass
        self.after(3500, self._hide_clipboard_toast)

    def _hide_clipboard_toast(self):
        try:
            self.toast_banner.unbind("<Button-1>")
        except Exception:
            pass
        self.toast_banner.configure(text="", fg_color="transparent", height=0)
        try:
            self.toast_banner.configure(cursor="")
        except Exception:
            pass

    # --- Recent Downloads with Audio Preview Player ---
    def add_history_entry(self, artist: str, title: str, tag_text: str, file_path: str = None, is_skipped: bool = False):
        if hasattr(self, 'empty_history_label') and self.empty_history_label and self.empty_history_label.winfo_exists():
            self.empty_history_label.destroy()
            self.empty_history_label = None

        row = ctk.CTkFrame(self.history_box, fg_color="#1E293B", border_color="#334155", border_width=1, corner_radius=8)
        row.pack(fill="x", pady=3, padx=4)

        status_icon = "⏩" if is_skipped else "✓"
        icon_color = "#F59E0B" if is_skipped else "#10B981"
        icon_label = ctk.CTkLabel(
            row,
            text=status_icon,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=icon_color,
            width=26
        )
        icon_label.pack(side="left", padx=(8, 4))

        song_info = ctk.CTkLabel(
            row,
            text=f"{artist} - {title}",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#F8FAFC",
            anchor="w"
        )
        song_info.pack(side="left", fill="x", expand=True, padx=4)

        status_display = "Already Exists" if is_skipped else tag_text
        tag = ctk.CTkLabel(
            row,
            text=status_display,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#0F172A",
            text_color="#94A3B8",
            corner_radius=6,
            padx=8,
            pady=2
        )
        tag.pack(side="left", padx=(4, 8))

        # Action Buttons on Right
        if file_path and os.path.exists(file_path):
            # 1. Reveal in File Explorer button
            open_btn = ctk.CTkButton(
                row,
                text="📂",
                width=30,
                height=24,
                font=ctk.CTkFont(size=12),
                fg_color="#334155",
                hover_color="#475569",
                corner_radius=6,
                command=lambda fp=file_path: self.reveal_file(fp)
            )
            ModernToolTip(open_btn, "Open and highlight file in Windows File Explorer")
            open_btn.pack(side="right", padx=(2, 8))

            # 2. Play / Stop Preview Button
            play_btn = ctk.CTkButton(
                row,
                text="▶ Preview",
                width=75,
                height=24,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color="#059669",
                hover_color="#047857",
                corner_radius=6
            )

            def toggle_play(fp=file_path, b=play_btn):
                if self.audio_player.is_playing and self.audio_player.current_path == fp:
                    self.audio_player.stop()
                    b.configure(text="▶ Preview", fg_color="#059669", hover_color="#047857")
                    self.active_play_btn = None
                else:
                    if self.active_play_btn:
                        try:
                            self.active_play_btn.configure(text="▶ Preview", fg_color="#059669", hover_color="#047857")
                        except Exception:
                            pass
                    success = self.audio_player.play(fp)
                    if success:
                        b.configure(text="⏹ Stop", fg_color="#E11D48", hover_color="#BE123C")
                        self.active_play_btn = b
                    else:
                        b.configure(text="✕ Error", fg_color="#475569")

            play_btn.configure(command=toggle_play)
            play_btn.pack(side="right", padx=(4, 2))

    def reveal_file(self, file_path: str):
        if not file_path or not os.path.exists(file_path):
            self.on_open_folder()
            return
        try:
            norm = os.path.normpath(file_path)
            subprocess.Popen(f'explorer /select,"{norm}"')
        except Exception:
            try:
                os.startfile(os.path.dirname(file_path))
            except Exception:
                pass

    def on_clear_history(self):
        self.audio_player.stop()
        self.active_play_btn = None
        for widget in self.history_box.winfo_children():
            widget.destroy()
        self.empty_history_label = ctk.CTkLabel(
            self.history_box,
            text="🎵 No songs downloaded yet.\nCopy any song link (Ctrl + C) on YouTube Music to get started!",
            font=ctk.CTkFont(size=12),
            text_color="#64748B",
            justify="center"
        )
        self.empty_history_label.pack(pady=40)

    def update_queue_badge(self):
        size = self.download_queue.qsize()
        active_txt = f" ({self.active_workers_count} downloading)" if self.active_workers_count > 0 else ""
        self.queue_badge.configure(text=f"Queue: {size} song{'s' if size != 1 else ''}{active_txt}")

    # Settings Event Handlers
    def on_format_change(self, val: str):
        if "M4A" in val:
            self.config["audio_format"] = "m4a"
            self.quality_menu.configure(state="disabled")
            self.q_label.configure(text_color="#64748B")
            self.show_clipboard_toast("Switched to Lightning M4A (Untouched 1-second AAC stream)")
        elif "FLAC" in val:
            self.config["audio_format"] = "flac"
            self.quality_menu.configure(state="disabled")
            self.q_label.configure(text_color="#64748B")
            self.show_clipboard_toast("Switched to FLAC (Lossless audio container)")
        else:
            self.config["audio_format"] = "mp3"
            self.quality_menu.configure(state="normal")
            self.q_label.configure(text_color="#E2E8F0")
            self.show_clipboard_toast("Switched to MP3 (Custom bitrate)")
        self.save_config()

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

    def on_skip_toggle(self):
        enabled = bool(self.skip_checkbox.get())
        self.config["skip_existing"] = enabled
        self.save_config()

    def on_clip_toggle(self):
        enabled = bool(self.clip_switch.get())
        self.config["auto_clipboard"] = enabled
        self.save_config()
        if enabled:
            self.clip_status_badge.configure(
                text="● ACTIVE (Auto-Capture)",
                fg_color="#064E3B",
                text_color="#34D399"
            )
        else:
            self.clip_status_badge.configure(
                text="○ PAUSED",
                fg_color="#1E293B",
                text_color="#64748B"
            )

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

    def open_github_repo(self):
        try:
            webbrowser.open(GITHUB_REPO_URL)
        except Exception:
            pass

    # --- Clipboard & URL Processing with Playlist Detection ---
    def on_manual_download(self):
        raw = self.url_entry.get().strip()
        if not raw:
            return
        self.handle_incoming_url(raw, source="Manual")
        self.url_entry.delete(0, "end")

    def handle_incoming_url(self, text: str, source: str = "Clipboard"):
        """Checks if URL is a single song or dedicated playlist, ensuring seamless 1-click single-song downloads."""
        playlist_match = YOUTUBE_PLAYLIST_REGEX.search(text)
        video_matches = YOUTUBE_VIDEO_REGEX.findall(text)

        # 1. If link contains a specific song/video ID (e.g. watch?v=... or watch?v=...&list=...)
        # Prioritize downloading that single song immediately without any modal popups or interruptions.
        if video_matches:
            playlist_id = playlist_match.group(1) if playlist_match else None
            for vid in video_matches:
                self.queue_video(vid, source=source, album_id=playlist_id)
            return

        # 2. Pure playlist / album URL (e.g. youtube.com/playlist?list=... with NO single video ID)
        # The user explicitly copied the whole playlist, so open the playlist batch downloader.
        if playlist_match:
            playlist_id = playlist_match.group(1)
            self.prompt_playlist_download(playlist_id, single_vid=None)
            return

        if source == "Manual":
            self.show_clipboard_toast("Please enter a valid YouTube or YouTube Music song or playlist link", is_success=False)

    def prompt_playlist_download(self, playlist_id: str, single_vid: str = None):
        """Displays interactive modal to download full album / playlist."""
        modal = ctk.CTkToplevel(self)
        modal.title("Playlist / Album Detected")
        modal.geometry("460x220")
        modal.resizable(False, False)
        modal.attributes('-topmost', True)

        ctk.CTkLabel(
            modal,
            text="🎵 Playlist / Album Detected!",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(20, 6))

        info_label = ctk.CTkLabel(
            modal,
            text="Fetching playlist tracklist details...",
            font=ctk.CTkFont(size=12),
            text_color="#B0BEC5"
        )
        info_label.pack(pady=4)

        btn_box = ctk.CTkFrame(modal, fg_color="transparent")
        btn_box.pack(pady=(16, 10))

        def fetch_tracks():
            ytdlp_bin = get_ytdlp_path()
            if not ytdlp_bin:
                modal.destroy()
                return

            cmd = [
                ytdlp_bin,
                "--flat-playlist",
                "--no-warnings",
                "--quiet",
                "--print", "%(id)s|||%(title)s",
                f"https://www.youtube.com/playlist?list={playlist_id}"
            ]

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

            tracks = []
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                for line in proc.stdout:
                    line = line.strip()
                    if line and "|||" in line:
                        parts = line.split("|||")
                        vid = parts[0].strip()
                        tit = parts[1].strip() if len(parts) > 1 else "Unknown Track"
                        if len(vid) == 11:
                            tracks.append((vid, tit))
                proc.wait()
            except Exception:
                pass

            def update_ui():
                try:
                    if not modal.winfo_exists():
                        return
                except Exception:
                    return

                if not tracks:
                    info_label.configure(text="Could not load playlist tracks or playlist is empty.")
                    return

                info_label.configure(text=f"Found {len(tracks)} songs in this playlist/album.\nWould you like to download all tracks?")

                def download_all():
                    modal.destroy()
                    for vid, tit in tracks:
                        self.queue_video(vid, source="Playlist", title_hint=tit)
                    self.show_clipboard_toast(f"Queued {len(tracks)} songs from playlist!")
                    self.show_tray_notification("OneTapTube Playlist", f"Queued {len(tracks)} songs for download.")

                ctk.CTkButton(
                    btn_box,
                    text=f"⬇ Download All ({len(tracks)})",
                    fg_color="#2E7D32",
                    hover_color="#1B5E20",
                    font=ctk.CTkFont(weight="bold"),
                    command=download_all
                ).pack(side="left", padx=8)

                if single_vid:
                    def download_single():
                        modal.destroy()
                        self.queue_video(single_vid, source="Playlist")

                    ctk.CTkButton(
                        btn_box,
                        text="Download Single Song",
                        fg_color="#1E88E5",
                        hover_color="#1565C0",
                        font=ctk.CTkFont(weight="bold"),
                        command=download_single
                    ).pack(side="left", padx=8)

                ctk.CTkButton(
                    btn_box,
                    text="Cancel",
                    fg_color="#455A64",
                    hover_color="#37474F",
                    command=modal.destroy
                ).pack(side="left", padx=8)

            self.after(0, update_ui)

        threading.Thread(target=fetch_tracks, daemon=True).start()

    def queue_video(self, video_id: str, source: str = "Clipboard", title_hint: str = None, album_id: str = None):
        with self.lock:
            if video_id not in self.currently_queued:
                self.currently_queued.add(video_id)
                self.download_queue.put((video_id, title_hint))
                self.after(0, self.update_queue_badge)
                if source == "Clipboard":
                    if album_id and not album_id.startswith("RD"):
                        self.after(0, lambda a_id=album_id: self.show_clipboard_toast(
                            "Song queued! • Album detected (click here to download full album)",
                            on_click=lambda: self.prompt_playlist_download(a_id)
                        ))
                    else:
                        self.after(0, lambda: self.show_clipboard_toast(f"Song queued: https://music.youtube.com/watch?v={video_id}"))

    # Clipboard Monitoring: Thread-Safe Native Windows Hook (Zero GUI Thread Contention)
    def clipboard_monitor(self):
        last_clipboard_text = ""
        try:
            last_clipboard_text = get_native_clipboard_text() or self.clipboard_get().strip()
        except Exception:
            pass

        while self.running:
            if self.config.get("auto_clipboard", True):
                try:
                    clip = get_native_clipboard_text()
                    if not clip:
                        try:
                            clip = self.clipboard_get().strip()
                        except Exception:
                            clip = ""

                    if clip and clip != last_clipboard_text:
                        last_clipboard_text = clip
                        self.after(0, lambda c=clip: self.handle_incoming_url(c, source="Clipboard"))
                except Exception:
                    pass
            time.sleep(0.2)

    # --- Background Download Processing (Multi-Threaded Pool) ---
    def download_worker(self, worker_id: int):
        while self.running:
            try:
                video_id, title_hint = self.download_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            with self.lock:
                self.active_workers_count += 1
            self.after(0, self.update_queue_badge)

            try:
                self.process_download(video_id, worker_id, title_hint)
            finally:
                with self.lock:
                    self.currently_queued.discard(video_id)
                    self.active_workers_count = max(0, self.active_workers_count - 1)
                self.download_queue.task_done()
                self.after(0, self.update_queue_badge)

    def process_download(self, video_id: str, worker_id: int, title_hint: str = None):
        target_dir = self.config.get("download_dir", DEFAULT_DOWNLOAD_DIR)
        quality = self.config.get("audio_quality", "160")
        fmt_setting = self.config.get("audio_format", "mp3").lower()
        embed_meta = self.config.get("embed_metadata", True)
        embed_art = self.config.get("embed_thumbnail", False)
        skip_existing = self.config.get("skip_existing", True)

        if "m4a" in fmt_setting or "aac" in fmt_setting:
            target_format = "m4a"
            tag_label = "M4A (Lightning)"
        elif "flac" in fmt_setting:
            target_format = "flac"
            tag_label = "FLAC (Lossless)"
        else:
            target_format = "mp3"
            tag_label = f"{quality} kbps MP3"

        ytdlp_bin = get_ytdlp_path()
        ffmpeg_bin = get_ffmpeg_path()

        if not ytdlp_bin or not ffmpeg_bin:
            self.after(0, self.check_dependencies_startup)
            self.after(0, lambda: self.status_detail_label.configure(
                text="Status: Missing yt-dlp or FFmpeg. Please click 'Auto-Install' above."
            ))
            return

        url = f"https://music.youtube.com/watch?v={video_id}"
        display_name = title_hint if title_hint else f"Song ID: {video_id}"

        # Assign leader worker to smoothly drive single-song progress bar without flicker
        with self.lock:
            if self.active_display_worker is None:
                self.active_display_worker = worker_id
            is_leader = (self.active_display_worker == worker_id)

        if is_leader:
            self.after(0, lambda: self.song_title_label.configure(text=f"🎵 {display_name}"))
            self.after(0, lambda: self.status_detail_label.configure(text=f"Status: Downloading ({tag_label})..."))
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
            "--audio-format", target_format,
            "--sponsorblock-remove", "music_offtopic,sponsor",
            "--windows-filenames",
            "--no-playlist",
            "-o", out_template,
            "--newline",
            "--progress-template", "download:PROGRESS:%(progress._percent_str)s",
            "--print", "before_dl:METADATA:%(artist,creator,channel,uploader)s|||%(title)s",
            "--print", "after_move:SAVED_PATH:%(filepath)s"
        ]

        if target_format == "mp3":
            cmd.extend(["--audio-quality", f"{quality}K"])

        if skip_existing:
            cmd.extend(["--no-overwrites", "--no-post-overwrites"])
        else:
            cmd.append("--force-overwrites")

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
        song_title = title_hint or "Unknown Title"
        last_error_line = ""
        is_already_downloaded = False
        saved_file_path = None
        start_time = time.time()

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

                if line.startswith("SAVED_PATH:"):
                    p = line.replace("SAVED_PATH:", "").strip()
                    if os.path.exists(p) and os.path.getsize(p) > 1000:
                        saved_file_path = p

                elif line.startswith("METADATA:"):
                    raw_meta = line.replace("METADATA:", "").strip()
                    parts = raw_meta.split("|||")
                    if len(parts) >= 2:
                        artist_name = parts[0].strip() or "Unknown Artist"
                        song_title = parts[1].strip() or "Unknown Title"
                        if self.active_display_worker == worker_id:
                            self.after(0, lambda a=artist_name, t=song_title: self.song_title_label.configure(text=f"🎵 {a} - {t}"))

                elif line.startswith("PROGRESS:"):
                    pct_str = line.replace("PROGRESS:", "").replace("%", "").strip()
                    try:
                        pct = float(pct_str) / 100.0
                        pct_clamped = min(max(pct, 0.05), 0.95)
                        if self.active_display_worker == worker_id:
                            self.after(0, lambda p=pct_clamped: self.progress_bar.set(p))
                            self.after(0, lambda ps=pct_str: self.status_detail_label.configure(
                                text=f"Status: Downloading stream ({ps}%)..."
                            ))
                    except ValueError:
                        pass

                elif "[SponsorBlock]" in line:
                    if "removing" in line.lower() or "found" in line.lower():
                        if self.active_display_worker == worker_id:
                            self.after(0, lambda: self.status_detail_label.configure(text="Status: Trimming non-music intro/skit (SponsorBlock)..."))

                elif "[ExtractAudio]" in line or "[Metadata]" in line or "[ThumbnailsConvertor]" in line or "[ModifyChapters]" in line:
                    if self.active_display_worker == worker_id:
                        self.after(0, lambda: self.progress_bar.set(0.96))
                        self.after(0, lambda: self.status_detail_label.configure(text="Status: Packaging audio & tags..."))

                elif "has already been downloaded" in line.lower() or "already exists" in line.lower():
                    is_already_downloaded = True
                    match = re.search(r'\[download\]\s+(.*?)\s+has already been downloaded', line, re.IGNORECASE)
                    if match:
                        extracted = match.group(1).strip('"\'')
                        if os.path.exists(extracted):
                            saved_file_path = extracted

                elif "ERROR:" in line or "error:" in line:
                    last_error_line = line

            proc.wait()

            # Find output file if not captured directly via SAVED_PATH
            ext = target_format
            if not saved_file_path:
                expected_filename = f"{artist_name} - {song_title}.{ext}"
                candidate_path = os.path.join(target_dir, expected_filename)
                if os.path.exists(candidate_path):
                    saved_file_path = candidate_path
                else:
                    try:
                        clean_t = "".join(c for c in song_title if c.isalnum()).lower()
                        for f in os.listdir(target_dir):
                            if f.endswith(f".{ext}"):
                                clean_f = "".join(c for c in f if c.isalnum()).lower()
                                if clean_t and clean_t in clean_f:
                                    saved_file_path = os.path.join(target_dir, f)
                                    break
                        if not saved_file_path:
                            recent_files = [
                                os.path.join(target_dir, f)
                                for f in os.listdir(target_dir)
                                if f.endswith(f".{ext}") and os.path.getmtime(os.path.join(target_dir, f)) >= start_time - 2
                            ]
                            if recent_files:
                                saved_file_path = max(recent_files, key=os.path.getmtime)
                    except Exception:
                        pass

            # Relinquish leader worker so next active download can update progress bar cleanly
            with self.lock:
                was_leader = (self.active_display_worker == worker_id)
                if was_leader:
                    self.active_display_worker = None

            is_file_valid = bool(saved_file_path and os.path.exists(saved_file_path) and os.path.getsize(saved_file_path) > 1000)
            is_success = (proc.returncode == 0 or is_already_downloaded or is_file_valid)

            if is_success:
                if is_already_downloaded:
                    status_text = "Status: ⏩ Already exists in folder (Skipped)"
                    if was_leader or self.active_workers_count <= 1:
                        self.after(0, lambda a=artist_name, t=song_title: self.song_title_label.configure(text=f"🎵 {a} - {t}"))
                        self.after(0, lambda st=status_text: self.status_detail_label.configure(text=st))
                        self.after(0, lambda: self.progress_bar.set(1.0))
                    self.after(0, lambda a=artist_name, t=song_title, fp=saved_file_path: self.add_history_entry(a, t, tag_label, fp, is_skipped=True))
                else:
                    if was_leader or self.active_workers_count <= 1:
                        self.after(0, lambda a=artist_name, t=song_title: self.song_title_label.configure(text=f"🎵 {a} - {t}"))
                        self.after(0, lambda: self.status_detail_label.configure(text=f"Status: ✓ Successfully Saved ({tag_label})"))
                        self.after(0, lambda: self.progress_bar.set(1.0))
                    self.after(0, lambda a=artist_name, t=song_title, fp=saved_file_path: self.add_history_entry(a, t, tag_label, fp, is_skipped=False))
                    self.show_tray_notification("OneTapTube Download Complete", f"✓ Saved: {artist_name} - {song_title}")
            else:
                if was_leader or self.active_workers_count <= 1:
                    err_text = f"Status: ✕ Download failed. {last_error_line}" if last_error_line else "Status: ✕ Download failed. Check link or connection."
                    self.after(0, lambda et=err_text: self.status_detail_label.configure(text=et))
                    self.after(0, lambda: self.progress_bar.set(0.0))

        except Exception as e:
            with self.lock:
                if self.active_display_worker == worker_id:
                    self.active_display_worker = None
            self.after(0, lambda err=str(e): self.status_detail_label.configure(text=f"Status: ✕ Error: {err}"))
            self.after(0, lambda: self.progress_bar.set(0.0))

    # --- Standalone & Environment-Aware Update Management ---
    def fetch_latest_release(self) -> str:
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
                text=f"🔔 Update ({latest})",
                fg_color="#EA580C",
                hover_color="#C2410C",
                text_color="#FFFFFF"
            ))
        elif self.current_engine_version != "Not Installed":
            self.after(0, lambda: self.update_btn.configure(
                text="✓ Up to Date",
                fg_color="#1E293B",
                border_color="#334155",
                border_width=1,
                hover_color="#334155",
                text_color="#94A3B8"
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
            self.after(0, lambda: self.update_btn.configure(
                text="✓ Up to Date",
                fg_color="#1E293B",
                border_color="#334155",
                border_width=1,
                hover_color="#334155",
                text_color="#94A3B8"
            ))
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
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_box,
            text="GitHub Page",
            fg_color="#1E293B",
            border_color="#334155",
            border_width=1,
            hover_color="#334155",
            command=self.open_github_repo
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_box,
            text="Later",
            fg_color="#455A64",
            hover_color="#37474F",
            command=modal.destroy
        ).pack(side="left", padx=6)

    def _execute_standalone_update(self):
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
                    old_bin = target_binary + ".old"
                    if os.path.exists(old_bin):
                        try: os.remove(old_bin)
                        except Exception: pass
                    os.rename(target_binary, old_bin)

            os.replace(temp_binary, target_binary)

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

    # --- Window Close & Tray Minimization ---
    def on_close(self):
        if self.tray_icon:
            self.withdraw()
            self.show_tray_notification("OneTapTube Minimized", "OneTapTube is running in the background and listening for copied links.")
        else:
            self.quit_app()

    def quit_app(self):
        self.running = False
        try:
            self.audio_player.stop()
        except Exception:
            pass
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.destroy()
        sys.exit(0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = MusicDownloaderApp()
    app.mainloop()
