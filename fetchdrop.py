import os
import re
import sys
import json
import time
import base64
import shutil
import logging
import threading
import subprocess
import urllib.request
import zipfile
from typing import Any, Callable, Optional, Tuple, List, Dict
from pathlib import Path
from datetime import datetime
from tkinter import filedialog, messagebox
from logging.handlers import RotatingFileHandler

import customtkinter as ctk

# Pengecekan OS untuk msvcrt (Fitur Single Instance Windows)
if sys.platform == "win32":
    import msvcrt

# =====================================================
#   KONFIGURASI TEMA WARNA & UI
# =====================================================
ctk.set_appearance_mode("Dark")

COLOR_BG = "#0A0A0C"
COLOR_SIDEBAR = "#111113"
COLOR_CARD = "#16161A"
COLOR_ACCENT = "#E50914"
COLOR_ACCENT_HOV = "#B80710"
COLOR_BORDER = "#222226"
TEXT_MAIN = "#F3F4F6"
TEXT_MUTED = "#9CA3AF"

# =====================================================
#   PATH & DEPENDENSI ENGINE
# =====================================================
DEPENDENCY_DIR = Path.home() / ".fetchdrop_engine"
CONFIG_FILE = DEPENDENCY_DIR / ".fetchdrop_config.json"
HISTORY_FILE = DEPENDENCY_DIR / ".fetchdrop_history.json"
YTDLP_EXE = DEPENDENCY_DIR / "yt-dlp.exe"
LOG_FILE = DEPENDENCY_DIR / "fetchdrop.log"

_LOCK_FILE_HANDLE = None

def _check_single_instance() -> bool:
    """Mencegah aplikasi berjalan lebih dari satu instance di Windows."""
    if sys.platform != "win32":
        return True
    
    global _LOCK_FILE_HANDLE
    lock_path = DEPENDENCY_DIR / "fetchdrop.lock"
    DEPENDENCY_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        _LOCK_FILE_HANDLE = open(lock_path, "w")
        msvcrt.locking(_LOCK_FILE_HANDLE.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False

def _setup_logging() -> None:
    """Menyiapkan logging menggunakan RotatingFileHandler."""
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

def _get_app_basedir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def _meipass(*parts) -> Path:
    return _get_app_basedir().joinpath(*parts)

# Konstanta untuk menyembunyikan jendela CMD subprocess di Windows
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

# =====================================================
#   KONFIGURASI PERSISTENT & RIWAYAT UNDUHAN
# =====================================================
def load_config() -> Dict[str, Any]:
    default = {
        "download_folder": str(Path.home() / "Downloads"),
        "last_quality":    "Best",
        "last_container":  "Format Asli",
        "last_mode":       "video",
        "download_count":  0,
    }
    
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    default.update(data)
    except Exception as e:
        log.warning(f"Gagal memuat config: {e}")

    if not Path(default["download_folder"]).is_dir():
        default["download_folder"] = str(Path.home() / "Downloads")
    return default

def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        log.error(f"Gagal menyimpan config: {exc}")

def load_history() -> List[Dict[str, Any]]:
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception as e:
        log.warning(f"Gagal memuat riwayat: {e}")
    return []

def save_history(history: List[Dict[str, Any]]) -> None:
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-100:], f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.warning(f"Gagal menyimpan riwayat: {e}")

_history_lock = threading.Lock()

def append_history(entry: Dict[str, Any]) -> None:
    with _history_lock:
        history = load_history()
        history.append(entry)
        save_history(history)

def format_folder_label(path: str) -> str:
    try:
        rel = os.path.relpath(path, Path.home())
        display = os.path.join("~", rel) if not rel.startswith("..") else path
    except ValueError:
        display = path

    if len(display) > 48:
        parts = display.replace("\\", "/").split("/")
        display = ".../" + "/".join(parts[-2:]) if len(parts) >= 2 else "..." + display[-45:]
    return f"📁 {display}"


# =====================================================
#   VALIDASI & FORMAT MEDIA
# =====================================================
_PLATFORM_PATTERNS = {
    "youtube":   re.compile(r"(https?://)?(www\.)?(youtube\.com/(watch|shorts|playlist|embed|live)|youtu\.be/|music\.youtube\.com/watch)"),
    "tiktok":    re.compile(r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/(@[\w.]+/video/\d{10,}|v/\d{10,}|t/\w{8,}|\w{6,}/?)"),
    "instagram": re.compile(r"(https?://)?(www\.)?instagram\.com/(p|reel|tv)/[\w-]+"),
    "x":         re.compile(r"(https?://)?(www\.)?(twitter\.com|x\.com)/\w+/status/\d+"),
}

PLATFORM_LABELS = {
    "youtube": "YouTube", 
    "tiktok": "TikTok", 
    "instagram": "Instagram", 
    "x": "X / Twitter",
}

VIDEO_QUALITY_OPTIONS = ["Best", "4K (2160p)", "2K (1440p)", "1080p", "720p", "480p", "360p"]
AUDIO_QUALITY_OPTIONS = ["320 kbps", "192 kbps", "128 kbps"]

_RES_FORMAT_MAP = {
    "Best":       "bv*+ba/b",
    "360p":       "bv*[height<=360]+ba/b[height<=360]/b",
    "480p":       "bv*[height<=480]+ba/b[height<=480]/b",
    "720p":       "bv*[height<=720]+ba/b[height<=720]/b",
    "1080p":      "bv*[height<=1080]+ba/b[height<=1080]/b",
    "2K (1440p)": "bv*[height<=1440]+ba/b[height<=1440]/b",
    "4K (2160p)": "bv*[height<=2160]+ba/b[height<=2160]/b",
}

_AUDIO_QUALITY_MAP = {"320 kbps": "320k", "192 kbps": "192k", "128 kbps": "128k"}

_RES_MAP_LABELS = [
    (2160, "4K (2160p)"), (1440, "2K (1440p)"), (1080, "1080p"),
    (720, "720p"), (480, "480p"), (360, "360p"),
]

def detect_platform(url: str) -> Optional[str]:
    for name, pattern in _PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return None

def is_valid_url(url: str) -> bool:
    return detect_platform(url) is not None

def format_size(bytes_value: Any) -> str:
    if not bytes_value or bytes_value in ("NA", "0", 0):
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

def shorten_codec(codec: Optional[str], max_len: int = 10) -> str:
    if not codec or codec == "none": 
        return "N/A"
    return codec.split(".")[0][:max_len]


# =====================================================
#   NOTIFIKASI WINDOWS TOAST (DENGAN DUKUNGAN IKON)
# =====================================================
def send_toast(title: str, message: str, icon_path: Optional[Path] = None) -> None:
    """Mengirimkan notifikasi sistem Windows menggunakan PowerShell."""
    def _notify() -> None:
        try:
            template_type = "ToastText02"
            icon_injection = ""
            
            # Deteksi ketersediaan ikon, ubah template jika eksis
            if icon_path and icon_path.exists():
                template_type = "ToastImageAndText02"
                icon_uri = f"file:///{icon_path.absolute().as_posix()}"
                icon_injection = f"$template.GetElementsByTagName('image')[0].SetAttribute('src', '{icon_uri}') | Out-Null;"

            # Eskapasi tanda petik tunggal untuk mencegah PowerShell Parser Error
            escaped_title = title.replace("'", "''")
            escaped_message = message.replace("'", "''")

            ps_script = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
                f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::{template_type});"
                f"$template.GetElementsByTagName('text')[0].AppendChild($template.CreateTextNode('{escaped_title}')) | Out-Null;"
                f"$template.GetElementsByTagName('text')[1].AppendChild($template.CreateTextNode('{escaped_message}')) | Out-Null;"
                f"{icon_injection}"
                "$toast = [Windows.UI.Notifications.ToastNotification]::new($template);"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('FetchDrop').Show($toast);"
            )
            
            encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
                creationflags=CREATE_NO_WINDOW, timeout=5, capture_output=True,
            )
        except Exception as e:
            log.warning(f"Gagal mengirim toast: {e}")
            
    threading.Thread(target=_notify, daemon=True).start()


