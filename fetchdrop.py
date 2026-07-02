"""
FetchDrop – Social Media Downloader
Aplikasi pengunduh media dari platform sosial (YouTube, TikTok, Instagram, X/Twitter).

Dikompilasi dengan Nuitka untuk distribusi Windows (Mode Onefile).
Target: Python 3.12.10
"""

from __future__ import annotations

import atexit
import base64
import json
import logging
import math as _math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable

import customtkinter as ctk

# ── Type Aliases (Python 3.12+) ───────────────────────────────────────────────
type JsonDict = dict[str, Any]
type MediaInfo = dict[str, Any]

# ── OS Detection & Windows API ────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    import msvcrt

# ── Nuitka Compatibility ──────────────────────────────────────────────────────
def _resource_path(*parts: str) -> Path:
    """
    Mendapatkan path absolut ke aset bawaan (icon, dll).
    Pada Nuitka --onefile, __file__ mengarah ke direktori ekstraksi sementara.
    """
    base_dir = Path(__file__).resolve().parent
    return base_dir.joinpath(*parts)

# ── Color & Theme Configuration ───────────────────────────────────────────────
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

COLOR_BG = "#0A0A0C"
COLOR_SIDEBAR = "#111113"
COLOR_CARD = "#16161A"
COLOR_ACCENT = "#E50914"
COLOR_ACCENT_HOVER = "#B80710"
COLOR_BORDER = "#222226"
COLOR_TEXT_MAIN = "#F3F4F6"
COLOR_TEXT_MUTED = "#9CA3AF"
COLOR_TEXT_DIM = "#3A3A40"
COLOR_TEXT_ERROR = "#EF4444"
COLOR_TEXT_SUCCESS = "#22C55E"
COLOR_BTN_DISABLED_BG = "#1E1E22"
COLOR_BTN_DISABLED_FG = "#55555F"
COLOR_HOVER_BG = "#1D1D21"
COLOR_PROGRESS_BG = "#1F1F24"

FONT_FAMILY = "Segoe UI"

# ── Animation Engine ──────────────────────────────────────────────────────────
ANIM_FRAME_MS = 14
ANIM_SIDEBAR_FRAMES = 22
ANIM_FADE_TEXT_FRAMES = 14
ANIM_STATUS_FRAMES = 8
ANIM_HOVER_FRAMES = 6
ANIM_HEADER_FADE_OUT = 5
ANIM_HEADER_FADE_IN = 9
ANIM_COUNTER_FRAMES = 14

def _lerp_color(c1: str, c2: str, t: float) -> str:
    """Interpolasi halus antara dua string hex color (t ∈ [0.0, 1.0])."""
    def _parse(c: str) -> tuple[int, int, int]:
        h = c.lstrip("#")
        if len(h) == 3:
            h = h[0] * 2 + h[1] * 2 + h[2] * 2
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    t = max(0.0, min(1.0, t))
    r1, g1, b1 = _parse(c1)
    r2, g2, b2 = _parse(c2)
    return "#{:02x}{:02x}{:02x}".format(
        round(r1 + (r2 - r1) * t),
        round(g1 + (g2 - g1) * t),
        round(b1 + (b2 - b1) * t),
    )

def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3

def _ease_in_out_sine(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return -(_math.cos(_math.pi * t) - 1.0) / 2.0

def _ease_out_quint(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 5

# ── Paths & Engine Dependencies ───────────────────────────────────────────────
DEPENDENCY_DIR = Path.home() / ".fetchdrop_engine"
CONFIG_FILE = DEPENDENCY_DIR / ".fetchdrop_config.json"
YTDLP_EXE = DEPENDENCY_DIR / "yt-dlp.exe"
LOG_FILE = DEPENDENCY_DIR / "fetchdrop.log"
LOCK_FILE = DEPENDENCY_DIR / "fetchdrop.lock"

_LOCK_HANDLE: Any | None = None

def _release_single_instance() -> None:
    """Melepaskan lock file ketika aplikasi diakhiri dengan aman."""
    global _LOCK_HANDLE
    if _LOCK_HANDLE:
        try:
            _LOCK_HANDLE.close()
            LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass

atexit.register(_release_single_instance)

def _ensure_single_instance() -> bool:
    global _LOCK_HANDLE
    if not IS_WINDOWS:
        return True

    DEPENDENCY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _LOCK_HANDLE = open(LOCK_FILE, "w")
        msvcrt.locking(_LOCK_HANDLE.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False

def _show_instance_warning() -> None:
    msg = "Aplikasi FetchDrop sudah berjalan di latar belakang."
    title = "FetchDrop"
    if IS_WINDOWS:
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, title, 0x30)
            return
        except Exception:
            pass
    print(f"[{title}] {msg}")

# ── Logging Setup ─────────────────────────────────────────────────────────────
def _setup_logging() -> None:
    DEPENDENCY_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=256 * 1024, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        handlers=[handler],
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

_setup_logging()
log = logging.getLogger("fetchdrop")

CREATE_NO_WINDOW = (
    subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
)

# ── Persistent Configuration ──────────────────────────────────────────────────
def load_config() -> JsonDict:
    defaults: JsonDict = {
        "download_folder": str(Path.home() / "Downloads"),
        "last_quality": "Best",
        "last_container": "Format Asli",
        "last_mode": "video",
        "download_count": 0,
    }

    if not CONFIG_FILE.exists():
        return defaults

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            defaults.update(data)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.warning(f"Gagal memuat konfigurasi: {exc}")

    if not Path(defaults["download_folder"]).is_dir():
        defaults["download_folder"] = str(Path.home() / "Downloads")

    return defaults

def save_config(cfg: JsonDict) -> bool:
    try:
        DEPENDENCY_DIR.mkdir(parents=True, exist_ok=True)
        temp_file = CONFIG_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        temp_file.replace(CONFIG_FILE)
        return True
    except OSError as exc:
        log.error(f"Gagal menyimpan konfigurasi: {exc}")
        return False

def format_folder_label(path: str) -> str:
    try:
        home = Path.home()
        path_obj = Path(path).resolve()
        try:
            rel = path_obj.relative_to(home)
            display = f"~/{rel.as_posix()}"
        except ValueError:
            display = path_obj.as_posix()
    except (ValueError, OSError):
        display = path

    if len(display) > 48:
        parts = display.replace("\\", "/").split("/")
        if len(parts) >= 3:
            display = ".../" + "/".join(parts[-2:])
        elif len(parts) == 2:
            display = ".../" + parts[-1]
        else:
            display = "..." + display[-45:]
    return f"📁 {display}"

# ── Media Validation & Format Mapping ─────────────────────────────────────────
_PLATFORM_PATTERNS = {
    "youtube": re.compile(
        r"(https?://)?(www\.)?(youtube\.com/(watch|shorts|playlist|embed|live)|youtu\.be/|music\.youtube\.com/watch)",
        re.IGNORECASE,
    ),
    "tiktok": re.compile(
        r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/(@[\w.]+/video/\d{10,}|v/\d{10,}|t/\w{8,}|\w{6,}/?)",
        re.IGNORECASE,
    ),
    "instagram": re.compile(
        r"(https?://)?(www\.)?instagram\.com/(p|reel|tv)/[\w-]+",
        re.IGNORECASE,
    ),
    "x": re.compile(
        r"(https?://)?(www\.)?(twitter\.com|x\.com)/\w+/status/\d+",
        re.IGNORECASE,
    ),
}

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "x": "X / Twitter",
}

VIDEO_QUALITY_OPTIONS = [
    "Best", "4K (2160p)", "2K (1440p)", "1080p", "720p", "480p", "360p"
]
AUDIO_QUALITY_OPTIONS = ["320 kbps", "192 kbps", "128 kbps"]

_RES_FORMAT_MAP = {
    "Best": "bv*+ba/b",
    "360p": "bv*[height<=360]+ba/b[height<=360]/bv*[height<=360]/b[height<=360]",
    "480p": "bv*[height<=480]+ba/b[height<=480]/bv*[height<=480]/b[height<=480]",
    "720p": "bv*[height<=720]+ba/b[height<=720]/bv*[height<=720]/b[height<=720]",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]/bv*[height<=1080]/b[height<=1080]",
    "2K (1440p)": "bv*[height<=1440]+ba/b[height<=1440]/bv*[height<=1440]/b[height<=1440]",
    "4K (2160p)": "bv*[height<=2160]+ba/b[height<=2160]/bv*[height<=2160]/b[height<=2160]",
}
_AUDIO_QUALITY_MAP = {"320 kbps": "320k", "192 kbps": "192k", "128 kbps": "128k"}

_RES_MAP_LABELS = [
    (2160, "4K (2160p)"), (1440, "2K (1440p)"), (1080, "1080p"),
    (720, "720p"), (480, "480p"), (360, "360p"),
]

def detect_platform(url: str) -> str | None:
    for name, pattern in _PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return None

def is_valid_url(url: str) -> bool:
    return detect_platform(url) is not None

def format_size(bytes_value: Any) -> str:
    if not bytes_value or bytes_value in ("NA", "0", "N/A"):
        return "N/A"
    try:
        b = float(bytes_value)
        if b <= 0:
            return "N/A"
        units = ("B", "KB", "MB", "GB", "TB")
        for unit in units[:-1]:
            if b < 1024.0:
                return f"{b:.1f} {unit}"
            b /= 1024.0
        return f"{b:.1f} {units[-1]}"
    except (ValueError, TypeError):
        return "N/A"

def _parse_ytdlp_size(size_str: str) -> float | None:
    """Parse string ukuran dari yt-dlp menjadi bytes (case-insensitive)."""
    size_upper = size_str.strip().upper()
    # Kunci dalam uppercase agar pencocokan tidak bergantung pada kapitalisasi
    # (regex penangkap memakai re.IGNORECASE sehingga hasil tangkapan bisa mixed-case)
    unit_map = {
        "TIB": 1024 ** 4, "GIB": 1024 ** 3, "MIB": 1024 ** 2, "KIB": 1024,
        "TB": 1000 ** 4, "GB": 1000 ** 3, "MB": 1000 ** 2, "KB": 1000, "B": 1,
    }
    for unit, multiplier in unit_map.items():
        if size_upper.endswith(unit):
            try:
                return float(size_upper[: -len(unit)]) * multiplier
            except ValueError:
                return None
    try:
        return float(size_str)
    except ValueError:
        return None

def shorten_codec(codec: str | None, max_len: int = 10) -> str:
    if not codec or codec.lower() in ("none", "", "null"):
        return "N/A"
    return codec.split(".")[0][:max_len]

# ── Windows Toast Notifications ───────────────────────────────────────────────
def send_toast(title: str, message: str, icon_path: Path | None = None) -> None:
    """Mengirim native toast notification Windows menggunakan PowerShell."""
    def _notify() -> None:
        try:
            template_type = "ToastText02"
            icon_injection = ""

            if icon_path and icon_path.exists():
                template_type = "ToastImageAndText02"
                icon_uri = f"file:///{icon_path.absolute().as_posix()}"
                icon_injection = (
                    f"$template.GetElementsByTagName('image')[0]."
                    f"SetAttribute('src', '{icon_uri}') | Out-Null;"
                )

            def _ps_xml_escape(text: str) -> str:
                return (
                    text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("'", "''")
                )

            escaped_title = _ps_xml_escape(title)
            escaped_message = _ps_xml_escape(message)

            ps_script = (
                "[Windows.UI.Notifications.ToastNotificationManager, "
                "Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
                f"$template = [Windows.UI.Notifications.ToastNotificationManager]::"
                f"GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::{template_type});"
                f"$template.GetElementsByTagName('text')[0]."
                f"AppendChild($template.CreateTextNode('{escaped_title}')) | Out-Null;"
                f"$template.GetElementsByTagName('text')[1]."
                f"AppendChild($template.CreateTextNode('{escaped_message}')) | Out-Null;"
                f"{icon_injection}"
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($template);"
                "[Windows.UI.Notifications.ToastNotificationManager]::"
                "CreateToastNotifier('FetchDrop').Show($toast);"
            )

            encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
            subprocess.run(
                [
                    "powershell", "-NoProfile", "-NonInteractive",
                    "-WindowStyle", "Hidden", "-EncodedCommand", encoded,
                ],
                creationflags=CREATE_NO_WINDOW,
                timeout=5,
                capture_output=True,
            )
        except Exception as exc:
            log.warning(f"Notifikasi toast gagal: {exc}")

    threading.Thread(target=_notify, daemon=True).start()

# ── Cleanup & Engine Validation ───────────────────────────────────────────────
def cleanup_partial_files(folder: str) -> None:
    """Membersihkan file sampah jika proses unduhan dibatalkan."""
    partial_suffixes = (".part", ".ytdl", ".temp")
    fstream_re = re.compile(
        r"\.f\d{2,5}\.(mp4|m4a|webm|opus|ogg|ts|aac|flac|wav|vtt)$",
        re.IGNORECASE,
    )

    def _try_remove(path_obj: Path, max_retries: int = 6) -> None:
        for attempt in range(max_retries):
            try:
                path_obj.unlink(missing_ok=True)
                return
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(0.3 * (2 ** attempt))
            except OSError:
                return

    try:
        folder_path = Path(folder)
        if not folder_path.exists() or not folder_path.is_dir():
            return
        
        for entry in folder_path.iterdir():
            if not entry.is_file():
                continue
            name = entry.name
            if name.endswith(partial_suffixes) or ".part-Frag" in name or fstream_re.search(name):
                _try_remove(entry)
    except Exception as exc:
        log.warning(f"Cleanup gagal memindai folder: {exc}")

def engine_is_ready() -> bool:
    has_ytdlp = YTDLP_EXE.exists() and YTDLP_EXE.stat().st_size >= 1_000_000
    has_ffmpeg = bool(
        shutil.which("ffmpeg")
        or ((DEPENDENCY_DIR / "ffmpeg.exe").exists() and (DEPENDENCY_DIR / "ffprobe.exe").exists())
    )
    return has_ytdlp and has_ffmpeg

def get_ffmpeg_location() -> str | None:
    return None if shutil.which("ffmpeg") else str(DEPENDENCY_DIR)

# ── Metadata Fetching ─────────────────────────────────────────────────────────
def get_info(url: str, is_audio: bool = False) -> tuple[MediaInfo | None, str | None]:
    cmd = [
        str(YTDLP_EXE), "-J", "--no-warnings", "--no-colors",
        "--socket-timeout", "15", "--playlist-items", "1",
    ]
    if ffmpeg_loc := get_ffmpeg_location():
        cmd.extend(["--ffmpeg-location", ffmpeg_loc])
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=30, creationflags=CREATE_NO_WINDOW,
        )

        if result.returncode != 0:
            stderr = result.stderr.lower() if result.stderr else ""
            if "private" in stderr or "members only" in stderr:
                return None, "Video bersifat privat atau memerlukan akses khusus."
            if "not available" in stderr or "removed" in stderr:
                return None, "Video tidak ditemukan atau telah dihapus."
            if "geo" in stderr or "blocked" in stderr:
                return None, "Video diblokir di wilayah Anda."
            return None, "Gagal mengambil info: video tidak ditemukan atau diblokir."

        info = json.loads(result.stdout)
        playlist_count: int | None = None

        if "entries" in info:
            playlist_count = info.get("playlist_count") or info.get("entry_count")
            entries = [e for e in (info.get("entries") or []) if e]
            if not playlist_count and entries:
                playlist_count = len(entries)
            if not entries:
                return None, "Playlist kosong atau tidak dapat diakses."
            info = entries[0]

        filesize = info.get("filesize")
        size_raw = filesize if filesize is not None else (info.get("filesize_approx") or "NA")

        available_resolutions = ["Best"]
        seen_heights = sorted({
            f.get("height") for f in info.get("formats", [])
            if f.get("height") and f.get("vcodec") and f.get("vcodec") != "none"
            and "storyboard" not in str(f.get("format_note", "")).lower()
        }, reverse=True)

        added_labels = set()
        for height in seen_heights:
            for threshold, label in _RES_MAP_LABELS:
                if height >= threshold and label not in added_labels:
                    available_resolutions.append(label)
                    added_labels.add(label)
                    break

        upload_date = info.get("upload_date", "Unknown")
        if upload_date and len(upload_date) == 8 and upload_date.isdigit():
            upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"

        data: MediaInfo = {
            "title": info.get("title", "Tidak diketahui"),
            "channel": info.get("channel") or info.get("uploader", "Tidak diketahui"),
            "duration": info.get("duration_string", "Tidak diketahui"),
            "upload_date": upload_date,
            "size": format_size(size_raw),
            "acodec": shorten_codec(info.get("acodec")),
            "playlist_count": playlist_count,
            "available_resolutions": available_resolutions,
        }

        if not is_audio:
            data["resolution"] = info.get("resolution", "Tidak diketahui")
            data["vcodec"] = shorten_codec(info.get("vcodec"))
        else:
            asr = info.get("asr")
            data["asr"] = f"{asr:,}" if isinstance(asr, (int, float)) else "Tidak diketahui"

        return data, None

    except subprocess.TimeoutExpired:
        return None, "Waktu habis (timeout 30 detik). Periksa koneksi internet."
    except json.JSONDecodeError:
        return None, "Respons dari mesin tidak valid. Coba perbarui mesin."
    except FileNotFoundError:
        return None, "File mesin yt-dlp tidak ditemukan."
    except Exception as exc:
        log.warning(f"get_info error: {exc}")
        return None, f"Kesalahan tidak terduga: {str(exc)[:80]}"