# =====================================================
#   CLEANUP & VALIDASI MESIN
# =====================================================
def _cleanup_partial_files(folder: str) -> None:
    """Hapus sisa file parsial yang ditinggalkan mesin setelah pembatalan."""
    partial_suffixes = (".part", ".ytdl", ".temp")
    fstream_re = re.compile(r"\.f\d{2,5}\.(mp4|m4a|webm|opus|ogg|ts|aac|flac|wav|vtt)$", re.IGNORECASE)

    def _try_remove(path: str, name: str, max_retries: int = 6) -> None:
        for attempt in range(max_retries):
            try:
                os.remove(path)
                log.info(f"Cleanup: dihapus '{name}'")
                return
            except PermissionError:
                if attempt < max_retries - 1:
                    time.sleep(0.3 * (2 ** attempt))
            except FileNotFoundError:
                return 
            except OSError as exc:
                log.warning(f"Cleanup: gagal hapus '{name}' — {exc}")
                return

    try:
        entries_snapshot = list(os.scandir(folder))
    except OSError as exc:
        log.warning(f"Cleanup: gagal scan folder '{folder}' — {exc}")
        return

    for entry in entries_snapshot:
        if not entry.is_file(follow_symlinks=False): 
            continue
        
        name = entry.name
        if name.endswith(partial_suffixes) or ".part-Frag" in name or bool(fstream_re.search(name)):
            _try_remove(entry.path, name)

def engine_is_ready() -> bool:
    has_ytdlp = YTDLP_EXE.exists() and YTDLP_EXE.stat().st_size >= 1_000_000
    has_ffmpeg = bool(shutil.which("ffmpeg") or (
        (DEPENDENCY_DIR / "ffmpeg.exe").exists() and (DEPENDENCY_DIR / "ffprobe.exe").exists()
    ))
    return has_ytdlp and has_ffmpeg

def get_ffmpeg_location() -> Optional[str]:
    return None if shutil.which("ffmpeg") else str(DEPENDENCY_DIR)