# ── Splash Screen ─────────────────────────────────────────────────────────────
class SplashOverlay(ctk.CTkFrame):
    _FADE_TOTAL = 18

    def __init__(self, parent: ctk.CTk) -> None:
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self.lift()

        self._dismiss_id: str | None = None
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        self._lbl_logo = ctk.CTkLabel(
            inner, text="⚡ FetchDrop", font=(FONT_FAMILY, 40, "bold"), text_color=COLOR_TEXT_MAIN
        )
        self._lbl_logo.pack(pady=(0, 4))

        self._lbl_sub = ctk.CTkLabel(
            inner, text="Menyiapkan mesin pengunduh — hanya dilakukan sekali.",
            font=(FONT_FAMILY, 11), text_color=COLOR_TEXT_MUTED
        )
        self._lbl_sub.pack(pady=(0, 36))

        self._bar = ctk.CTkProgressBar(
            inner, width=360, height=5, progress_color=COLOR_ACCENT,
            fg_color="#1A1A1E", mode="indeterminate"
        )
        self._bar.pack(pady=(0, 10))
        self._bar.start()

        self._lbl_pct = ctk.CTkLabel(
            inner, text="", font=(FONT_FAMILY, 12, "bold"),
            text_color=COLOR_ACCENT, width=360, anchor="e"
        )
        self._lbl_pct.pack()

        self._lbl_status = ctk.CTkLabel(
            inner, text="Memeriksa komponen sistem...", font=(FONT_FAMILY, 11),
            text_color=COLOR_TEXT_MUTED, width=360, anchor="w"
        )
        self._lbl_status.pack(pady=(4, 0))

    def set_status(self, text: str, pct: str = "") -> None:
        if self.winfo_exists():
            self._lbl_status.configure(text=text)
            self._lbl_pct.configure(text=pct)

    def switch_to_determinate(self) -> None:
        if self.winfo_exists():
            self._bar.stop()
            self._bar.configure(mode="determinate")
            self._bar.set(0.0)

    def set_progress(self, value: float) -> None:
        if self.winfo_exists():
            self._bar.set(max(0.0, min(1.0, value)))

    def dismiss(self) -> None:
        if not self.winfo_exists() or self._dismiss_id is not None:
            return
        self._animate_fade_out(0)

    def _animate_fade_out(self, step: int) -> None:
        if not self.winfo_exists():
            return
        t = _ease_in_out_sine(step / self._FADE_TOTAL)

        try:
            self._lbl_logo.configure(text_color=_lerp_color(COLOR_TEXT_MAIN, COLOR_BG, t))
            self._lbl_sub.configure(text_color=_lerp_color(COLOR_TEXT_MUTED, COLOR_BG, t))
            self._lbl_pct.configure(text_color=_lerp_color(COLOR_ACCENT, COLOR_BG, t))
            self._lbl_status.configure(text_color=_lerp_color(COLOR_TEXT_MUTED, COLOR_BG, t))
            self._bar.configure(
                progress_color=_lerp_color(COLOR_ACCENT, COLOR_BG, t),
                fg_color=_lerp_color("#1A1A1E", COLOR_BG, t)
            )
        except Exception:
            pass

        if step < self._FADE_TOTAL:
            self._dismiss_id = self.after(ANIM_FRAME_MS, lambda: self._animate_fade_out(step + 1))
        else:
            if self.winfo_exists():
                self.destroy()