# =====================================================
#   LOGIKA UTAMA METADATA STRIPPER
# =====================================================
def get_info(url: str, is_audio: bool = False) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Mengambil informasi streaming media secara aman (terbatas 1 item jika playlist)."""
    cmd = [
        str(YTDLP_EXE), "-J", "--no-warnings", 
        "--socket-timeout", "15", "--playlist-items", "1"
    ]
    
    ffmpeg_loc = get_ffmpeg_location()
    if ffmpeg_loc:
        cmd.extend(["--ffmpeg-location", ffmpeg_loc])
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=30, creationflags=CREATE_NO_WINDOW
        )
        
        if result.returncode != 0:
            return None, "Video bersifat privat, tidak ditemukan, atau diblokir oleh platform."

        info = json.loads(result.stdout)
        playlist_count: Optional[int] = None
        
        # Ekstrak jumlah playlist yang benar dari objek root sebelum terpotong oleh --playlist-items
        if "entries" in info:
            playlist_count = info.get("playlist_count") or info.get("entry_count")
            entries = [e for e in (info.get("entries") or []) if e]
            if not playlist_count and entries:
                playlist_count = len(entries)
            if not entries: 
                return None, "Playlist kosong."
            info = entries[0]

        filesize = info.get("filesize")
        size_raw = filesize if filesize is not None else (info.get("filesize_approx") or "NA")

        available_resolutions = ["Best"]
        seen_heights = sorted(
            {f.get("height") for f in info.get("formats", [])
             if f.get("height") and f.get("vcodec") and f.get("vcodec") != "none"
             and "storyboard" not in str(f.get("format_note", "")).lower()}, reverse=True
        )
        
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

        data = {
            "title":                 info.get("title", "Unknown"),
            "channel":               info.get("channel") or info.get("uploader", "Unknown"),
            "duration":              info.get("duration_string", "Unknown"),
            "upload_date":           upload_date,
            "size":                  format_size(size_raw),
            "acodec":                shorten_codec(info.get("acodec")),
            "playlist_count":        playlist_count,
            "available_resolutions": available_resolutions,
        }

        if not is_audio:
            data["resolution"] = info.get("resolution", "Unknown")
            data["vcodec"] = shorten_codec(info.get("vcodec"))
        else:
            asr = info.get("asr")
            data["asr"] = f"{asr:,}" if isinstance(asr, (int, float)) else "Unknown"

        return data, None
        
    except subprocess.TimeoutExpired:
        return None, "Waktu habis (timeout 30 detik)."
    except json.JSONDecodeError:
        return None, "Respons dari mesin rusak. Coba Update Engine."
    except Exception as e:
        log.warning(f"get_info err: {e}")
        return None, str(e)


# =====================================================
#   SPLASH SCREEN FRAME
# =====================================================
class SplashOverlay(ctk.CTkFrame):
    def __init__(self, parent: ctk.CTk):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self.lift()
        
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(inner, text="⚡ FetchDrop", font=("Segoe UI", 40, "bold"), text_color=TEXT_MAIN).pack(pady=(0, 4))
        ctk.CTkLabel(inner, text="Menyiapkan mesin pengunduh — hanya dilakukan sekali.", font=("Segoe UI", 11), text_color=TEXT_MUTED).pack(pady=(0, 36))
        
        self._bar = ctk.CTkProgressBar(inner, width=360, height=5, progress_color=COLOR_ACCENT, fg_color="#1A1A1E", mode="indeterminate")
        self._bar.pack(pady=(0, 10))
        self._bar.start()

        self._lbl_pct = ctk.CTkLabel(inner, text="", font=("Segoe UI", 12, "bold"), text_color=COLOR_ACCENT, width=360, anchor="e")
        self._lbl_pct.pack()
        
        self._lbl_status = ctk.CTkLabel(inner, text="Memeriksa komponen sistem...", font=("Segoe UI", 11), text_color=TEXT_MUTED, width=360, anchor="w")
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
        if self.winfo_exists(): 
            self.destroy()


# =====================================================
#   APLIKASI UTAMA (YTDOWNLOADERAPP)
# =====================================================
class YTDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FetchDrop – Social Media Downloader")
        self.geometry("860x560")
        self.minsize(860, 560)
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG)

        try:
            icon_p = _meipass("icon.ico")
            if icon_p.exists(): 
                self.iconbitmap(str(icon_p))
        except Exception:
            pass

        cfg = load_config()
        self.download_count: int = cfg.get("download_count", 0)
        self.download_folder: str = cfg["download_folder"]
        self.current_info_url: Optional[str] = None
        self.current_platform: Optional[str] = None
        self._last_fetched_title: Optional[str] = None
        self._last_fetched_size: Optional[str] = None
        self.dl_mode: str = cfg.get("last_mode", "video")
        
        self._cancel_event = threading.Event()
        self._shutdown_event = threading.Event()
        self._is_downloading: bool = False
        self._dl_process: Optional[subprocess.Popen] = None
        self._splash: Optional[SplashOverlay] = None

        self.vformat: str = "bv*+ba/b"
        self.container: str = "auto"
        self.aquality: str = "320k"
        self._last_video_resolutions: Optional[List[str]] = None
        
        self._fade_version: int = 0
        self._info_fetch_token: int = 0
        self.current_progress: float = 0.0
        self.target_progress: float = 0.0
        self._anim_id: Optional[str] = None
        self._is_animating_progress: bool = False

        self.fonts = {
            "nav_bold":      ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            "nav_reg":       ctk.CTkFont(family="Segoe UI", size=12),
            "header":        ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            "label_bold":    ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            "label_reg":     ctk.CTkFont(family="Segoe UI", size=12),
            "label_sm":      ctk.CTkFont(family="Segoe UI", size=11),
            "label_sm_bold": ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            "label_xs":      ctk.CTkFont(family="Segoe UI", size=10),
            "label_xs_bold": ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            "label_9_bold":  ctk.CTkFont(family="Segoe UI", size=9,  weight="bold"),
            "btn_main":      ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            "btn_sm":        ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            "btn_xs":        ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            "counter":       ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            "logo":          ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            "icon_lg":       ctk.CTkFont(family="Segoe UI", size=18),
            "icon_md":       ctk.CTkFont(family="Segoe UI", size=13),
        }

        self._sidebar_anim_id: Optional[str] = None
        self._focus_debounce_id: Optional[str] = None

        self._setup_layout()
        self._apply_saved_config(cfg)
        self._run_dependency_check()

        self.bind("<Control-v>", self._on_ctrl_v)
        self._last_clipboard: str = ""
        self.bind("<FocusIn>", self._on_window_focus)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

    def _on_close_request(self) -> None:
        if self._anim_id:
            self.after_cancel(self._anim_id)
        if self._sidebar_anim_id:
            self.after_cancel(self._sidebar_anim_id)
        if self._focus_debounce_id:
            self.after_cancel(self._focus_debounce_id)

        if self._is_downloading:
            if not messagebox.askyesno(
                "Unduhan Sedang Berjalan",
                "Menutup aplikasi akan membatalkan unduhan yang berjalan.\nYakin ingin keluar?",
                icon="warning", parent=self
            ):
                return

        self._shutdown_event.set()
        self._cancel_event.set()
        self._kill_dl_process()
        self._save_current_config()
        self.destroy()

    # =====================================================
    #   LAYOUT GEOMETRY SYSTEM
    # =====================================================
    def _setup_layout(self) -> None:
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main_content()
        self._build_history_panel()

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=COLOR_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(self.sidebar, text="⚡ FetchDrop", font=self.fonts["logo"], text_color=TEXT_MAIN).grid(row=0, column=0, padx=24, pady=(32, 2), sticky="w")
        ctk.CTkLabel(self.sidebar, text="Stable Engine", font=self.fonts["label_xs_bold"], text_color=TEXT_MUTED).grid(row=1, column=0, padx=24, pady=(0, 36), sticky="w")
        ctk.CTkLabel(self.sidebar, text="KATEGORI UNDUHAN", font=self.fonts["label_xs_bold"], text_color="#4B4B54").grid(row=2, column=0, padx=24, pady=(0, 8), sticky="w")

        self.btn_mode_video = ctk.CTkButton(self.sidebar, text="🎬  Video Downloader", anchor="w", height=38, fg_color=COLOR_ACCENT, text_color=TEXT_MAIN, font=self.fonts["nav_bold"], hover_color=COLOR_ACCENT_HOV, command=lambda: self._select_sidebar_mode("video"))
        self.btn_mode_video.grid(row=3, column=0, padx=16, pady=4, sticky="ew")

        self.btn_mode_audio = ctk.CTkButton(self.sidebar, text="🎵  Audio MP3 Extractor", anchor="w", height=38, fg_color="transparent", text_color=TEXT_MUTED, font=self.fonts["nav_reg"], hover_color="#1D1D21", command=lambda: self._select_sidebar_mode("audio"))
        self.btn_mode_audio.grid(row=4, column=0, padx=16, pady=4, sticky="ew")

        self.btn_mode_history = ctk.CTkButton(self.sidebar, text="🕓  Riwayat Unduhan", anchor="w", height=38, fg_color="transparent", text_color=TEXT_MUTED, font=self.fonts["nav_reg"], hover_color="#1D1D21", command=lambda: self._select_sidebar_mode("history"))
        self.btn_mode_history.grid(row=5, column=0, padx=16, pady=4, sticky="ew")

        self.sidebar.grid_rowconfigure(6, weight=1)
        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer.grid(row=6, column=0, sticky="ews", padx=24, pady=24)

        ctk.CTkLabel(footer, text="TOTAL BERKAS TERUNDUH", font=self.fonts["label_9_bold"], text_color="#4B4B54").pack(anchor="w")
        counter_row = ctk.CTkFrame(footer, fg_color="transparent")
        counter_row.pack(anchor="w", pady=(2, 0), fill="x")

        self.lbl_stats_counter = ctk.CTkLabel(counter_row, text=f"{self.download_count} Files", font=self.fonts["counter"], text_color=COLOR_ACCENT)
        self.lbl_stats_counter.pack(side="left")

        self.btn_reset_count = ctk.CTkButton(counter_row, text="↺", width=26, height=26, fg_color="transparent", hover_color="#1E1E22", text_color="#4B4B54", font=self.fonts["icon_md"], command=self._do_reset_count)
        self.btn_reset_count.pack(side="left", padx=(6, 0), pady=(2, 0))

        self.btn_update_engine = ctk.CTkButton(footer, text="🔄 Update Engine", height=28, fg_color="#1E1E22", hover_color="#25252A", text_color=TEXT_MUTED, font=self.fonts["btn_xs"], command=self._update_engine)
        self.btn_update_engine.pack(anchor="w", pady=(16, 0), fill="x")

    def _build_main_content(self) -> None:
        self.main_content = ctk.CTkFrame(self, fg_color="transparent")
        self.main_content.grid(row=0, column=1, padx=28, pady=28, sticky="nsew")
        self.main_content.grid_columnconfigure(0, weight=1)

        self.lbl_header_title = ctk.CTkLabel(self.main_content, text="🎬  Video Stream Downloader", font=self.fonts["header"], text_color=TEXT_MAIN)
        self.lbl_header_title.grid(row=0, column=0, sticky="w", pady=(0, 16))

        input_card = ctk.CTkFrame(self.main_content, height=52, fg_color=COLOR_CARD, border_color=COLOR_BORDER, border_width=1)
        input_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        input_card.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(input_card, placeholder_text="Tempel tautan video di sini...", height=52, fg_color="transparent", border_width=0, font=self.fonts["label_reg"])
        self.url_entry.grid(row=0, column=0, padx=(16, 8), sticky="ew")
        self.url_entry.bind("<Return>", lambda _: self._on_enter_url())

        actions = ctk.CTkFrame(input_card, fg_color="transparent")
        actions.grid(row=0, column=1, padx=(0, 8), sticky="e")

        ctk.CTkButton(actions, text="✕", width=34, height=34, fg_color="#1E1E22", hover_color="#3A1A1A", text_color="#FF6B6B", font=self.fonts["label_sm_bold"], command=self._clear_url).pack(side="left", padx=3)
        ctk.CTkButton(actions, text="📋", width=34, height=34, fg_color="#1E1E22", hover_color="#25252A", text_color=TEXT_MAIN, font=self.fonts["label_sm_bold"], command=self._paste_url).pack(side="left", padx=3)
        self.btn_check_url = ctk.CTkButton(actions, text="Cek Media", width=90, height=34, fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOV, font=self.fonts["btn_sm"], command=self._load_video_info)
        self.btn_check_url.pack(side="left", padx=(6, 0))

        info_card = ctk.CTkFrame(self.main_content, fg_color=COLOR_CARD, border_color=COLOR_BORDER, border_width=1)
        info_card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        
        self.lbl_info_title = ctk.CTkLabel(info_card, text="Judul Konten : -", font=self.fonts["label_bold"], text_color="#3A3A40", anchor="w", wraplength=540)
        self.lbl_info_title.grid(row=0, column=0, padx=18, pady=(16, 4), sticky="ew")
        self.lbl_info_channel = ctk.CTkLabel(info_card, text="Uploader     : -", font=self.fonts["label_reg"], text_color="#3A3A40", anchor="w")
        self.lbl_info_channel.grid(row=1, column=0, padx=18, pady=4, sticky="ew")
        self.lbl_info_meta1 = ctk.CTkLabel(info_card, text="Durasi  : -   •   Rilis: -   •   Est. Ukuran: -", font=self.fonts["label_reg"], text_color="#3A3A40", anchor="w")
        self.lbl_info_meta1.grid(row=2, column=0, padx=18, pady=4, sticky="ew")
        self.lbl_info_meta2 = ctk.CTkLabel(info_card, text="Codec Video : -   •   Codec Audio: -", font=self.fonts["label_reg"], text_color="#3A3A40", anchor="w")
        self.lbl_info_meta2.grid(row=3, column=0, padx=18, pady=(4, 16), sticky="ew")

        config_card = ctk.CTkFrame(self.main_content, height=56, fg_color=COLOR_CARD, border_color=COLOR_BORDER, border_width=1)
        config_card.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        config_card.grid_columnconfigure((1, 3), weight=1)

        self.lbl_res = ctk.CTkLabel(config_card, text="Kualitas Video:", font=self.fonts["label_reg"])
        self.lbl_res.grid(row=0, column=0, padx=(18, 12), pady=12, sticky="w")
        self.combo_res = ctk.CTkComboBox(config_card, values=VIDEO_QUALITY_OPTIONS, width=145, height=32, fg_color=COLOR_BG, border_color=COLOR_BORDER, button_color="#1E1E22", state="readonly", command=self._update_quality_vars)
        self.combo_res.grid(row=0, column=1, pady=12, sticky="w")

        self.lbl_container = ctk.CTkLabel(config_card, text="Format Container:", font=self.fonts["label_reg"])
        self.lbl_container.grid(row=0, column=2, padx=(24, 12), pady=12, sticky="w")
        self.combo_container = ctk.CTkComboBox(config_card, values=["Format Asli", "MP4", "MKV"], width=145, height=32, fg_color=COLOR_BG, border_color=COLOR_BORDER, button_color="#1E1E22", state="readonly", command=self._update_container_vars)
        self.combo_container.grid(row=0, column=3, pady=12, sticky="w")

        status_zone = ctk.CTkFrame(self.main_content, fg_color="transparent")
        status_zone.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        status_zone.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(status_zone, text="Menunggu instruksi tautan...", font=self.fonts["label_sm"], text_color=TEXT_MUTED, anchor="w")
        self.lbl_status.grid(row=0, column=0, sticky="w")
        self.lbl_percentage = ctk.CTkLabel(status_zone, text="0%", font=self.fonts["icon_md"], text_color=COLOR_ACCENT)
        self.lbl_percentage.grid(row=0, column=1, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(self.main_content, progress_color=COLOR_ACCENT, fg_color="#1F1F24", height=4)
        self.progress_bar.grid(row=5, column=0, sticky="ew", pady=(6, 24))
        self.progress_bar.set(0)

        action_bar = ctk.CTkFrame(self.main_content, fg_color="transparent")
        action_bar.grid(row=6, column=0, sticky="ew")
        action_bar.grid_columnconfigure(0, weight=1)

        self.lbl_folder = ctk.CTkLabel(action_bar, text=format_folder_label(self.download_folder), font=self.fonts["label_sm"], text_color=TEXT_MUTED, cursor="hand2")
        self.lbl_folder.grid(row=0, column=0, sticky="w")
        self.lbl_folder.bind("<Button-1>", lambda _: self._open_output_folder())
        self.lbl_folder.bind("<Enter>", lambda _: self.lbl_folder.configure(text_color=TEXT_MAIN))
        self.lbl_folder.bind("<Leave>", lambda _: self.lbl_folder.configure(text_color=TEXT_MUTED))

        controls_right = ctk.CTkFrame(action_bar, fg_color="transparent")
        controls_right.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(controls_right, text="Ubah Folder", width=90, height=34, fg_color=COLOR_CARD, hover_color="#1E1E22", border_color=COLOR_BORDER, border_width=1, command=self._change_output_folder).pack(side="left", padx=4)
        self.btn_cancel = ctk.CTkButton(controls_right, text="Batal", width=75, height=34, fg_color="transparent", text_color="#FFA4A4", hover_color="#2A1418", border_width=1, border_color="#3A1C20", state="disabled", command=self._cancel_download)
        self.btn_cancel.pack(side="left", padx=4)
        self.btn_download = ctk.CTkButton(controls_right, text="⬇  DOWNLOAD VIDEO", width=155, height=34, fg_color="#1E1E22", text_color="#55555F", font=self.fonts["btn_main"], state="disabled", command=self._start_download)
        self.btn_download.pack(side="left", padx=(8, 0))

    def _build_history_panel(self) -> None:
        self.history_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.history_panel.grid(row=0, column=1, padx=28, pady=28, sticky="nsew")
        self.history_panel.grid_columnconfigure(0, weight=1)
        self.history_panel.grid_rowconfigure(1, weight=1)
        self.history_panel.grid_remove()

        header_row = ctk.CTkFrame(self.history_panel, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        header_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(header_row, text="🕓  Riwayat Unduhan", font=self.fonts["header"]).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header_row, text="🗑 Hapus Semua", width=110, height=28, fg_color="#1E1E22", text_color="#FF6B6B", hover_color="#3A1A1A", command=self._clear_history).grid(row=0, column=1, sticky="e")

        self.history_scroll = ctk.CTkScrollableFrame(self.history_panel, fg_color=COLOR_CARD, border_color=COLOR_BORDER, border_width=1)
        self.history_scroll.grid(row=1, column=0, sticky="nsew")
        self.history_scroll.grid_columnconfigure(0, weight=1)

    def _refresh_history_panel(self) -> None:
        for widget in self.history_scroll.winfo_children(): 
            widget.destroy()
            
        history = load_history()
        if not history:
            ctk.CTkLabel(self.history_scroll, text="Belum ada riwayat unduhan.", font=self.fonts["label_reg"], text_color="#3A3A40").pack(pady=40)
            return
            
        for entry in reversed(history): 
            self._build_history_row(entry)

    def _build_history_row(self, entry: Dict[str, Any]) -> None:
        folder_path = entry.get("folder", "")
        row_frame = ctk.CTkFrame(self.history_scroll, fg_color="#1A1A1E", border_color=COLOR_BORDER, border_width=1)
        row_frame.pack(fill="x", padx=6, pady=4)
        row_frame.grid_columnconfigure(1, weight=1)

        def _on_enter(e, f=row_frame): f.configure(fg_color="#222228")
        def _on_leave(e, f=row_frame): f.configure(fg_color="#1A1A1E")
        def _on_click(e, p=folder_path):
            if p and Path(p).is_dir(): 
                os.startfile(p)

        row_frame.bind("<Enter>", _on_enter)
        row_frame.bind("<Leave>", _on_leave)
        
        if folder_path and Path(folder_path).is_dir():
            row_frame.bind("<Button-1>", _on_click)
            row_frame.configure(cursor="hand2")

        icon_text = "🎬" if entry.get("mode") == "video" else "🎵"
        lbl_icon = ctk.CTkLabel(row_frame, text=icon_text, font=self.fonts["icon_lg"], width=36)
        lbl_icon.grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=12)
        
        title_text = entry.get("title", "Unknown")[:67] + ("..." if len(entry.get("title", "")) > 70 else "")
        lbl_title = ctk.CTkLabel(row_frame, text=title_text, font=self.fonts["label_sm_bold"], anchor="w")
        lbl_title.grid(row=0, column=1, padx=(0, 12), pady=(10, 2), sticky="ew")
        
        platform_name = PLATFORM_LABELS.get(entry.get('platform', ''), entry.get('platform', '-'))
        meta = f"{platform_name}  •  {entry.get('quality', '-')}  •  {entry.get('size', '-')}  •  {entry.get('date', '-')}"
        
        lbl_meta = ctk.CTkLabel(row_frame, text=meta, font=self.fonts["label_xs"], text_color=TEXT_MUTED, anchor="w")
        lbl_meta.grid(row=1, column=1, padx=(0, 12), pady=(0, 10), sticky="ew")

        for w in (lbl_icon, lbl_title, lbl_meta):
            w.bind("<Enter>", _on_enter)
            w.bind("<Leave>", _on_leave)
            w.bind("<Button-1>", _on_click)

    def _clear_history(self) -> None:
        if messagebox.askyesno("Hapus", "Hapus semua riwayat?", parent=self):
            save_history([])
            self._refresh_history_panel()

    # =====================================================
    #   LOGIKA INTERMEDIATE ANIMATION & UI PERSISTENCE
    # =====================================================
    def _do_reset_count(self) -> None:
        if messagebox.askyesno("Reset", "Reset hitungan unduhan ke 0?", parent=self):
            self.download_count = 0
            self._save_current_config()

    def _animate_progress_bar(self) -> None:
        if not self.winfo_exists(): 
            return
            
        diff = self.target_progress - self.current_progress
        if abs(diff) > 0.005:
            self.current_progress += diff * 0.15
            self.progress_bar.set(self.current_progress)
            self._anim_id = self.after(16, self._animate_progress_bar)
        else:
            self.current_progress = self.target_progress
            self.progress_bar.set(self.current_progress)
            self._is_animating_progress = False

    def _trigger_progress_animation(self) -> None:
        """Menghindari infinite frame polling loop saat idle."""
        if not self._is_animating_progress:
            self._is_animating_progress = True
            self._animate_progress_bar()

    def _fade_in_text(self, labels: List[Tuple[Any, str, bool]], step: int = 0, version: int = 0) -> None:
        if version != self._fade_version or not self.winfo_exists(): 
            return
            
        colors = ["#222226", "#44444A", "#77777F", "#A8A8B2", "#D4D4DB", "#F3F4F6"]
        muted_colors = ["#1A1A1E", "#333338", "#55555F", "#77777F", "#8E949F", "#A1A1AA"]
        
        if step < len(colors):
            for lbl, txt, is_title in labels:
                if lbl.winfo_exists():
                    lbl.configure(text=txt, text_color=colors[step] if is_title else muted_colors[step])
            self.after(25, lambda: self._fade_in_text(labels, step + 1, version))

    def _select_sidebar_mode(self, mode: str) -> None:
        if self._is_downloading: 
            return
            
        if self._sidebar_anim_id:
            self.after_cancel(self._sidebar_anim_id)
            self._sidebar_anim_id = None

        is_history = (mode == "history")
        if is_history:
            self.main_content.grid_remove()
            self.history_panel.grid()
            self._refresh_history_panel()
        else:
            self.history_panel.grid_remove()
            self.main_content.grid()
            self.dl_mode = mode

        self._info_fetch_token += 1
        is_video = (mode == "video")

        self.btn_mode_video.configure(
            text_color=TEXT_MAIN if mode=="video" else TEXT_MUTED, 
            font=self.fonts["nav_bold"] if mode=="video" else self.fonts["nav_reg"]
        )
        self.btn_mode_audio.configure(
            text_color=TEXT_MAIN if mode=="audio" else TEXT_MUTED, 
            font=self.fonts["nav_bold"] if mode=="audio" else self.fonts["nav_reg"]
        )
        self.btn_mode_history.configure(
            text_color=TEXT_MAIN if is_history else TEXT_MUTED, 
            font=self.fonts["nav_bold"] if is_history else self.fonts["nav_reg"]
        )

        if is_history:
            self.btn_mode_video.configure(fg_color="transparent")
            self.btn_mode_audio.configure(fg_color="transparent")
            self.btn_mode_history.configure(fg_color=COLOR_ACCENT)
            return

        self.btn_mode_history.configure(fg_color="transparent")
        self._animate_sidebar_select(is_video, step=0)

        if is_video:
            self.lbl_header_title.configure(text="🎬  Video Stream Downloader")
            self.lbl_res.configure(text="Kualitas Video:")
            res_to_show = self._last_video_resolutions or VIDEO_QUALITY_OPTIONS
            self.combo_res.configure(values=res_to_show)
            self.combo_res.set(res_to_show[0])
            self.after(0, self.lbl_container.grid)
            self.after(0, self.combo_container.grid)
            self.btn_download.configure(text="⬇  DOWNLOAD VIDEO")
        else:
            self.lbl_header_title.configure(text="🎵  Audio MP3 Extractor")
            self.lbl_res.configure(text="Bitrate MP3:")
            self.combo_res.configure(values=AUDIO_QUALITY_OPTIONS)
            self.combo_res.set(AUDIO_QUALITY_OPTIONS[0])
            self.after(0, self.lbl_container.grid_remove)
            self.after(0, self.combo_container.grid_remove)
            self.btn_download.configure(text="🎵  EXTRACT MP3")

        self._update_quality_vars(self.combo_res.get())
        if is_video: 
            self._update_container_vars(self.combo_container.get())
            
        self._reset_info_display()
        self._save_current_config()

    def _animate_sidebar_select(self, is_video: bool, step: int = 0) -> None:
        ACTIVATE = ["#2A0204", "#4E050B", "#760912", "#9E0D19", "#C61120", COLOR_ACCENT]
        DEACTIVATE = ["#B80710", "#8A0510", "#5E040C", "#380308", "#1E0204", "transparent"]
        v_col, a_col = (ACTIVATE, DEACTIVATE) if is_video else (DEACTIVATE, ACTIVATE)
        
        if step < 5:
            self.btn_mode_video.configure(fg_color=v_col[step])
            self.btn_mode_audio.configure(fg_color=a_col[step])
            self._sidebar_anim_id = self.after(16, lambda: self._animate_sidebar_select(is_video, step + 1))
        else:
            self.btn_mode_video.configure(fg_color=COLOR_ACCENT if is_video else "transparent")
            self.btn_mode_audio.configure(fg_color=COLOR_ACCENT if not is_video else "transparent")

    def _apply_saved_config(self, cfg: Dict[str, Any]) -> None:
        self._select_sidebar_mode(cfg.get("last_mode", "video"))
        sq = cfg.get("last_quality", "Best")
        if (self.dl_mode == "video" and sq in VIDEO_QUALITY_OPTIONS) or (self.dl_mode == "audio" and sq in AUDIO_QUALITY_OPTIONS):
            self.combo_res.set(sq)
        self.combo_container.set(cfg.get("last_container", "Format Asli"))
        self._update_quality_vars(self.combo_res.get())
        self._update_container_vars(self.combo_container.get())

    def _save_current_config(self) -> None:
        save_config({
            "download_folder": self.download_folder,
            "last_quality":    self.combo_res.get(),
            "last_container":  self.combo_container.get(),
            "last_mode":       self.dl_mode if self.dl_mode in ("video", "audio") else "video",
            "download_count":  self.download_count,
        })
        self.lbl_stats_counter.configure(text=f"{self.download_count} Files")

    def _reset_info_display(self) -> None:
        self.current_info_url = None
        self.btn_download.configure(state="disabled", fg_color="#1E1E22", text_color="#55555F")
        self.lbl_info_title.configure(text="Judul Konten : -", text_color="#3A3A40")
        self.lbl_info_channel.configure(text="Uploader     : -", text_color="#3A3A40")
        self.lbl_info_meta1.configure(text="Durasi  : -   •   Rilis: -   •   Est. Ukuran: -", text_color="#3A3A40")
        self.lbl_info_meta2.configure(
            text="Codec Video : -   •   Codec Audio: -" if self.dl_mode == "video" else "Audio Rate  : -   •   Codec Audio: -", 
            text_color="#3A3A40"
        )
        self.target_progress = 0.0
        self._trigger_progress_animation()
        self.lbl_percentage.configure(text="0%")
        self.lbl_status.configure(text="Status: Siap. Tempel tautan untuk mulai.")

    def _update_status(self, text: str, progress_val: Optional[float] = None, percent_text: Optional[str] = None) -> None:
        self.lbl_status.configure(text=f"Status: {text}")
        if progress_val is not None: 
            self.target_progress = float(progress_val)
            self._trigger_progress_animation()
        if percent_text is not None: 
            self.lbl_percentage.configure(text=percent_text)

    def _update_quality_vars(self, val: str) -> None:
        if self.dl_mode == "video":
            self.vformat = _RES_FORMAT_MAP.get(val, "bv*+ba/b")
        else:
            self.aquality = _AUDIO_QUALITY_MAP.get(val, "192k")

    def _update_container_vars(self, val: str) -> None:
        self.container = {"MP4": "mp4", "MKV": "mkv"}.get(val, "auto")

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, text)
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

    def _on_enter_url(self) -> None:
        if YTDLP_EXE.exists(): 
            self._load_video_info()

    def _on_ctrl_v(self, event=None):
        if self.focus_get() is self.url_entry: 
            return None
        if self.history_panel.winfo_ismapped(): 
            return "break"
            
        self._paste_url()
        if url := self.url_entry.get().strip():
            if is_valid_url(url): 
                self._load_video_info()
        return "break"

    def _on_window_focus(self, event=None) -> None:
        if event and event.widget is not self: 
            return
        if self._focus_debounce_id: 
            self.after_cancel(self._focus_debounce_id)
        self._focus_debounce_id = self.after(120, self._on_window_focus_debounced)

    def _on_window_focus_debounced(self) -> None:
        self._focus_debounce_id = None
        if self._is_downloading or self.history_panel.winfo_ismapped(): 
            return
            
        try: 
            clip = self.clipboard_get().strip()
        except Exception: 
            return
        
        if clip and clip != self._last_clipboard and is_valid_url(clip) and clip != self.url_entry.get().strip():
            self._last_clipboard = clip
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, clip)
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
        proc = self._dl_process
        if not proc: 
            return
            
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=5
                )
            except Exception: 
                pass
        try: 
            proc.terminate()
        except Exception: 
            pass

    def _cancel_download(self) -> None:
        self._cancel_event.set()
        self._kill_dl_process()
        self._update_status("Mengirim sinyal pembatalan...", 0.0, "0%")
        self.btn_cancel.configure(state="disabled")

    # =====================================================
    #   DEPENDENCY CHECK + AUTO-DOWNLOAD
    # =====================================================
    def _run_dependency_check(self) -> None:
        if engine_is_ready():
            self._update_status("✅ Mesin utama siap. Masukkan URL untuk memulai.", 0.0, "0%")
            return
            
        self._splash = SplashOverlay(self)
        self.btn_check_url.configure(state="disabled")
        threading.Thread(target=self._download_dependencies, daemon=True).start()

    @staticmethod
    def _fetch_file_to_disk(url: str, out_path: Path, shutdown_evt: threading.Event, cb_progress: Callable[[float, int], None]) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            with open(out_path, "wb") as f:
                while True:
                    if shutdown_evt.is_set():
                        f.close()
                        out_path.unlink(missing_ok=True)
                        return
                    chunk = response.read(65536)
                    if not chunk: 
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0: 
                        cb_progress(downloaded / total_size, downloaded)

    def _download_dependencies(self) -> None:
        url_ytdlp = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        url_ffmpeg = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        zip_path = DEPENDENCY_DIR / "ffmpeg_temp.zip"

        def _update_splash(title: str, total_size_mb: float, start_pct: float, end_pct: float, ratio: float, downloaded: int) -> None:
            if not self._splash: 
                return
            overall = start_pct + (end_pct - start_pct) * ratio
            pct_str = f"{int(overall * 100)}%"
            txt = f"📥 Mengunduh {title}... ({format_size(downloaded)} / {total_size_mb:.1f} MB)" if total_size_mb else f"📥 Mengunduh {title}..."
            self.after(0, lambda: self._splash.set_status(txt, pct_str) if self._splash else None)
            self.after(0, lambda: self._splash.set_progress(overall) if self._splash else None)

        try:
            if self._splash: 
                self.after(0, self._splash.switch_to_determinate)
            
            # Fetch yt-dlp (Hanya diunduh jika belum ada / korup)
            if not YTDLP_EXE.exists() or YTDLP_EXE.stat().st_size < 1_000_000:
                self._fetch_file_to_disk(url_ytdlp, YTDLP_EXE, self._shutdown_event, lambda r, d: _update_splash("Mesin Inti", 35.0, 0.0, 0.3, r, d))
                if not YTDLP_EXE.exists() or YTDLP_EXE.stat().st_size < 1_000_000:
                    raise RuntimeError("File yt-dlp tidak lengkap.")
            else:
                self.after(0, lambda: self._splash.set_progress(0.3) if self._splash else None)

            # Fetch FFmpeg
            self._fetch_file_to_disk(url_ffmpeg, zip_path, self._shutdown_event, lambda r, d: _update_splash("Ekstensi Audio", 45.0, 0.3, 0.8, r, d))
            if not zip_path.exists() or zip_path.stat().st_size < 10_000_000:
                raise RuntimeError("File FFmpeg tidak lengkap.")

            if self._splash:
                self.after(0, lambda: self._splash.set_status("📦 Mengekstrak komponen mesin...", "85%") if self._splash else None)
                self.after(0, lambda: self._splash.set_progress(0.85) if self._splash else None)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                for member in zip_ref.infolist():
                    fname = member.filename.replace("\\", "/")
                    if "/bin/" in fname and (fname.endswith(".exe") or fname.endswith(".dll")):
                        dest_path = DEPENDENCY_DIR / Path(fname).name
                        with zip_ref.open(member) as src, open(dest_path, "wb") as dst:
                            dst.write(src.read())

            zip_path.unlink(missing_ok=True)

            if self._splash:
                self.after(0, lambda: self._splash.set_status("✅ Semua komponen siap!", "100%") if self._splash else None)
                self.after(0, lambda: self._splash.set_progress(1.0) if self._splash else None)

            self.after(900, lambda: self._splash and self._splash.dismiss())
            self.after(0, lambda: self.btn_check_url.configure(state="normal"))
            self.after(0, lambda: self._update_status("✅ Sistem siap. Masukkan URL untuk memulai."))

        except Exception as e:
            # Proteksi: Jangan hapus YTDLP secara membabi buta jika kegagalan terjadi di segmen FFmpeg
            if YTDLP_EXE.exists() and YTDLP_EXE.stat().st_size < 1_000_000:
                YTDLP_EXE.unlink(missing_ok=True)
            zip_path.unlink(missing_ok=True)
            err_msg = "❌ Koneksi gagal!" if "urlopen" in str(e).lower() else "❌ Diblokir sistem/antivirus!"
            self.after(0, lambda: self._splash and self._splash.set_status(err_msg, "0%"))
            self.after(4000, lambda: self._splash and self._splash.dismiss())
            self.after(0, lambda: self._update_status(err_msg, 0.0, "0%"))

    # =====================================================
    #   UPDATE ENGINE MANUAL
    # =====================================================
    def _update_engine(self) -> None:
        if self._is_downloading: 
            return self._update_status("⚠ Selesaikan unduhan dahulu.", 0.0, "0%")
        if not YTDLP_EXE.exists(): 
            return self._update_status("❌ Mesin yt-dlp belum terpasang.", 0.0, "0%")

        self.btn_update_engine.configure(state="disabled", text="⏳ Updating...")
        self._update_status("Mengunduh pembaruan mesin pengunduh (yt-dlp)...", 0.5, "50%")

        def run_update() -> None:
            try:
                res = subprocess.run(
                    [str(YTDLP_EXE), "-U"], capture_output=True, text=True,
                    encoding="utf-8", timeout=60, creationflags=CREATE_NO_WINDOW
                )
                msg = "✅ Mesin sudah dalam versi terbaru." if "up to date" in (res.stdout or "").lower() else "✅ Mesin berhasil diperbarui!"
                self.after(0, lambda: self._update_status(msg, 1.0, "100%"))
            except subprocess.TimeoutExpired:
                self.after(0, lambda: self._update_status("❌ Gagal update: timeout.", 0.0, "0%"))
            except Exception as e:
                self.after(0, lambda m=str(e)[:50]: self._update_status(f"❌ Gagal update: {m}", 0.0, "0%"))
            finally:
                self.after(0, lambda: self.btn_update_engine.configure(state="normal", text="🔄 Update Engine"))

        threading.Thread(target=run_update, daemon=True).start()

    # =====================================================
    #   FETCH INFO & CORE DOWNLOAD HANDLER
    # =====================================================
    def _load_video_info(self) -> None:
        if self.btn_check_url.cget("state") == "disabled": 
            return
            
        url = self.url_entry.get().strip()
        if not url: 
            return self._update_status("Form tautan kosong!", 0.0, "0%")
        if not YTDLP_EXE.exists(): 
            return self._update_status("⚠ Mesin yt-dlp hilang!", 0.0, "0%")
        
        platform = detect_platform(url)
        if not platform: 
            return self._update_status("⚠ Platform tidak didukung.", 0.0, "0%")

        self.current_platform = platform
        self.btn_check_url.configure(state="disabled", text="⏳ Mengecek...")
        
        p_label = PLATFORM_LABELS[platform]
        self._update_status(f"🎬 Menganalisis stream dari {p_label}...", 0.2, "20%")

        fetch_mode, fetch_token = self.dl_mode, self._info_fetch_token

        def _async_info() -> None:
            data, error = get_info(url, is_audio=(fetch_mode == "audio"))
            
            def _apply() -> None:
                if fetch_token != self._info_fetch_token: 
                    return
                self.btn_check_url.configure(state="normal", text="Cek Media")
                
                if error:
                    self._update_status("❌ Gagal memuat info media.", 0.0, "0%")
                    self.lbl_info_title.configure(text=f"⚠ Gagal: {error[:80]}", text_color="#EF4444")
                    return
                
                if fetch_mode == "video" and data and "available_resolutions" in data:
                    res = data["available_resolutions"]
                    self._last_video_resolutions = res
                    self.combo_res.configure(values=res)
                    
                    # Smart UX Check: Pertahankan pilihan sebelumnya jika tersedia di video baru
                    prev_selection = self.combo_res.get()
                    if prev_selection in res:
                        self.combo_res.set(prev_selection)
                        self._update_quality_vars(prev_selection)
                    else:
                        self.combo_res.set(res[0])
                        self._update_quality_vars(res[0])

                p_info = f" [{data.get('playlist_count')} video]" if data.get("playlist_count") else ""
                
                if fetch_mode == "video":
                    meta2 = f"Codec Video : {data.get('vcodec', 'N/A')}   •   Codec Audio: {data.get('acodec')}"
                else:
                    meta2 = f"Audio Rate  : {data.get('asr', 'N/A')} Hz   •   Codec Audio: {data.get('acodec')}"
                
                tgts = [
                    (self.lbl_info_title, f"[{PLATFORM_LABELS.get(platform, platform)}] {data.get('title')}{p_info}", True),
                    (self.lbl_info_channel, f"Uploader     : {data.get('channel')}", False),
                    (self.lbl_info_meta1, f"Durasi  : {data.get('duration')}   •   Rilis: {data.get('upload_date')}   •   Est. Ukuran: {data.get('size')}", False),
                    (self.lbl_info_meta2, meta2, False)
                ]
                
                self._fade_version += 1
                self._fade_in_text(tgts, 0, self._fade_version)
                self.current_info_url = url
                self._last_fetched_title = data.get("title")
                self._last_fetched_size = data.get("size")
                self._update_status("✅ Info siap. Klik tombol mulai.", 1.0, "100%")
                self.btn_download.configure(state="normal", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOV, text_color=TEXT_MAIN)

            self.after(0, _apply)

        threading.Thread(target=_async_info, daemon=True).start()

    def _start_download(self) -> None:
        if not self.current_info_url or self._is_downloading: 
            return
            
        self._is_downloading = True
        self._cancel_event.clear()
        
        self.btn_download.configure(state="disabled", fg_color="#1E1E22", text_color="#55555F")
        self.btn_check_url.configure(state="disabled")
        self.btn_cancel.configure(state="normal")

        url = self.current_info_url
        folder = self.download_folder
        platform = self.current_platform or "youtube"
        dl_mode = self.dl_mode
        t_cache = self._last_fetched_title
        s_cache = self._last_fetched_size
        q_label = self.combo_res.get()

        cmd = [str(YTDLP_EXE), "--newline", "--no-warnings", "--no-playlist"]
        
        if f_loc := get_ffmpeg_location(): 
            cmd.extend(["--ffmpeg-location", f_loc])

        if dl_mode == "video":
            # self.vformat diturunkan lintas platform dengan fallback komparatif sehingga aman
            cmd.extend([
                "-f", self.vformat,
                "--windows-filenames",
                "-o", os.path.join(folder, "%(uploader).20s - %(title).40s [%(height)sp].%(ext)s"),
            ])
            if self.container != "auto": 
                cmd.extend(["--merge-output-format", self.container])
        else:
            cmd.extend([
                "-f", "ba/b",
                "--windows-filenames",
                "-o", os.path.join(folder, "%(uploader).20s - %(title).40s.%(ext)s"),
                "--convert-thumbnails", "jpg", "--embed-thumbnail", "--embed-metadata",
                "--extract-audio", "--audio-format", "mp3", "--audio-quality", self.aquality,
            ])
        cmd.append(url)

        def _run_dl() -> None:
            self.after(0, lambda: self._update_status("Menyiapkan instruksi unduhan...", 0.0, "0%"))
            try:
                self._dl_process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    encoding="utf-8", errors="ignore", creationflags=CREATE_NO_WINDOW
                )

                for line in self._dl_process.stdout:
                    if self._cancel_event.is_set() or self._shutdown_event.is_set():
                        self._kill_dl_process()
                        break
                    
                    line = line.strip()
                    # Menghilangkan dependensi 'ETA' agar kompatibel penuh dengan Instagram/TikTok streams
                    if "[download]" in line and "%" in line:
                        if m := re.search(r"(\d+\.?\d*)%", line):
                            val = float(m.group(1))
                            speed = line.split(" at ", 1)[1].strip() if " at " in line else ""
                            sts = f"🎬 Mengunduh • {speed}" if speed else "🎬 Mengunduh..."
                            self.after(0, lambda v=val/100, p=f"{int(val)}%", s=sts: self._update_status(s, v, p))
                    elif line.startswith("[Merger]") or line.startswith("[ExtractAudio]"):
                        msg = "⚙️ Menggabungkan video & audio..." if dl_mode == "video" else "⚙️ Mengonversi ke MP3..."
                        self.after(0, lambda m=msg: self._update_status(m, max(0.95, self.target_progress), f"{int(max(0.95, self.target_progress)*100)}%"))

                try: 
                    self._dl_process.stdout.read()
                except Exception: 
                    pass

                try: 
                    self._dl_process.wait(timeout=8.0)
                except subprocess.TimeoutExpired:
                    self._kill_dl_process()
                    try: 
                        self._dl_process.wait(timeout=3.0)
                    except subprocess.TimeoutExpired: 
                        pass

                if self._cancel_event.is_set():
                    time.sleep(1.2)
                    _cleanup_partial_files(folder)
                    self.after(0, lambda: self._update_status("⛔ Unduhan dibatalkan.", 0.0, "0%"))
                elif self._dl_process.returncode == 0:
                    self.download_count += 1
                    self.after(0, self._save_current_config)
                    append_history({
                        "title": t_cache or url, "platform": platform, "mode": dl_mode,
                        "quality": q_label, "size": s_cache or "-", "folder": folder,
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
                    
                    notif = f"Tersimpan: {(t_cache or '')[:50]}"
                    try:
                        icn = _meipass("icon.ico")
                    except Exception:
                        icn = None
                        
                    send_toast("FetchDrop ✅", notif, icn)
                    self.after(0, lambda: self._update_status("✅ Berkas berhasil disimpan.", 1.0, "100%"))
                else:
                    rc = self._dl_process.returncode
                    if rc in (1, 101): emsg = "❌ Gagal: Video privat, dihapus, atau diblokir."
                    elif rc == 2: emsg = "❌ Gagal: URL tidak valid atau format dibatasi."
                    else: emsg = f"❌ Gagal (Kode {rc}). Coba Update Engine."
                    self.after(0, lambda m=emsg: self._update_status(m, 0.0, "0%"))

            except Exception as e:
                self.after(0, lambda m=str(e)[:60]: self._update_status(f"❌ Error: {m}", 0.0, "0%"))
            finally:
                self._is_downloading = False
                self._dl_process = None
                if not self._shutdown_event.is_set():
                    self.after(0, lambda: self.btn_download.configure(
                        state="normal", fg_color=COLOR_ACCENT, 
                        hover_color=COLOR_ACCENT_HOV, text_color=TEXT_MAIN
                    ))
                    self.after(0, lambda: self.btn_check_url.configure(state="normal"))
                    self.after(0, lambda: self.btn_cancel.configure(state="disabled"))

        threading.Thread(target=_run_dl, daemon=True).start()

# =====================================================
#   ENTRY POINT INTERACTION
# =====================================================
if __name__ == "__main__":
    if not _check_single_instance():
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, "Aplikasi FetchDrop sudah berjalan di latar belakang.", "FetchDrop", 0x30)
        sys.exit(0)
        
    app = YTDownloaderApp()
    app.mainloop()