# ── Main Application ──────────────────────────────────────────────────────────
class FetchDropApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("FetchDrop – Social Media Downloader")
        self.geometry("720x490")
        self.minsize(720, 490)
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG)

        self._center_window()
        self._load_window_icon()

        cfg = load_config()
        self.download_count: int = cfg.get("download_count", 0)
        self.download_folder: str = cfg["download_folder"]
        self.current_info_url: str | None = None
        self.current_platform: str | None = None
        self._last_fetched_title: str | None = None
        self._last_fetched_size: str | None = None
        self.dl_mode: str = cfg.get("last_mode", "video")

        self._cancel_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._is_downloading: bool = False
        self._dl_process: subprocess.Popen[str] | None = None
        self._splash: SplashOverlay | None = None
        self._engine_ready: bool = False

        self.vformat: str = "bv*+ba/b"
        self.container: str = "auto"
        self.aquality: str = "320k"
        self._last_video_resolutions: list[str] | None = None

        self._fade_version: int = 0
        self._info_fetch_token: int = 0
        self.current_progress: float = 0.0
        self.target_progress: float = 0.0
        self._anim_id: str | None = None
        self._is_animating_progress: bool = False

        self.fonts = self._create_fonts()

        # Animation states
        self._sidebar_anim_id: str | None = None
        self._focus_debounce_id: str | None = None
        self._status_anim_id: str | None = None
        self._folder_hover_id: str | None = None
        self._btn_enable_id: str | None = None
        self._header_fade_id: str | None = None
        self._header_fade_ver: int = 0
        self._counter_flash_id: str | None = None
        self._status_current_color: str = COLOR_TEXT_MUTED
        self._last_clipboard: str = ""

        self._setup_layout()
        self._apply_saved_config(cfg)
        self._run_dependency_check()

        self.bind("<Control-v>", self._on_ctrl_v)
        self.bind("<FocusIn>", self._on_window_focus)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self.url_entry.bind("<KeyRelease>", self._on_url_changed)

    def _center_window(self) -> None:
        self.update_idletasks()
        w, h = 720, 490
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _load_window_icon(self) -> None:
        if IS_WINDOWS:
            try:
                icon_path = _resource_path("icon.ico")
                if icon_path.exists():
                    self.iconbitmap(str(icon_path))
            except Exception as e:
                log.warning(f"Gagal memuat ikon: {e}")

    def _create_fonts(self) -> dict[str, ctk.CTkFont]:
        return {
            "nav_bold": ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            "nav_reg": ctk.CTkFont(family=FONT_FAMILY, size=12),
            "header": ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            "label_bold": ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            "label_reg": ctk.CTkFont(family=FONT_FAMILY, size=12),
            "label_sm": ctk.CTkFont(family=FONT_FAMILY, size=11),
            "label_sm_bold": ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            "label_xs": ctk.CTkFont(family=FONT_FAMILY, size=10),
            "label_xs_bold": ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            "label_9_bold": ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
            "btn_main": ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            "btn_sm": ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            "btn_xs": ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            "counter": ctk.CTkFont(family=FONT_FAMILY, size=18, weight="bold"),
            "logo": ctk.CTkFont(family=FONT_FAMILY, size=20, weight="bold"),
            "icon_lg": ctk.CTkFont(family=FONT_FAMILY, size=18),
            "icon_md": ctk.CTkFont(family=FONT_FAMILY, size=13),
        }

    def _on_close_request(self) -> None:
        self._cancel_all_animations()
        if self._is_downloading:
            if not messagebox.askyesno(
                "Unduhan Berjalan",
                "Membatalkan unduhan yang sedang berlangsung.\nYakin ingin keluar?",
                icon="warning",
                parent=self,
            ):
                return

        self._shutdown_event.set()
        self._cancel_event.set()
        self._kill_dl_process()
        if self._splash:
            try:
                self._splash.dismiss()
            except Exception:
                pass
            self._splash = None
        self._save_current_config()
        self.destroy()

    def _cancel_all_animations(self) -> None:
        for anim_id in (
            self._anim_id, self._sidebar_anim_id, self._focus_debounce_id,
            self._status_anim_id, self._folder_hover_id, self._btn_enable_id,
            self._header_fade_id, self._counter_flash_id,
        ):
            if anim_id is not None:
                try:
                    self.after_cancel(anim_id)
                except Exception:
                    pass
        self._anim_id = self._sidebar_anim_id = self._focus_debounce_id = None
        self._status_anim_id = self._folder_hover_id = self._btn_enable_id = None
        self._header_fade_id = self._counter_flash_id = None

    # ── Modular Layout System ─────────────────────────────────────────────────
    def _setup_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main_content()

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=190, corner_radius=0, fg_color=COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar, text="⚡ FetchDrop", font=self.fonts["logo"], text_color=COLOR_TEXT_MAIN
        ).grid(row=0, column=0, padx=20, pady=(24, 2), sticky="w")

        ctk.CTkLabel(
            self.sidebar, text="Stable Engine", font=self.fonts["label_xs_bold"], text_color=COLOR_TEXT_MUTED
        ).grid(row=1, column=0, padx=20, pady=(0, 24), sticky="w")

        ctk.CTkLabel(
            self.sidebar, text="UNDUHAN", font=self.fonts["label_xs_bold"], text_color="#4B4B54"
        ).grid(row=2, column=0, padx=20, pady=(0, 6), sticky="w")

        self.btn_mode_video = ctk.CTkButton(
            self.sidebar, text="🎬  Video", anchor="w", height=36, fg_color=COLOR_ACCENT,
            text_color=COLOR_TEXT_MAIN, font=self.fonts["nav_bold"], hover_color=COLOR_ACCENT_HOVER,
            command=lambda: self._select_sidebar_mode("video")
        )
        self.btn_mode_video.grid(row=3, column=0, padx=12, pady=3, sticky="ew")

        self.btn_mode_audio = ctk.CTkButton(
            self.sidebar, text="🎵  Audio MP3", anchor="w", height=36, fg_color="transparent",
            text_color=COLOR_TEXT_MUTED, font=self.fonts["nav_reg"], hover_color=COLOR_HOVER_BG,
            command=lambda: self._select_sidebar_mode("audio")
        )
        self.btn_mode_audio.grid(row=4, column=0, padx=12, pady=3, sticky="ew")

        self.sidebar.grid_rowconfigure(5, weight=1)
        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ews", padx=20, pady=20)

        ctk.CTkLabel(
            footer, text="TOTAL TERUNDUH", font=self.fonts["label_9_bold"], text_color="#4B4B54"
        ).pack(anchor="w")

        counter_row = ctk.CTkFrame(footer, fg_color="transparent")
        counter_row.pack(anchor="w", pady=(2, 0), fill="x")

        self.lbl_stats_counter = ctk.CTkLabel(
            counter_row, text=f"{self.download_count} Berkas", font=self.fonts["counter"], text_color=COLOR_ACCENT
        )
        self.lbl_stats_counter.pack(side="left")

        self.btn_reset_count = ctk.CTkButton(
            counter_row, text="↺", width=26, height=26, fg_color="transparent",
            hover_color="#1E1E22", text_color="#4B4B54", font=self.fonts["icon_md"],
            command=self._do_reset_count
        )
        self.btn_reset_count.pack(side="left", padx=(6, 0), pady=(2, 0))

        self.btn_update_engine = ctk.CTkButton(
            footer, text="🔄 Perbarui Mesin", height=28, fg_color="#1E1E22",
            hover_color="#25252A", text_color=COLOR_TEXT_MUTED, font=self.fonts["btn_xs"],
            command=self._update_engine
        )
        self.btn_update_engine.pack(anchor="w", pady=(14, 0), fill="x")

    def _build_main_content(self) -> None:
        self.main_content = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_content.grid_columnconfigure(0, weight=1)

        self._build_header_section()
        self._build_input_section()
        self._build_info_section()
        self._build_config_section()
        self._build_status_section()
        self._build_action_section()

    def _build_header_section(self) -> None:
        self.lbl_header_title = ctk.CTkLabel(
            self.main_content, text="🎬  Video Stream Downloader",
            font=self.fonts["header"], text_color=COLOR_TEXT_MAIN
        )
        self.lbl_header_title.grid(row=0, column=0, sticky="w", pady=(0, 10))

    def _build_input_section(self) -> None:
        input_card = ctk.CTkFrame(
            self.main_content, height=46, fg_color=COLOR_CARD,
            border_color=COLOR_BORDER, border_width=1
        )
        input_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        input_card.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            input_card, placeholder_text="Tempel tautan media di sini...", height=46,
            fg_color="transparent", border_width=0, font=self.fonts["label_reg"],
            text_color=COLOR_TEXT_MAIN, placeholder_text_color=COLOR_TEXT_MUTED
        )
        self.url_entry.grid(row=0, column=0, padx=(14, 6), sticky="ew")
        self.url_entry.bind("<Return>", lambda _: self._load_video_info())

        actions = ctk.CTkFrame(input_card, fg_color="transparent")
        actions.grid(row=0, column=1, padx=(0, 6), sticky="e")

        ctk.CTkButton(
            actions, text="✕", width=30, height=30, fg_color="#1E1E22",
            hover_color="#3A1A1A", text_color="#FF6B6B", font=self.fonts["label_sm_bold"],
            command=self._clear_url
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            actions, text="📋", width=30, height=30, fg_color="#1E1E22",
            hover_color="#25252A", text_color=COLOR_TEXT_MAIN, font=self.fonts["label_sm_bold"],
            command=self._paste_url
        ).pack(side="left", padx=2)

        self.btn_check_url = ctk.CTkButton(
            actions, text="Cek Media", width=82, height=30, fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HOVER, text_color=COLOR_TEXT_MAIN,
            font=self.fonts["btn_sm"], command=self._load_video_info
        )
        self.btn_check_url.pack(side="left", padx=(4, 0))

    def _build_info_section(self) -> None:
        info_card = ctk.CTkFrame(
            self.main_content, fg_color=COLOR_CARD, border_color=COLOR_BORDER, border_width=1
        )
        info_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.lbl_info_title = ctk.CTkLabel(
            info_card, text="Judul Konten : -", font=self.fonts["label_bold"],
            text_color=COLOR_TEXT_DIM, anchor="w", wraplength=460
        )
        self.lbl_info_title.grid(row=0, column=0, padx=14, pady=(10, 2), sticky="ew")

        self.lbl_info_channel = ctk.CTkLabel(
            info_card, text="Uploader        : -", font=self.fonts["label_reg"],
            text_color=COLOR_TEXT_DIM, anchor="w"
        )
        self.lbl_info_channel.grid(row=1, column=0, padx=14, pady=2, sticky="ew")

        self.lbl_info_meta1 = ctk.CTkLabel(
            info_card, text="Durasi  : -   •   Diunggah: -   •   Est. Ukuran: -",
            font=self.fonts["label_reg"], text_color=COLOR_TEXT_DIM, anchor="w"
        )
        self.lbl_info_meta1.grid(row=2, column=0, padx=14, pady=2, sticky="ew")

        self.lbl_info_meta2 = ctk.CTkLabel(
            info_card, text="Codec Video : -   •   Codec Audio: -",
            font=self.fonts["label_reg"], text_color=COLOR_TEXT_DIM, anchor="w"
        )
        self.lbl_info_meta2.grid(row=3, column=0, padx=14, pady=(2, 10), sticky="ew")

    def _build_config_section(self) -> None:
        config_card = ctk.CTkFrame(
            self.main_content, height=50, fg_color=COLOR_CARD, border_color=COLOR_BORDER, border_width=1
        )
        config_card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        config_card.grid_columnconfigure(1, weight=1)
        config_card.grid_columnconfigure(3, weight=0)

        self.lbl_res = ctk.CTkLabel(config_card, text="Kualitas Video:", font=self.fonts["label_reg"])
        self.lbl_res.grid(row=0, column=0, padx=(14, 10), pady=10, sticky="w")

        self.combo_res = ctk.CTkComboBox(
            config_card, values=VIDEO_QUALITY_OPTIONS, width=135, height=30,
            font=self.fonts["label_reg"], fg_color=COLOR_BG, border_color=COLOR_BORDER,
            button_color="#1E1E22", button_hover_color="#25252A", state="readonly",
            command=self._update_quality_vars
        )
        self.combo_res.grid(row=0, column=1, pady=10, sticky="w")

        self.lbl_container = ctk.CTkLabel(config_card, text="Format Video:", font=self.fonts["label_reg"])
        self.lbl_container.grid(row=0, column=2, padx=(20, 10), pady=10, sticky="w")

        self.combo_container = ctk.CTkComboBox(
            config_card, values=["Format Asli", "MP4", "MKV"], width=140, height=30,
            font=self.fonts["label_reg"], fg_color=COLOR_BG, border_color=COLOR_BORDER,
            button_color="#1E1E22", button_hover_color="#25252A", state="readonly",
            command=self._update_container_vars
        )
        self.combo_container.grid(row=0, column=3, padx=(0, 14), pady=10, sticky="w")

    def _build_status_section(self) -> None:
        status_zone = ctk.CTkFrame(self.main_content, fg_color="transparent")
        status_zone.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        status_zone.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(
            status_zone, text="Menunggu tautan...", font=self.fonts["label_sm"],
            text_color=COLOR_TEXT_MUTED, anchor="w"
        )
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.lbl_percentage = ctk.CTkLabel(
            status_zone, text="0%", font=self.fonts["icon_md"], text_color=COLOR_ACCENT
        )
        self.lbl_percentage.grid(row=0, column=1, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(
            self.main_content, progress_color=COLOR_ACCENT, fg_color=COLOR_PROGRESS_BG, height=4
        )
        self.progress_bar.grid(row=5, column=0, sticky="ew", pady=(4, 16))
        self.progress_bar.set(0)

    def _build_action_section(self) -> None:
        action_bar = ctk.CTkFrame(self.main_content, fg_color="transparent")
        action_bar.grid(row=6, column=0, sticky="ew")
        action_bar.grid_columnconfigure(0, weight=1)

        self.lbl_folder = ctk.CTkLabel(
            action_bar, text=format_folder_label(self.download_folder),
            font=self.fonts["label_sm"], text_color=COLOR_TEXT_MUTED, cursor="hand2"
        )
        self.lbl_folder.grid(row=0, column=0, sticky="w")
        self.lbl_folder.bind("<Button-1>", lambda _: self._open_output_folder())
        self.lbl_folder.bind("<Enter>", lambda _: self._start_folder_hover(entering=True))
        self.lbl_folder.bind("<Leave>", lambda _: self._start_folder_hover(entering=False))

        controls_right = ctk.CTkFrame(action_bar, fg_color="transparent")
        controls_right.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            controls_right, text="Ubah Folder", width=86, height=32,
            fg_color=COLOR_CARD, hover_color="#1E1E22", text_color=COLOR_TEXT_MUTED,
            border_color=COLOR_BORDER, border_width=1, command=self._change_output_folder
        ).pack(side="left", padx=3)

        self.btn_cancel = ctk.CTkButton(
            controls_right, text="Batal", width=70, height=32,
            fg_color="transparent", text_color="#FFA4A4", hover_color="#2A1418",
            border_width=1, border_color="#3A1C20", state="disabled", command=self._cancel_download
        )
        self.btn_cancel.pack(side="left", padx=3)

        self.btn_download = ctk.CTkButton(
            controls_right, text="⬇  UNDUH VIDEO", width=148, height=32,
            fg_color=COLOR_BTN_DISABLED_BG, text_color=COLOR_BTN_DISABLED_FG,
            font=self.fonts["btn_main"], state="disabled", command=self._start_download
        )
        self.btn_download.pack(side="left", padx=(6, 0))

    # ── Logic & Animations ────────────────────────────────────────────────────
    def _do_reset_count(self) -> None:
        if messagebox.askyesno("Reset Counter", "Reset hitungan unduhan ke 0?", parent=self):
            self.download_count = 0
            self.lbl_stats_counter.configure(text="0 Berkas")
            self._save_current_config()

    def _animate_progress_bar(self) -> None:
        if not self.winfo_exists():
            return
        diff = self.target_progress - self.current_progress
        if abs(diff) > 0.0015:
            proximity = max(abs(diff), 0.05)
            factor = 0.18 + 0.12 * _ease_out_cubic(min(proximity * 3, 1.0))
            self.current_progress += diff * factor
            self.current_progress = max(0.0, min(1.0, self.current_progress))
            self.progress_bar.set(self.current_progress)

            if self.lbl_percentage.winfo_exists():
                pct_int = round(self.current_progress * 100)
                if self.lbl_percentage.cget("text") != f"{pct_int}%":
                    self.lbl_percentage.configure(text=f"{pct_int}%")

            if self._anim_id:
                try:
                    self.after_cancel(self._anim_id)
                except Exception:
                    pass
            self._anim_id = self.after(ANIM_FRAME_MS, self._animate_progress_bar)
        else:
            self.current_progress = self.target_progress
            self.progress_bar.set(self.current_progress)
            if self.lbl_percentage.winfo_exists():
                self.lbl_percentage.configure(text=f"{round(self.target_progress * 100)}%")
            self._anim_id = None
            self._is_animating_progress = False

    def _trigger_progress_animation(self) -> None:
        if not self._is_animating_progress:
            self._is_animating_progress = True
            self._animate_progress_bar()

    def _fade_in_text(self, labels: list[tuple[ctk.CTkLabel, str, bool]], step: int = 0, version: int = 0) -> None:
        if version != self._fade_version or not self.winfo_exists():
            return
        total = ANIM_FADE_TEXT_FRAMES
        _START_TITLE, _START_MUTED = "#1C1C20", "#181819"

        if step < total:
            t = _ease_out_cubic(step / (total - 1))
            for lbl, txt, is_title in labels:
                if lbl.winfo_exists():
                    from_c = _START_TITLE if is_title else _START_MUTED
                    to_c = COLOR_TEXT_MAIN if is_title else COLOR_TEXT_MUTED
                    lbl.configure(text=txt, text_color=_lerp_color(from_c, to_c, t))
            delay = max(ANIM_FRAME_MS - 2, int(ANIM_FRAME_MS * (1.0 - t * 0.35)))
            self.after(delay, lambda: self._fade_in_text(labels, step + 1, version))
        else:
            for lbl, txt, is_title in labels:
                if lbl.winfo_exists():
                    lbl.configure(text=txt, text_color=COLOR_TEXT_MAIN if is_title else COLOR_TEXT_MUTED)

    def _select_sidebar_mode(self, mode: str) -> None:
        if self._is_downloading:
            return
        if self._sidebar_anim_id:
            try:
                self.after_cancel(self._sidebar_anim_id)
            except Exception:
                pass
            self._sidebar_anim_id = None

        self.dl_mode = mode
        self._info_fetch_token += 1
        is_video = mode == "video"
        
        for m, btn in {"video": self.btn_mode_video, "audio": self.btn_mode_audio}.items():
            is_active = m == mode
            # Hanya update font di sini; text_color dikelola oleh animasi sidebar
            # agar tidak terjadi flash (step-0 animasi memulai dari warna berlawanan)
            btn.configure(
                font=self.fonts["nav_bold"] if is_active else self.fonts["nav_reg"]
            )
            
        self._animate_sidebar_select(is_video, 0)
        self._update_mode_ui(is_video)

        if self.combo_res.cget("values"):
            self._update_quality_vars(self.combo_res.get())
        if is_video:
            self._update_container_vars(self.combo_container.get())

        self._reset_info_display()
        self._save_current_config()

    def _update_mode_ui(self, is_video: bool) -> None:
        new_title = "🎬  Video Stream Downloader" if is_video else "🎵  Audio MP3 Extractor"
        self._header_fade_ver += 1
        self._start_header_fade(new_title, self._header_fade_ver)

        if is_video:
            self.lbl_res.configure(text="Kualitas Video:")
            res_values = self._last_video_resolutions or VIDEO_QUALITY_OPTIONS
            prev = self.combo_res.get()
            self.combo_res.configure(values=res_values)
            self.combo_res.set(prev if prev in res_values else res_values[0])
            self.lbl_container.grid()
            self.combo_container.grid()
            self.btn_download.configure(text="⬇  UNDUH VIDEO")
        else:
            self.lbl_res.configure(text="Bitrate MP3:")
            prev = self.combo_res.get()
            self.combo_res.configure(values=AUDIO_QUALITY_OPTIONS)
            self.combo_res.set(prev if prev in AUDIO_QUALITY_OPTIONS else AUDIO_QUALITY_OPTIONS[0])
            self.lbl_container.grid_remove()
            self.combo_container.grid_remove()
            self.btn_download.configure(text="🎵  EKSTRAK MP3")

    def _animate_sidebar_select(self, is_video: bool, step: int = 0) -> None:
        if step > ANIM_SIDEBAR_FRAMES or not self.winfo_exists():
            if self.winfo_exists():
                # State final; text_color ditetapkan di sini (bukan di for-loop
                # _select_sidebar_mode) untuk menghindari flash di frame pertama animasi
                self.btn_mode_video.configure(
                    fg_color=COLOR_ACCENT if is_video else COLOR_SIDEBAR,
                    hover_color=COLOR_ACCENT_HOVER if is_video else COLOR_HOVER_BG,
                    text_color=COLOR_TEXT_MAIN if is_video else COLOR_TEXT_MUTED,
                )
                self.btn_mode_audio.configure(
                    fg_color=COLOR_ACCENT if not is_video else COLOR_SIDEBAR,
                    hover_color=COLOR_ACCENT_HOVER if not is_video else COLOR_HOVER_BG,
                    text_color=COLOR_TEXT_MAIN if not is_video else COLOR_TEXT_MUTED,
                )
            self._sidebar_anim_id = None
            return

        t = _ease_out_cubic(step / ANIM_SIDEBAR_FRAMES)
        a_col, i_col = _lerp_color(COLOR_SIDEBAR, COLOR_ACCENT, t), _lerp_color(COLOR_ACCENT, COLOR_SIDEBAR, t)
        a_txt, i_txt = _lerp_color(COLOR_TEXT_MUTED, COLOR_TEXT_MAIN, t), _lerp_color(COLOR_TEXT_MAIN, COLOR_TEXT_MUTED, t)

        if is_video:
            self.btn_mode_video.configure(fg_color=a_col, text_color=a_txt)
            self.btn_mode_audio.configure(fg_color=i_col, text_color=i_txt)
        else:
            self.btn_mode_audio.configure(fg_color=a_col, text_color=a_txt)
            self.btn_mode_video.configure(fg_color=i_col, text_color=i_txt)

        self._sidebar_anim_id = self.after(ANIM_FRAME_MS, lambda: self._animate_sidebar_select(is_video, step + 1))

    def _apply_saved_config(self, cfg: JsonDict) -> None:
        self._select_sidebar_mode(cfg.get("last_mode", "video"))
        sq = cfg.get("last_quality", "Best")
        if self.dl_mode == "video" and sq in VIDEO_QUALITY_OPTIONS:
            self.combo_res.set(sq)
        elif self.dl_mode == "audio" and sq in AUDIO_QUALITY_OPTIONS:
            self.combo_res.set(sq)
        self.combo_container.set(cfg.get("last_container", "Format Asli"))
        self._update_quality_vars(self.combo_res.get())
        self._update_container_vars(self.combo_container.get())

    def _save_current_config(self) -> None:
        save_config({
            "download_folder": self.download_folder,
            "last_quality": self.combo_res.get(),
            "last_container": self.combo_container.get(),
            "last_mode": self.dl_mode if self.dl_mode in ("video", "audio") else "video",
            "download_count": self.download_count,
        })
        if self.lbl_stats_counter.winfo_exists():
            self.lbl_stats_counter.configure(text=f"{self.download_count} Berkas")

    def _reset_info_display(self) -> None:
        self.current_info_url = None
        # Batalkan animasi enable tombol yang mungkin masih berjalan sebelum men-disable
        if self._btn_enable_id:
            try:
                self.after_cancel(self._btn_enable_id)
            except Exception:
                pass
            self._btn_enable_id = None
        self.btn_download.configure(state="disabled", fg_color=COLOR_BTN_DISABLED_BG, text_color=COLOR_BTN_DISABLED_FG)

        url = self.url_entry.get().strip()
        self.btn_check_url.configure(
            state="normal" if (url and self._engine_ready and not self._is_downloading) else "disabled",
            text="Cek Media"
        )

        self.lbl_info_title.configure(text="Judul Konten : -", text_color=COLOR_TEXT_DIM)
        self.lbl_info_channel.configure(text="Uploader        : -", text_color=COLOR_TEXT_DIM)
        self.lbl_info_meta1.configure(text="Durasi  : -   •   Diunggah: -   •   Est. Ukuran: -", text_color=COLOR_TEXT_DIM)
        meta2 = "Codec Video : -   •   Codec Audio: -" if self.dl_mode == "video" else "Audio Rate  : -   •   Codec Audio: -"
        self.lbl_info_meta2.configure(text=meta2, text_color=COLOR_TEXT_DIM)

        self.target_progress = 0.0
        self._trigger_progress_animation()
        self.lbl_percentage.configure(text="0%", text_color=COLOR_TEXT_MUTED)
        self._update_status("Siap. Tempel tautan untuk mulai.")

    def _update_status(self, text: str, progress_val: float | None = None, percent_text: str | None = None,
                       is_error: bool = False, is_success: bool = False) -> None:
        if not self.winfo_exists():
            return
            
        target_color = COLOR_TEXT_MUTED
        pct_color = COLOR_ACCENT
        if is_error:
            target_color = pct_color = COLOR_TEXT_ERROR
        elif is_success:
            target_color = pct_color = COLOR_TEXT_SUCCESS

        self.lbl_status.configure(text=text)
        self._start_status_color_fade(target_color)

        if progress_val is not None:
            self.target_progress = float(progress_val)
            self._trigger_progress_animation()
        if percent_text is not None:
            if progress_val in (0.0, 1.0, None):
                self.lbl_percentage.configure(text=percent_text, text_color=pct_color)
            else:
                self.lbl_percentage.configure(text_color=pct_color)

    def _update_quality_vars(self, val: str) -> None:
        if self.dl_mode == "video":
            self.vformat = _RES_FORMAT_MAP.get(val, "bv*+ba/b")
        else:
            self.aquality = _AUDIO_QUALITY_MAP.get(val, "192k")

    def _update_container_vars(self, val: str) -> None:
        self.container = {"MP4": "mp4", "MKV": "mkv"}.get(val, "auto")

    def _start_status_color_fade(self, target: str) -> None:
        if not self.winfo_exists():
            return
        if self._status_anim_id:
            try:
                self.after_cancel(self._status_anim_id)
            except Exception:
                pass
            self._status_anim_id = None

        if self._status_current_color == target:
            self.lbl_status.configure(text_color=target)
            return
        self._animate_status_color(self._status_current_color, target, 0)

    def _animate_status_color(self, from_c: str, to_c: str, step: int) -> None:
        if not self.winfo_exists():
            return
        t = _ease_out_cubic(step / ANIM_STATUS_FRAMES) if step < ANIM_STATUS_FRAMES else 1.0
        if self.lbl_status.winfo_exists():
            self.lbl_status.configure(text_color=_lerp_color(from_c, to_c, t))

        if step < ANIM_STATUS_FRAMES:
            self._status_anim_id = self.after(ANIM_FRAME_MS, lambda: self._animate_status_color(from_c, to_c, step + 1))
        else:
            self._status_current_color = to_c
            self._status_anim_id = None

    def _start_folder_hover(self, entering: bool) -> None:
        if not self.winfo_exists():
            return
        if self._folder_hover_id:
            try:
                self.after_cancel(self._folder_hover_id)
            except Exception:
                pass
        try:
            from_c = self.lbl_folder.cget("text_color")
            if isinstance(from_c, (list, tuple)):
                from_c = from_c[0]
        except Exception:
            from_c = COLOR_TEXT_MUTED
        to_c = COLOR_TEXT_MAIN if entering else COLOR_TEXT_MUTED
        self._animate_folder_hover(str(from_c), to_c, 0)

    def _animate_folder_hover(self, from_c: str, to_c: str, step: int) -> None:
        if not self.winfo_exists():
            return
        t = _ease_in_out_sine(step / ANIM_HOVER_FRAMES) if step < ANIM_HOVER_FRAMES else 1.0
        if self.lbl_folder.winfo_exists():
            self.lbl_folder.configure(text_color=_lerp_color(from_c, to_c, t))
        if step < ANIM_HOVER_FRAMES:
            self._folder_hover_id = self.after(ANIM_FRAME_MS, lambda: self._animate_folder_hover(from_c, to_c, step + 1))
        else:
            self._folder_hover_id = None

    def _start_btn_download_enable(self) -> None:
        if not self.winfo_exists():
            return
        if self._btn_enable_id:
            try:
                self.after_cancel(self._btn_enable_id)
            except Exception:
                pass
        self.btn_download.configure(state="normal", hover_color=COLOR_ACCENT_HOVER)
        self._animate_btn_enable(0)

    def _animate_btn_enable(self, step: int) -> None:
        if not self.winfo_exists():
            return
        t = _ease_out_quint(step / 12) if step < 12 else 1.0
        bg = _lerp_color(COLOR_BTN_DISABLED_BG, COLOR_ACCENT, t)
        fg = _lerp_color(COLOR_BTN_DISABLED_FG, COLOR_TEXT_MAIN, t)
        if self.btn_download.winfo_exists():
            self.btn_download.configure(fg_color=bg, text_color=fg)
        if step < 12:
            self._btn_enable_id = self.after(ANIM_FRAME_MS, lambda: self._animate_btn_enable(step + 1))
        else:
            self._btn_enable_id = None

    def _start_header_fade(self, new_text: str, version: int) -> None:
        if not self.winfo_exists():
            return
        if self._header_fade_id:
            try:
                self.after_cancel(self._header_fade_id)
            except Exception:
                pass
        self._animate_header_fade(new_text, version, 0)

    def _animate_header_fade(self, new_text: str, version: int, step: int) -> None:
        if not self.winfo_exists() or version != self._header_fade_ver:
            return
        if step <= ANIM_HEADER_FADE_OUT:
            t = _ease_in_out_sine(step / ANIM_HEADER_FADE_OUT) if ANIM_HEADER_FADE_OUT > 0 else 1.0
            if self.lbl_header_title.winfo_exists():
                self.lbl_header_title.configure(text_color=_lerp_color(COLOR_TEXT_MAIN, "#18181B", t))
            if step == ANIM_HEADER_FADE_OUT and self.lbl_header_title.winfo_exists():
                self.lbl_header_title.configure(text=new_text)
        else:
            idx = step - ANIM_HEADER_FADE_OUT
            t = _ease_out_cubic(idx / ANIM_HEADER_FADE_IN) if ANIM_HEADER_FADE_IN > 0 else 1.0
            if self.lbl_header_title.winfo_exists():
                self.lbl_header_title.configure(text_color=_lerp_color("#18181B", COLOR_TEXT_MAIN, t))

        if step < (ANIM_HEADER_FADE_OUT + ANIM_HEADER_FADE_IN):
            self._header_fade_id = self.after(ANIM_FRAME_MS, lambda: self._animate_header_fade(new_text, version, step + 1))
        else:
            if self.lbl_header_title.winfo_exists():
                self.lbl_header_title.configure(text_color=COLOR_TEXT_MAIN)
            self._header_fade_id = None

    def _trigger_counter_flash(self) -> None:
        if not self.winfo_exists():
            return
        if self._counter_flash_id:
            try:
                self.after_cancel(self._counter_flash_id)
            except Exception:
                pass
        self._animate_counter_flash(0)

    def _animate_counter_flash(self, step: int) -> None:
        if not self.winfo_exists():
            return
        t = step / ANIM_COUNTER_FRAMES
        _FLASH_PEAK = "#FF6666"
        if t < 0.4:
            color = _lerp_color(COLOR_ACCENT, _FLASH_PEAK, _ease_out_quint(t / 0.4))
        else:
            color = _lerp_color(_FLASH_PEAK, COLOR_ACCENT, _ease_in_out_sine((t - 0.4) / 0.6))

        if self.lbl_stats_counter.winfo_exists():
            self.lbl_stats_counter.configure(text_color=color)

        if step < ANIM_COUNTER_FRAMES:
            self._counter_flash_id = self.after(20, lambda: self._animate_counter_flash(step + 1))
        else:
            if self.lbl_stats_counter.winfo_exists():
                self.lbl_stats_counter.configure(text_color=COLOR_ACCENT)
            self._counter_flash_id = None

    def _on_url_changed(self, _event: Any = None) -> None:
        url = self.url_entry.get().strip()
        if url and self._engine_ready and not self._is_downloading:
            self.btn_check_url.configure(state="normal")
        else:
            self.btn_check_url.configure(state="disabled")

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, text)
            self._on_url_changed()
        except Exception:
            pass

    def _clear_url(self) -> None:
        self.url_entry.delete(0, "end")
        self._last_video_resolutions = None
        if self.dl_mode == "video":
            self.combo_res.configure(values=VIDEO_QUALITY_OPTIONS)
            self.combo_res.set(VIDEO_QUALITY_OPTIONS[0])
            self._update_quality_vars(VIDEO_QUALITY_OPTIONS[0])
        self._reset_info_display()
        self._on_url_changed()

    def _on_ctrl_v(self, _event: Any = None) -> str | None:
        if self.focus_get() is self.url_entry:
            return None
        self._paste_url()
        url = self.url_entry.get().strip()
        if url and is_valid_url(url):
            self._load_video_info()
        return "break"

    def _on_window_focus(self, event: Any = None) -> None:
        if event and event.widget is not self:
            return
        if self._focus_debounce_id:
            try:
                self.after_cancel(self._focus_debounce_id)
            except Exception:
                pass
        self._focus_debounce_id = self.after(120, self._on_window_focus_debounced)

    def _on_window_focus_debounced(self) -> None:
        self._focus_debounce_id = None
        if self._is_downloading:
            return
        try:
            clip = self.clipboard_get().strip()
        except Exception:
            return
        if clip and clip != self._last_clipboard and is_valid_url(clip) and clip != self.url_entry.get().strip():
            self._last_clipboard = clip
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, clip)
            self._on_url_changed()
            if self._engine_ready:
                self._load_video_info()

    def _change_output_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.download_folder, parent=self)
        if selected:
            self.download_folder = selected
            self.lbl_folder.configure(text=format_folder_label(selected))
            self._save_current_config()

    def _open_output_folder(self) -> None:
        if Path(self.download_folder).is_dir():
            os.startfile(self.download_folder)

    def _kill_dl_process(self) -> None:
        """Mengakhiri proses download dengan aman."""
        proc = self._dl_process
        if not proc:
            return
        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=5
                )
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _cancel_download(self) -> None:
        """Sinyal pembatalan saat klik tombol batal."""
        self._cancel_event.set()
        self.btn_cancel.configure(state="disabled")
        self._update_status("Membatalkan unduhan...", 0.0, "0%", is_error=True)
        # Paksa kill proses segera di background thread agar readline() tidak
        # memblokir selamanya ketika yt-dlp berhenti menghasilkan output
        threading.Thread(target=self._kill_dl_process, daemon=True).start()

    # ── Dependency Management ─────────────────────────────────────────────────
    def _run_dependency_check(self) -> None:
        if engine_is_ready():
            self._engine_ready = True
            self._update_status("✅ Mesin utama siap. Masukkan URL untuk memulai.", 0.0, "0%", is_success=True)
            self._on_url_changed()
            return

        self._splash = SplashOverlay(self)
        self.btn_check_url.configure(state="disabled")
        threading.Thread(target=self._download_dependencies, daemon=True).start()

    def _dismiss_splash(self) -> None:
        if self._splash and not self._shutdown_event.is_set():
            self._splash.dismiss()
        self._splash = None

    @staticmethod
    def _fetch_file_to_disk(url: str, out_path: Path, shutdown_evt: threading.Event, progress_cb: Callable[[float, int, int], None]) -> bool:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                with open(out_path, "wb") as f:
                    while True:
                        if shutdown_evt.is_set():
                            break
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress_cb(downloaded / total_size, downloaded, total_size)
                        else:
                            progress_cb(0.0, downloaded, 0)
                if shutdown_evt.is_set():
                    out_path.unlink(missing_ok=True)
                    return False
            return True
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            log.error(f"Error downloading {url}: {exc}")
            out_path.unlink(missing_ok=True)
            raise RuntimeError(f"Gagal mengunduh: {exc}") from exc

    def _download_dependencies(self) -> None:
        url_ytdlp = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        url_ffmpeg = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        zip_path = DEPENDENCY_DIR / "ffmpeg_temp.zip"

        def _safe_splash(fn: Callable[[], None]) -> None:
            if self._splash and self.winfo_exists() and not self._shutdown_event.is_set():
                self.after(0, lambda f=fn: f() if self._splash and self.winfo_exists() else None)

        def update_splash(title: str, start_pct: float, end_pct: float, ratio: float, downloaded: int, total_bytes: int) -> None:
            if not self._splash or self._shutdown_event.is_set():
                return
            overall = start_pct + (end_pct - start_pct) * ratio
            pct_str = f"{int(overall * 100)}%"
            txt = f"📥 Mengunduh {title}... ({format_size(downloaded)} / {format_size(total_bytes)})" if total_bytes > 0 else f"📥 Mengunduh {title}... ({format_size(downloaded)})"
            _safe_splash(lambda: self._splash.set_status(txt, pct_str) if self._splash else None)
            _safe_splash(lambda: self._splash.set_progress(overall) if self._splash else None)

        try:
            _safe_splash(lambda: self._splash.switch_to_determinate() if self._splash else None)

            if not YTDLP_EXE.exists() or YTDLP_EXE.stat().st_size < 1_000_000:
                self._fetch_file_to_disk(
                    url_ytdlp, YTDLP_EXE, self._shutdown_event,
                    lambda r, d, t: update_splash("Mesin Inti", 0.0, 0.3, r, d, t),
                )
                if self._shutdown_event.is_set(): return
                if not YTDLP_EXE.exists() or YTDLP_EXE.stat().st_size < 1_000_000:
                    raise RuntimeError("File yt-dlp tidak lengkap.")
            else:
                _safe_splash(lambda: self._splash.set_progress(0.3) if self._splash else None)

            has_local_ffmpeg = (DEPENDENCY_DIR / "ffmpeg.exe").exists() and (DEPENDENCY_DIR / "ffprobe.exe").exists()
            if not shutil.which("ffmpeg") and not has_local_ffmpeg:
                self._fetch_file_to_disk(
                    url_ffmpeg, zip_path, self._shutdown_event,
                    lambda r, d, t: update_splash("Ekstensi Audio", 0.3, 0.8, r, d, t),
                )
                if self._shutdown_event.is_set():
                    zip_path.unlink(missing_ok=True)
                    return
                if not zip_path.exists() or zip_path.stat().st_size < 10_000_000:
                    raise RuntimeError("File FFmpeg tidak lengkap.")

                _safe_splash(lambda: self._splash.set_status("📦 Mengekstrak komponen mesin...", "85%") if self._splash else None)
                _safe_splash(lambda: self._splash.set_progress(0.85) if self._splash else None)

                try:
                    with zipfile.ZipFile(zip_path, "r") as zip_ref:
                        for member in zip_ref.infolist():
                            fname = member.filename.replace("\\", "/")
                            if "/bin/" in fname and fname.endswith((".exe", ".dll")):
                                dest_path = DEPENDENCY_DIR / Path(fname).name
                                with zip_ref.open(member) as src, open(dest_path, "wb") as dst:
                                    dst.write(src.read())
                except zipfile.BadZipFile as exc:
                    raise RuntimeError("File FFmpeg rusak.") from exc
                finally:
                    zip_path.unlink(missing_ok=True)
            else:
                _safe_splash(lambda: self._splash.set_progress(0.8) if self._splash else None)

            if self._shutdown_event.is_set(): return
            _safe_splash(lambda: self._splash.set_status("✅ Semua komponen siap!", "100%") if self._splash else None)
            _safe_splash(lambda: self._splash.set_progress(1.0) if self._splash else None)

            self._engine_ready = True
            if not self._shutdown_event.is_set() and self.winfo_exists():
                self.after(900, self._dismiss_splash)
                self.after(0, self._on_url_changed)
                self.after(0, lambda: self._update_status("✅ Sistem siap. Masukkan URL untuk memulai.", is_success=True))

        except Exception as exc:
            if YTDLP_EXE.exists() and YTDLP_EXE.stat().st_size < 1_000_000:
                YTDLP_EXE.unlink(missing_ok=True)
            zip_path.unlink(missing_ok=True)

            # _fetch_file_to_disk membungkus network error dalam RuntimeError,
            # sehingga perlu cek exc.__cause__ untuk mendeteksi error koneksi
            _cause = exc.__cause__ if isinstance(exc, RuntimeError) else exc
            is_conn_err = isinstance(_cause, (urllib.error.URLError, urllib.error.HTTPError, TimeoutError))
            err_msg = "❌ Koneksi gagal! Periksa internet lalu klik 'Perbarui Mesin'." if is_conn_err else f"❌ {str(exc)[:60]}"

            if not self._shutdown_event.is_set():
                _safe_splash(lambda: self._splash.set_status(err_msg, "0%") if self._splash else None)
                self.after(4000, self._dismiss_splash)
                self.after(0, lambda: self._update_status(err_msg, 0.0, "0%", is_error=True))

    def _update_engine(self) -> None:
        if self._is_downloading:
            self._update_status("⚠ Selesaikan unduhan terlebih dahulu.", 0.0, "0%", is_error=True)
            return
        if not YTDLP_EXE.exists():
            self._update_status("❌ Mesin yt-dlp belum terpasang.", 0.0, "0%", is_error=True)
            return

        self.btn_update_engine.configure(state="disabled", text="⏳ Memperbarui...")
        self._update_status("Mengunduh pembaruan mesin pengunduh...", 0.5, "50%")

        def run_update() -> None:
            try:
                res = subprocess.run(
                    [str(YTDLP_EXE), "-U"], capture_output=True, text=True,
                    encoding="utf-8", timeout=60, creationflags=CREATE_NO_WINDOW
                )
                if self._shutdown_event.is_set(): return
                stdout = (res.stdout or "").lower()
                
                if "up to date" in stdout:
                    if self.winfo_exists():
                        self.after(0, lambda: self._update_status("✅ Mesin sudah versi terbaru.", 1.0, "100%", is_success=True))
                elif res.returncode == 0:
                    if self.winfo_exists():
                        self.after(0, lambda: self._update_status("✅ Mesin diperbarui!", 1.0, "100%", is_success=True))
                else:
                    if self.winfo_exists():
                        self.after(0, lambda: self._update_status(f"⚠ Peringatan ({res.returncode})", 1.0, "100%", is_error=True))
            except Exception as exc:
                if not self._shutdown_event.is_set() and self.winfo_exists():
                    self.after(0, lambda m=str(exc)[:50]: self._update_status(f"❌ Gagal memperbarui: {m}", 0.0, "0%", is_error=True))
            finally:
                if not self._shutdown_event.is_set() and self.winfo_exists():
                    self.after(0, lambda: self.btn_update_engine.configure(state="normal", text="🔄 Perbarui Mesin"))

        threading.Thread(target=run_update, daemon=True).start()

    # ── Media Info Loading ────────────────────────────────────────────────────
    def _load_video_info(self) -> None:
        url = self.url_entry.get().strip()
        if not url or not self._engine_ready or self._is_downloading or not YTDLP_EXE.exists():
            return

        platform = detect_platform(url)
        if not platform:
            self._update_status("⚠ Platform tidak didukung.", 0.0, "0%", is_error=True)
            return

        self.current_platform = platform
        self.btn_check_url.configure(state="disabled", text="⏳ Mengecek...")
        self._update_status(f"🎬 Menganalisis stream dari {PLATFORM_LABELS[platform]}...", 0.2, "20%")

        fetch_mode = self.dl_mode
        fetch_token = self._info_fetch_token

        def _async_info() -> None:
            data, error = get_info(url, is_audio=(fetch_mode == "audio"))

            def _apply() -> None:
                if not self.winfo_exists():
                    return
                    
                _url_now = self.url_entry.get().strip()
                self.btn_check_url.configure(
                    state="normal" if (_url_now and self._engine_ready and not self._is_downloading) else "disabled",
                    text="Cek Media"
                )

                if fetch_token != self._info_fetch_token: return

                if error:
                    self._update_status(f"❌ {error[:90]}", 0.0, "0%", is_error=True)
                    self.lbl_info_title.configure(text=f"⚠ {error[:80]}", text_color=COLOR_TEXT_ERROR)
                    return

                if not data:
                    self._update_status("❌ Data media tidak valid.", 0.0, "0%", is_error=True)
                    return

                if fetch_mode == "video" and "available_resolutions" in data:
                    resolutions = data["available_resolutions"]
                    self._last_video_resolutions = resolutions
                    self.combo_res.configure(values=resolutions)
                    prev = self.combo_res.get()
                    self.combo_res.set(prev if prev in resolutions else resolutions[0])
                    self._update_quality_vars(self.combo_res.get())

                playlist_info = f" [{data['playlist_count']} video]" if data.get("playlist_count") else ""
                meta2 = (f"Codec Video : {data.get('vcodec', 'N/A')}   •   Codec Audio: {data.get('acodec', 'N/A')}"
                         if fetch_mode == "video" else
                         f"Audio Rate  : {data.get('asr', 'N/A')} Hz   •   Codec Audio: {data.get('acodec', 'N/A')}")

                targets = [
                    (self.lbl_info_title, f"Judul Konten : [{PLATFORM_LABELS.get(platform, platform)}] {data.get('title', 'Tidak diketahui')}{playlist_info}", True),
                    (self.lbl_info_channel, f"Uploader        : {data.get('channel', 'Tidak diketahui')}", False),
                    (self.lbl_info_meta1, f"Durasi  : {data.get('duration', '-')}   •   Diunggah: {data.get('upload_date', '-')}   •   Est. Ukuran: {data.get('size', '-')}", False),
                    (self.lbl_info_meta2, meta2, False),
                ]

                self._fade_version += 1
                self._fade_in_text(targets, 0, self._fade_version)
                self.current_info_url = url
                self._last_fetched_title = data.get("title")
                self._last_fetched_size = data.get("size")
                self._update_status("✅ Info siap. Klik tombol mulai.", 1.0, "100%", is_success=True)
                self._start_btn_download_enable()

            if not self._shutdown_event.is_set():
                self.after(0, _apply)

        threading.Thread(target=_async_info, daemon=True).start()

    # ── Download Handler ──────────────────────────────────────────────────────
    def _start_download(self) -> None:
        if not self.current_info_url or self._is_downloading:
            return

        self._is_downloading = True
        self._cancel_event.clear()
        self.target_progress = self.current_progress = 0.0
        self.progress_bar.set(0.0)
        self.lbl_percentage.configure(text="0%", text_color=COLOR_ACCENT)

        self.btn_download.configure(state="disabled", fg_color=COLOR_BTN_DISABLED_BG, text_color=COLOR_BTN_DISABLED_FG)
        self.btn_check_url.configure(state="disabled")
        self.btn_cancel.configure(state="normal")

        url, folder, dl_mode = self.current_info_url, self.download_folder, self.dl_mode
        title_cache = self._last_fetched_title
        
        # --no-colors mencegah ANSI escape codes merusak regex parser progress
        # --playlist-items 1 menggantikan --no-playlist: aman untuk URL video biasa
        # maupun URL playlist murni (yang lolos validasi regex & get_info)
        cmd = [str(YTDLP_EXE), "--newline", "--no-warnings", "--playlist-items", "1", "--no-colors"]

        if ffmpeg_loc := get_ffmpeg_location():
            cmd.extend(["--ffmpeg-location", ffmpeg_loc])

        if dl_mode == "video":
            cmd.extend([
                "-f", self.vformat, 
                "--windows-filenames",
                "-o", str(Path(folder) / "%(uploader).20s - %(title).40s [%(height)sp].%(ext)s")
            ])
            if self.container != "auto":
                cmd.extend(["--merge-output-format", self.container])
        else:
            cmd.extend([
                "-f", "ba/b", 
                "--windows-filenames",
                "-o", str(Path(folder) / "%(uploader).20s - %(title).40s.%(ext)s"),
                "--convert-thumbnails", "jpg", 
                "--embed-thumbnail", 
                "--embed-metadata",
                "--extract-audio", 
                "--audio-format", "mp3", 
                "--audio-quality", self.aquality,
            ])
        cmd.append(url)

        def _run_dl() -> None:
            if self.winfo_exists() and not self._shutdown_event.is_set():
                self.after(0, lambda: self._update_status("Menyiapkan instruksi unduhan...", 0.0, "0%"))

            try:
                self._dl_process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="ignore", creationflags=CREATE_NO_WINDOW
                )

                last_progress = 0.0
                if self._dl_process.stdout:
                    for line in iter(self._dl_process.stdout.readline, ""):
                        if self._cancel_event.is_set() or self._shutdown_event.is_set():
                            self._kill_dl_process()
                            break

                        line = line.strip()
                        if "[download]" in line and "%" in line:
                            match = re.search(r"(\d+\.?\d*)%", line)
                            if match:
                                val = float(match.group(1))
                                last_progress = val / 100

                                # Ekstraksi total ukuran dengan lebih kokoh (menangani variasi yt-dlp)
                                size_match = re.search(
                                    r"\bof\s+~?\s*([\d.]+(?:TiB|GiB|MiB|KiB|TB|GB|MB|KB|B))", line, re.IGNORECASE
                                )
                                total_bytes = (
                                    _parse_ytdlp_size(size_match.group(1)) if size_match else None
                                )

                                speed_raw = line.split(" at ", 1)[1].strip() if " at " in line else ""
                                speed = speed_raw.split(" ETA ")[0].strip() if " ETA " in speed_raw else speed_raw

                                parts: list[str] = ["🎬 Mengunduh"]
                                if total_bytes:
                                    dl_bytes = last_progress * total_bytes
                                    dl_str = "0 B" if dl_bytes <= 0 else format_size(dl_bytes)
                                    parts.append(f"{dl_str} / {format_size(total_bytes)}")
                                if speed:
                                    parts.append(speed)
                                status = " • ".join(parts) if len(parts) > 1 else "🎬 Mengunduh..."

                                if not self._shutdown_event.is_set() and self.winfo_exists():
                                    self.after(0, lambda v=last_progress, p=f"{int(val)}%", s=status: self._update_status(s, v, p))
                        
                        elif line.startswith(("[Merger]", "[ExtractAudio]")):
                            msg = "⚙️ Menggabungkan video & audio..." if dl_mode == "video" else "⚙️ Mengonversi ke MP3..."
                            if not self._shutdown_event.is_set() and self.winfo_exists():
                                self.after(0, lambda m=msg: self._update_status(m, max(0.95, self.target_progress), "99%"))

                try:
                    self._dl_process.wait(timeout=10.0)
                except subprocess.TimeoutExpired:
                    self._kill_dl_process()
                    try:
                        self._dl_process.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        pass

                if self._cancel_event.is_set():
                    time.sleep(1.5) # Beri nafas untuk I/O write sebelum unlink part files
                    cleanup_partial_files(folder)
                    if not self._shutdown_event.is_set() and self.winfo_exists():
                        self.after(0, lambda: self._update_status("⛔ Unduhan dibatalkan.", 0.0, "0%", is_error=True))
                
                elif self._dl_process.returncode == 0:
                    self.download_count += 1
                    if not self._shutdown_event.is_set() and self.winfo_exists():
                        self.after(0, self._save_current_config)
                        self.after(0, self._trigger_counter_flash)

                    notif_msg = f"Tersimpan: {(title_cache or '')[:50]}"
                    try:
                        icon_path = _resource_path("icon.ico")
                    except Exception:
                        icon_path = None
                    send_toast("FetchDrop ✅", notif_msg, icon_path)

                    if not self._shutdown_event.is_set() and self.winfo_exists():
                        self.after(0, lambda: self._update_status("✅ Berkas berhasil disimpan.", 1.0, "100%", is_success=True))
                else:
                    rc = self._dl_process.returncode
                    err_msg = ("❌ Gagal: Video privat/dihapus." if rc in (1, 101) else
                               "❌ Gagal: URL tidak valid." if rc == 2 else
                               f"❌ Gagal (Kode {rc}). Coba Perbarui Mesin.")
                    if not self._shutdown_event.is_set() and self.winfo_exists():
                        self.after(0, lambda m=err_msg: self._update_status(m, 0.0, "0%", is_error=True))

            except Exception as exc:
                if not self._shutdown_event.is_set() and self.winfo_exists():
                    self.after(0, lambda m=str(exc)[:60]: self._update_status(f"❌ Error: {m}", 0.0, "0%", is_error=True))
            finally:
                self._is_downloading = False
                self._dl_process = None
                if not self._shutdown_event.is_set() and self.winfo_exists():
                    self.after(0, self._start_btn_download_enable)
                    self.after(0, self._on_url_changed)
                    self.after(0, lambda: self.btn_cancel.configure(state="disabled"))

        threading.Thread(target=_run_dl, daemon=True).start()

# ── Entry Point ───────────────────────────────────────────────────────────────
def main() -> None:
    if not _ensure_single_instance():
        _show_instance_warning()
        sys.exit(0)
    app = FetchDropApp()
    app.mainloop()

if __name__ == "__main__":
    main()