"""
FetchDrop – Social Media Downloader (Decoupled Engine)
Platform  : Windows (Compiled to .exe)
Build     : Nuitka — standalone + onefile
Memerlukan: Python 3.10+, customtkinter, nuitka

Perintah build (jalankan build_nuitka.bat atau salin ke CMD):
  python -m nuitka --standalone --onefile --windows-console-mode=disable
    --windows-icon-from-ico=icon.ico --include-data-files=icon.ico=icon.ico
    --enable-plugin=tk-inter --include-package=customtkinter
    --include-package-data=customtkinter --output-filename=FetchDrop.exe
    --assume-yes-for-downloads fetchdrop.py
"""

import os
import re
import sys
import json
import shutil
import threading
import subprocess
import urllib.request
import zipfile
from tkinter import filedialog
import customtkinter as ctk



# =====================================================
#   KONFIGURASI TEMA WARNA
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

CONFIG_FILE = os.path.join(os.path.expanduser("~"),
                           ".fetchdrop_config.json")
DEPENDENCY_DIR = os.path.join(os.path.expanduser("~"), ".fetchdrop_engine")
YTDLP_EXE = os.path.join(DEPENDENCY_DIR, "yt-dlp.exe")


def _get_app_basedir() -> str:
    """
    Mengembalikan direktori base tempat resource (icon, dll.) berada.
    Kompatibel dengan tiga skenario:
      - PyInstaller onefile : sys._MEIPASS  (temp extraction dir)
      - Nuitka standalone/onefile & plain Python : dirname(__file__)
    Catatan: Nuitka TIDAK men-set sys._MEIPASS maupun sys.frozen,
    namun __file__ pada Nuitka compiled sudah mengarah ke lokasi yang benar.
    """
    if hasattr(sys, "_MEIPASS"):       # PyInstaller onefile (legacy/fallback)
        return sys._MEIPASS            # type: ignore[attr-defined]
    # Nuitka (standalone/onefile) dan plain Python dev mode
    return os.path.dirname(os.path.abspath(__file__))


def _meipass(*parts) -> str:
    """Resolusi path resource — kompatibel dengan Nuitka, PyInstaller, dan dev mode."""
    return os.path.join(_get_app_basedir(), *parts)


def get_startupinfo() -> subprocess.STARTUPINFO:
    """Mencegah munculnya jendela Command Prompt saat subprocess dipanggil di .exe"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


# =====================================================
#   KONFIGURASI PERSISTENT
# =====================================================

def load_config() -> dict:
    default = {
        "download_folder": os.path.join(os.path.expanduser("~"), "Downloads"),
        "last_quality":    "Best",
        "last_container":  "Format Asli",
        "last_mode":       "video",
        "download_count":  0,
    }
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            default.update(json.load(f))
    except Exception:
        pass

    # Validasi: pastikan folder masih ada, fallback ke Downloads jika tidak
    if not os.path.isdir(default["download_folder"]):
        default["download_folder"] = os.path.join(
            os.path.expanduser("~"), "Downloads")
    return default


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def format_folder_label(path: str) -> str:
    home = os.path.expanduser("~")
    try:
        rel = os.path.relpath(path, home)
        display = os.path.join("~", rel) if not rel.startswith("..") else path
    except ValueError:
        display = path

    if len(display) > 48:
        parts = display.replace("\\", "/").split("/")
        display = ".../" + \
            "/".join(parts[-2:]) if len(parts) >= 2 else "..." + display[-45:]
    return f"📁 {display}"


# =====================================================
#   VALIDASI PLATFORM & MEDIA FORMATTING
# =====================================================
_PLATFORM_PATTERNS = {
    "youtube":   re.compile(r"(https?://)?(www\.)?(youtube\.com/(watch|shorts|playlist|embed|live)|youtu\.be/|music\.youtube\.com/watch)"),
    "tiktok":    re.compile(r"(https?://)?(www\.|vm\.|vt\.)?tiktok\.com/(@[\w.]+/video/\d+|v/\d+|/t/\w+|[\w]+)"),
    "instagram": re.compile(r"(https?://)?(www\.)?instagram\.com/(p|reel|tv)/[\w-]+"),
    "x":         re.compile(r"(https?://)?(www\.)?(twitter\.com|x\.com)/\w+/status/\d+"),
}
PLATFORM_LABELS = {
    "youtube":   "YouTube",
    "tiktok":    "TikTok",
    "instagram": "Instagram",
    "x":         "X / Twitter",
}
VIDEO_QUALITY_OPTIONS = [
    "Best", "4K (2160p)", "2K (1440p)", "1080p", "720p", "480p", "360p"]
AUDIO_QUALITY_OPTIONS = ["320 kbps", "192 kbps", "128 kbps"]


def detect_platform(url: str) -> str | None:
    for name, pattern in _PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return None


def is_valid_url(url: str) -> bool:
    return detect_platform(url) is not None


def format_size(bytes_value: int | float | str) -> str:
    """Mengkonversi bytes ke format human-readable (KB / MB / GB / TB)."""
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


def shorten_codec(codec: str, max_len: int = 10) -> str:
    if not codec or codec == "none":
        return "N/A"
    return codec.split(".")[0][:max_len]


# =====================================================
#   DEPENDENCIES ENGINE CHECK (yt-dlp & FFmpeg)
# =====================================================

def engine_is_ready() -> bool:
    has_ytdlp = os.path.exists(YTDLP_EXE)
    has_ffmpeg = bool(
        shutil.which("ffmpeg") or (
            os.path.exists(os.path.join(DEPENDENCY_DIR, "ffmpeg.exe")) and
            os.path.exists(os.path.join(DEPENDENCY_DIR, "ffprobe.exe"))
        )
    )
    return has_ytdlp and has_ffmpeg


def get_ffmpeg_location() -> str | None:
    """Kembalikan path direktori FFmpeg jika tidak ditemukan di PATH sistem."""
    if shutil.which("ffmpeg"):
        return None
    return DEPENDENCY_DIR


# =====================================================
#   LOGIKA FETCH INFO MEDIA (MENGGUNAKAN SUBPROCESS)
# =====================================================

def get_info(url: str, is_audio: bool = False) -> tuple:
    cmd = [YTDLP_EXE, "-J", "--no-warnings", "--socket-timeout", "15"]

    ffmpeg_loc = get_ffmpeg_location()
    if ffmpeg_loc:
        cmd.extend(["--ffmpeg-location", ffmpeg_loc])
    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            startupinfo=get_startupinfo(),
        )

        if result.returncode != 0:
            return None, "Video bersifat privat, tidak ditemukan, atau diblokir oleh platform."

        info = json.loads(result.stdout)

        # Tangani playlist: ambil entri pertama yang valid
        playlist_count = None
        if "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            playlist_count = len(entries)
            if not entries:
                return None, "Playlist kosong."
            info = entries[0]

        size_raw = info.get("filesize") or info.get("filesize_approx") or "NA"

        # FIX: Mapping resolusi — gunakan set label agar tidak duplikat,
        # dan pastikan setiap height hanya dipetakan ke satu label.
        available_resolutions = ["Best"]
        res_map_labels = [
            (2160, "4K (2160p)"),
            (1440, "2K (1440p)"),
            (1080, "1080p"),
            (720,  "720p"),
            (480,  "480p"),
            (360,  "360p"),
        ]
        seen_heights = sorted(
            {
                f.get("height")
                for f in info.get("formats", [])
                if (
                    f.get("height")
                    # bukan None / kosong
                    and f.get("vcodec")
                    # bukan audio-only
                    and f.get("vcodec") not in ("none",)
                    and "storyboard" not in str(f.get("format_note", "")).lower()
                )
            },
            reverse=True,
        )
        added_labels: set[str] = set()
        for height in seen_heights:
            for threshold, label in res_map_labels:
                if height >= threshold and label not in added_labels:
                    available_resolutions.append(label)
                    added_labels.add(label)
                    break  # satu height -> satu label saja

        ud = info.get("upload_date", "Unknown")
        if ud and len(ud) == 8 and ud.isdigit():
            ud = f"{ud[:4]}-{ud[4:6]}-{ud[6:]}"

        data = {
            "title":                 info.get("title", "Unknown"),
            "channel":               info.get("channel") or info.get("uploader", "Unknown"),
            "duration":              info.get("duration_string", "Unknown"),
            "upload_date":           ud,
            "size":                  format_size(size_raw),
            "acodec":                shorten_codec(info.get("acodec", "Unknown")),
            "playlist_count":        playlist_count,
            "available_resolutions": available_resolutions,
        }

        if not is_audio:
            data["resolution"] = info.get("resolution", "Unknown")
            data["vcodec"] = shorten_codec(info.get("vcodec", "Unknown"))
        else:
            asr = info.get("asr")
            data["asr"] = f"{asr:,}" if isinstance(
                asr, (int, float)) else "Unknown"

        return data, None

    except Exception as e:
        return None, str(e)


# =====================================================
#   SPLASH SCREEN (DEPENDENCY DOWNLOADER)
# =====================================================
class SplashOverlay(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=COLOR_BG, corner_radius=0)
        self.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        self.lift()

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(
            inner, text="⚡ FetchDrop",
            font=ctk.CTkFont(family="Segoe UI", size=40, weight="bold"),
            text_color=TEXT_MAIN,
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            inner, text="Menyiapkan mesin pengunduh — hanya dilakukan sekali.",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#4B4B54",
        ).pack(pady=(0, 36))

        self._bar = ctk.CTkProgressBar(
            inner, width=360, height=5,
            progress_color=COLOR_ACCENT, fg_color="#1A1A1E",
            corner_radius=3, mode="indeterminate",
        )
        self._bar.pack(pady=(0, 10))
        self._bar.start()

        self._lbl_pct = ctk.CTkLabel(
            inner, text="",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLOR_ACCENT, width=360, anchor="e",
        )
        self._lbl_pct.pack()

        self._lbl_status = ctk.CTkLabel(
            inner, text="Memeriksa komponen sistem...",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=TEXT_MUTED, width=360, anchor="w",
        )
        self._lbl_status.pack(pady=(4, 0))

    def set_status(self, text: str, pct: str = ""):
        try:
            if self.winfo_exists():
                self._lbl_status.configure(text=text)
                self._lbl_pct.configure(text=pct)
        except Exception:
            pass

    def switch_to_determinate(self):
        try:
            if self.winfo_exists():
                self._bar.stop()
                self._bar.configure(mode="determinate")
                self._bar.set(0.0)
        except Exception:
            pass

    def set_progress(self, value: float):
        try:
            if self.winfo_exists():
                self._bar.set(max(0.0, min(1.0, value)))
        except Exception:
            pass

    def dismiss(self):
        try:
            if self.winfo_exists():
                self.destroy()
        except Exception:
            pass


# =====================================================
#   ANTARMUKA GUI UTAMA
# =====================================================
class YTDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("FetchDrop – Social Media Downloader")
        self.geometry("860x560")
        self.resizable(False, False)
        self.configure(fg_color=COLOR_BG)

        try:
            # Selalu gunakan _meipass() — ia menangani semua mode secara otomatis.
            # sys.frozen TIDAK diset oleh Nuitka, sehingga getattr(sys, "frozen")
            # selalu False pada Nuitka compiled → ikon tidak pernah termuat.
            # Fix: hapus kondisi tersebut dan andalkan _meipass() sepenuhnya.
            icon_path = _meipass("icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass

        cfg = load_config()
        self.download_count = cfg.get("download_count", 0)
        self.download_folder = cfg["download_folder"]
        self.current_info_url = None
        self.current_platform = None
        self.dl_mode = cfg.get("last_mode", "video")
        self._cancel_event = threading.Event()
        # sinyal global: aplikasi sedang ditutup
        self._shutdown_event = threading.Event()
        self._is_downloading = False
        self._dl_process = None
        self._splash = None

        self.vformat = "bv*+ba/b"
        self.vres = cfg.get("last_quality", "Best")
        self.container = "auto"
        self.aquality = "320K"
        self._last_video_resolutions = None  # Resolusi hasil Cek Media terakhir
        # Versi animasi fade-in aktif (untuk batalkan chain lama)
        self._fade_version = 0

        self.current_progress = 0.0
        self.target_progress = 0.0

        # ── Pre-bake font objects ──────────────────────────────────────────
        # PENTING: Jangan buat CTkFont baru setiap switch mode sidebar.
        # Re-creating font triggers Tkinter font re-registration → frame skip.
        # Objek font dibuat sekali di sini dan di-reuse selamanya.
        self._fn_nav_bold = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        self._fn_nav_reg  = ctk.CTkFont(family="Segoe UI", size=12)

        # ID untuk membatalkan animasi sidebar yang sedang berjalan
        self._sidebar_anim_id: str | None = None

        self._setup_layout()
        self._apply_saved_config(cfg)
        self._animate_progress_bar()
        self._run_dependency_check()

        # FIX: bind Ctrl+V hanya untuk paste manual agar tidak bentrok
        # dengan event default Tkinter pada widget Entry
        self.bind("<Control-v>", self._on_ctrl_v)

        # Intersep tombol X (close) agar semua proses latar belakang
        # dihentikan dengan bersih sebelum aplikasi benar-benar ditutup
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

    # =====================================================
    #   SHUTDOWN BERSIH (TOMBOL X / ALT-F4)
    # =====================================================

    def _on_close_request(self):
        """
        Dipanggil saat pengguna menekan tombol X atau Alt+F4.

        Urutan shutdown:
        1. Tandai _shutdown_event agar semua thread berhenti iterasi.
        2. Kirim sinyal cancel ke _cancel_event (sama seperti tombol "Batal").
        3. Paksa terminate proses yt-dlp jika sedang berjalan.
        4. Tutup jendela — thread sudah daemon=True sehingga Python runtime
           akan membersihkan sisanya secara otomatis.
        """
        # Tandai bahwa aplikasi sedang ditutup; semua thread akan berhenti
        self._shutdown_event.set()
        self._cancel_event.set()

        # Hentikan proses yt-dlp aktif jika ada
        if self._dl_process is not None:
            try:
                self._dl_process.terminate()
            except Exception:
                pass

        # Simpan konfigurasi terakhir sebelum keluar
        try:
            self._save_current_config()
        except Exception:
            pass

        # Tutup jendela dan akhiri event loop Tkinter
        self.destroy()

    # =====================================================
    #   LAYOUT SETUP
    # =====================================================

    def _setup_layout(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_content()

    def _build_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self, width=220, corner_radius=0,
            fg_color=COLOR_SIDEBAR, border_width=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.sidebar, text="⚡ FetchDrop",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=TEXT_MAIN,
        ).grid(row=0, column=0, padx=24, pady=(32, 2), sticky="w")

        ctk.CTkLabel(
            self.sidebar, text="Stable Engine",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=1, column=0, padx=24, pady=(0, 36), sticky="w")

        ctk.CTkLabel(
            self.sidebar, text="KATEGORI UNDUHAN",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color="#4B4B54",
        ).grid(row=2, column=0, padx=24, pady=(0, 8), sticky="w")

        self.btn_mode_video = ctk.CTkButton(
            self.sidebar, text="🎬  Video Downloader",
            anchor="w", height=38, corner_radius=8,
            fg_color=COLOR_ACCENT, text_color=TEXT_MAIN,
            font=self._fn_nav_bold,
            hover_color=COLOR_ACCENT_HOV,
            command=lambda: self._select_sidebar_mode("video"),
        )
        self.btn_mode_video.grid(row=3, column=0, padx=16, pady=4, sticky="ew")

        self.btn_mode_audio = ctk.CTkButton(
            self.sidebar, text="🎵  Audio MP3 Extractor",
            anchor="w", height=38, corner_radius=8,
            fg_color="transparent", text_color=TEXT_MUTED,
            font=self._fn_nav_reg,
            hover_color="#1D1D21",
            command=lambda: self._select_sidebar_mode("audio"),
        )
        self.btn_mode_audio.grid(row=4, column=0, padx=16, pady=4, sticky="ew")

        # Footer sidebar — statistik dan tombol update engine
        self.sidebar.grid_rowconfigure(5, weight=1)
        footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        footer.grid(row=5, column=0, sticky="ews", padx=24, pady=24)

        ctk.CTkLabel(
            footer, text="TOTAL BERKAS TERUNDUH",
            font=ctk.CTkFont(family="Segoe UI", size=9, weight="bold"),
            text_color="#4B4B54",
        ).pack(anchor="w")

        counter_row = ctk.CTkFrame(footer, fg_color="transparent")
        counter_row.pack(anchor="w", pady=(2, 0), fill="x")

        self.lbl_stats_counter = ctk.CTkLabel(
            counter_row, text=f"{self.download_count} Files",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=COLOR_ACCENT,
        )
        self.lbl_stats_counter.pack(side="left")

        self.btn_reset_count = ctk.CTkButton(
            counter_row, text="↺", width=26, height=26,
            fg_color="transparent", hover_color="#1E1E22",
            text_color="#4B4B54", corner_radius=6,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            command=self._do_reset_count,
        )
        self.btn_reset_count.pack(side="left", padx=(6, 0), pady=(2, 0))

        self.btn_update_engine = ctk.CTkButton(
            footer, text="🔄 Update Engine", height=28,
            fg_color="#1E1E22", hover_color="#25252A",
            text_color=TEXT_MUTED, corner_radius=6,
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            command=self._update_engine,
        )
        self.btn_update_engine.pack(anchor="w", pady=(16, 0), fill="x")

    def _build_main_content(self):
        self.main_content = ctk.CTkFrame(
            self, corner_radius=0, fg_color="transparent")
        self.main_content.grid(row=0, column=1, padx=28,
                               pady=28, sticky="nsew")
        self.main_content.grid_columnconfigure(0, weight=1)

        # Header
        self.lbl_header_title = ctk.CTkLabel(
            self.main_content, text="🎬  Video Stream Downloader",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=TEXT_MAIN,
        )
        self.lbl_header_title.grid(row=0, column=0, sticky="w", pady=(0, 16))

        # Input URL
        input_card = ctk.CTkFrame(
            self.main_content, height=52,
            fg_color=COLOR_CARD, border_width=1,
            border_color=COLOR_BORDER, corner_radius=10,
        )
        input_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        input_card.grid_columnconfigure(0, weight=1)
        input_card.grid_propagate(False)

        self.url_entry = ctk.CTkEntry(
            input_card,
            placeholder_text="Tempel tautan video di sini (YouTube, TikTok, IG, X)...",
            height=52, fg_color="transparent", border_width=0,
            text_color=TEXT_MAIN,
            font=ctk.CTkFont(family="Segoe UI", size=12),
        )
        self.url_entry.grid(row=0, column=0, padx=(16, 8), sticky="ew")
        self.url_entry.bind("<Return>", lambda _: self._load_video_info())

        actions = ctk.CTkFrame(input_card, fg_color="transparent")
        actions.grid(row=0, column=1, padx=(0, 8), sticky="e")

        ctk.CTkButton(
            actions, text="✕", width=34, height=34,
            fg_color="#1E1E22", hover_color="#3A1A1A",
            text_color="#FF6B6B", corner_radius=6,
            command=self._clear_url,
        ).pack(side="left", padx=3)

        ctk.CTkButton(
            actions, text="📋", width=34, height=34,
            fg_color="#1E1E22", hover_color="#25252A",
            text_color=TEXT_MAIN, corner_radius=6,
            command=self._paste_url,
        ).pack(side="left", padx=3)

        self.btn_check_url = ctk.CTkButton(
            actions, text="Cek Media", width=90, height=34,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOV,
            text_color=TEXT_MAIN,
            font=ctk.CTkFont(family="Segoe UI", weight="bold", size=11),
            corner_radius=6,
            command=self._load_video_info,
        )
        self.btn_check_url.pack(side="left", padx=(6, 0))

        # Info Card
        info_card = ctk.CTkFrame(
            self.main_content,
            fg_color=COLOR_CARD, border_width=1,
            border_color=COLOR_BORDER, corner_radius=10,
        )
        info_card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        info_card.grid_columnconfigure(0, weight=1)

        f_bold = ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        f_reg = ctk.CTkFont(family="Segoe UI", size=12)

        self.lbl_info_title = ctk.CTkLabel(
            info_card, text="Judul Konten : -",
            font=f_bold, text_color="#3A3A40",
            anchor="w", justify="left", wraplength=550,
        )
        self.lbl_info_title.grid(
            row=0, column=0, padx=18, pady=(16, 4), sticky="ew")

        self.lbl_info_channel = ctk.CTkLabel(
            info_card, text="Uploader     : -",
            font=f_reg, text_color="#3A3A40",
            anchor="w", justify="left", wraplength=550,
        )
        self.lbl_info_channel.grid(
            row=1, column=0, padx=18, pady=4, sticky="ew")

        self.lbl_info_meta1 = ctk.CTkLabel(
            info_card,
            text="Durasi       : -   •   Rilis: -   •   Estimasi Ukuran: -",
            font=f_reg, text_color="#3A3A40",
            anchor="w", justify="left", wraplength=550,
        )
        self.lbl_info_meta1.grid(row=2, column=0, padx=18, pady=4, sticky="ew")

        self.lbl_info_meta2 = ctk.CTkLabel(
            info_card, text="Codec Video  : -   •   Codec Audio: -",
            font=f_reg, text_color="#3A3A40",
            anchor="w", justify="left", wraplength=550,
        )
        self.lbl_info_meta2.grid(
            row=3, column=0, padx=18, pady=(4, 16), sticky="ew")

        # Config Card (Kualitas & Container)
        config_card = ctk.CTkFrame(
            self.main_content, height=56,
            fg_color=COLOR_CARD, border_width=1,
            border_color=COLOR_BORDER, corner_radius=10,
        )
        config_card.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        config_card.grid_propagate(False)
        config_card.grid_columnconfigure((1, 3), weight=1)

        self.lbl_res = ctk.CTkLabel(
            config_card, text="Kualitas Sediaan:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TEXT_MAIN,
        )
        self.lbl_res.grid(row=0, column=0, padx=(18, 12), pady=12, sticky="w")

        self.combo_res = ctk.CTkComboBox(
            config_card,
            values=VIDEO_QUALITY_OPTIONS,
            width=145, height=32,
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            button_color="#1E1E22", button_hover_color="#25252A",
            text_color=TEXT_MAIN, corner_radius=6,
            command=self._update_quality_vars,
        )
        self.combo_res.grid(row=0, column=1, pady=12, sticky="w")

        self.lbl_container = ctk.CTkLabel(
            config_card, text="Format Container:",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=TEXT_MAIN,
        )
        self.lbl_container.grid(
            row=0, column=2, padx=(24, 12), pady=12, sticky="w")

        self.combo_container = ctk.CTkComboBox(
            config_card, values=["Format Asli", "MP4", "MKV"],
            width=145, height=32,
            fg_color=COLOR_BG, border_color=COLOR_BORDER,
            button_color="#1E1E22", button_hover_color="#25252A",
            text_color=TEXT_MAIN, corner_radius=6,
            command=self._update_container_vars,
        )
        self.combo_container.grid(row=0, column=3, pady=12, sticky="w")

        # Status & Progress
        status_zone = ctk.CTkFrame(self.main_content, fg_color="transparent")
        status_zone.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        status_zone.grid_columnconfigure(0, weight=1)

        self.lbl_status = ctk.CTkLabel(
            status_zone, text="Menunggu instruksi tautan...",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=TEXT_MUTED, anchor="w",
        )
        self.lbl_status.grid(row=0, column=0, sticky="w")

        self.lbl_percentage = ctk.CTkLabel(
            status_zone, text="0%",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=COLOR_ACCENT,
        )
        self.lbl_percentage.grid(row=0, column=1, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(
            self.main_content,
            progress_color=COLOR_ACCENT, fg_color="#1F1F24",
            height=4, corner_radius=2,
        )
        self.progress_bar.grid(row=5, column=0, sticky="ew", pady=(6, 24))
        self.progress_bar.set(0)

        # Action Bar
        action_bar = ctk.CTkFrame(self.main_content, fg_color="transparent")
        action_bar.grid(row=6, column=0, sticky="ew")
        action_bar.grid_columnconfigure(0, weight=1)

        self.lbl_folder = ctk.CTkLabel(
            action_bar,
            text=format_folder_label(self.download_folder),
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=TEXT_MUTED,
        )
        self.lbl_folder.grid(row=0, column=0, sticky="w")

        controls_right = ctk.CTkFrame(action_bar, fg_color="transparent")
        controls_right.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            controls_right, text="📂 Buka", width=75, height=34,
            fg_color=COLOR_CARD, border_width=1, border_color=COLOR_BORDER,
            text_color=TEXT_MUTED, hover_color="#1E1E22", corner_radius=6,
            command=self._open_output_folder,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            controls_right, text="Ubah", width=75, height=34,
            fg_color=COLOR_CARD, border_width=1, border_color=COLOR_BORDER,
            text_color=TEXT_MAIN, hover_color="#1E1E22", corner_radius=6,
            command=self._change_output_folder,
        ).pack(side="left", padx=4)

        self.btn_cancel = ctk.CTkButton(
            controls_right, text="Batal", width=75, height=34,
            fg_color="transparent", border_width=1,
            border_color="#3A1C20", text_color="#FFA4A4",
            hover_color="#2A1418", state="disabled", corner_radius=6,
            command=self._cancel_download,
        )
        self.btn_cancel.pack(side="left", padx=4)

        self.btn_download = ctk.CTkButton(
            controls_right, text="MULAI UNDUH", width=135, height=34,
            fg_color="#1E1E22", hover_color="#25252A", text_color="#55555F",
            font=ctk.CTkFont(family="Segoe UI", weight="bold", size=12),
            state="disabled", corner_radius=6,
            command=self._start_download,
        )
        self.btn_download.pack(side="left", padx=(8, 0))

    # =====================================================
    #   LOGIKA UI
    # =====================================================

    def _do_reset_count(self):
        self.download_count = 0
        self._save_current_config()

    def _animate_progress_bar(self):
        try:
            if not self.winfo_exists():
                return
            diff = self.target_progress - self.current_progress
            if abs(diff) > 0.001:
                self.current_progress += diff * 0.15
            else:
                self.current_progress = self.target_progress
            self.progress_bar.set(self.current_progress)
            self.after(16, self._animate_progress_bar)
        except Exception:
            pass

    def _fade_in_text(self, labels_with_text: list, step: int = 0, version: int = 0):
        # Batalkan rantai animasi lama jika ada versi lebih baru yang dimulai
        if version != self._fade_version:
            return
        colors = ["#222226", "#44444A", "#77777F",
                  "#A8A8B2", "#D4D4DB", "#F3F4F6"]
        muted_colors = ["#1A1A1E", "#333338",
                        "#55555F", "#77777F", "#8E949F", "#A1A1AA"]
        if step < len(colors):
            for lbl, txt, is_title in labels_with_text:
                lbl.configure(
                    text=txt,
                    text_color=colors[step] if is_title else muted_colors[step],
                )
            # Gunakan default argument (s=step, v=version) agar nilai terkunci
            # saat lambda dibuat, bukan saat dipanggil
            self.after(25, lambda s=step, v=version: self._fade_in_text(
                labels_with_text, s + 1, v))

    def _select_sidebar_mode(self, mode: str):
        # Jangan izinkan pergantian mode saat proses unduhan sedang berjalan
        if self._is_downloading:
            return

        # ── Batalkan animasi sidebar yang mungkin sedang berjalan ──────────
        if self._sidebar_anim_id is not None:
            self.after_cancel(self._sidebar_anim_id)
            self._sidebar_anim_id = None

        self.dl_mode = mode
        is_video = (mode == "video")

        # ── Update text_color & font SEKARANG (pakai font pre-created) ─────
        # Tidak ada re-registration font → tidak ada frame skip
        self.btn_mode_video.configure(
            text_color=TEXT_MAIN if is_video else TEXT_MUTED,
            font=self._fn_nav_bold if is_video else self._fn_nav_reg,
        )
        self.btn_mode_audio.configure(
            text_color=TEXT_MAIN if not is_video else TEXT_MUTED,
            font=self._fn_nav_bold if not is_video else self._fn_nav_reg,
        )

        # ── Animasi cross-fade background tombol (smooth) ──────────────────
        self._animate_sidebar_select(is_video, step=0)

        # ── Update konten panel ────────────────────────────────────────────
        if is_video:
            self.lbl_header_title.configure(text="🎬  Video Stream Downloader")
            self.lbl_res.configure(text="Kualitas Video:")
            res_to_show = self._last_video_resolutions or VIDEO_QUALITY_OPTIONS
            self.combo_res.configure(values=res_to_show)
            self.combo_res.set(res_to_show[0])
            # ── FIX: defer grid changes ke next event loop tick ─────────────
            # Ini memisahkan layout recalculation dari configure() di atas,
            # sehingga Tkinter tidak perlu repaint dua kali dalam satu frame.
            self.after(0, self.lbl_container.grid)
            self.after(0, self.combo_container.grid)
            self.btn_download.configure(text="⬇  DOWNLOAD VIDEO")
        else:
            self.lbl_header_title.configure(text="🎵  Audio MP3 Extractor")
            self.lbl_res.configure(text="Bitrate MP3:")
            self.combo_res.configure(values=AUDIO_QUALITY_OPTIONS)
            # FIX: set ke nilai default yang pasti ada di list
            self.combo_res.set(AUDIO_QUALITY_OPTIONS[0])
            self.after(0, self.lbl_container.grid_remove)
            self.after(0, self.combo_container.grid_remove)
            self.btn_download.configure(text="🎵  EXTRACT MP3")

        self._update_quality_vars(self.combo_res.get())
        if is_video:
            self._update_container_vars(self.combo_container.get())
        self._reset_info_display()
        self._save_current_config()

    def _animate_sidebar_select(self, is_video: bool, step: int = 0):
        """
        Smooth 6-frame cross-fade untuk perpindahan tombol sidebar.
        Interpolasi warna dari sidebar-bg (#111113) → accent (#E50914)
        untuk tombol aktif, dan sebaliknya untuk tombol non-aktif.
        Berjalan di ~16ms per frame (≈60 fps) → total ~96ms, terasa instan
        tapi jauh lebih smooth dari perubahan langsung.
        """
        TOTAL = 6
        # Warna interpolasi: dark → accent (untuk tombol yang sedang diaktifkan)
        ACTIVATE = [
            "#2A0204", "#4E050B", "#760912",
            "#9E0D19", "#C61120", COLOR_ACCENT,
        ]
        # Warna interpolasi: accent → dark (untuk tombol yang sedang dinonaktifkan)
        DEACTIVATE = [
            "#B80710", "#8A0510", "#5E040C",
            "#380308", "#1E0204", "transparent",
        ]

        vid_colors = ACTIVATE   if is_video else DEACTIVATE
        aud_colors = DEACTIVATE if is_video else ACTIVATE

        try:
            if step < TOTAL - 1:
                # Frame tengah: hanya ubah background
                self.btn_mode_video.configure(fg_color=vid_colors[step])
                self.btn_mode_audio.configure(fg_color=aud_colors[step])
                self._sidebar_anim_id = self.after(
                    16, lambda s=step: self._animate_sidebar_select(is_video, s + 1)
                )
            else:
                # Frame terakhir: snap ke final state yang tepat
                self._sidebar_anim_id = None
                self.btn_mode_video.configure(
                    fg_color=COLOR_ACCENT if is_video else "transparent",
                )
                self.btn_mode_audio.configure(
                    fg_color=COLOR_ACCENT if not is_video else "transparent",
                )
        except Exception:
            pass

    def _apply_saved_config(self, cfg: dict):
        saved_mode = cfg.get("last_mode", "video")
        saved_quality = cfg.get("last_quality", "Best")
        saved_container = cfg.get("last_container", "Format Asli")

        self._select_sidebar_mode(saved_mode)

        # Hanya set jika nilai tersimpan valid untuk mode saat ini
        if saved_mode == "video" and saved_quality in VIDEO_QUALITY_OPTIONS:
            self.combo_res.set(saved_quality)
        elif saved_mode == "audio" and saved_quality in AUDIO_QUALITY_OPTIONS:
            self.combo_res.set(saved_quality)

        self.combo_container.set(saved_container)
        self._update_quality_vars(self.combo_res.get())
        self._update_container_vars(self.combo_container.get())

    def _save_current_config(self):
        save_config({
            "download_folder": self.download_folder,
            "last_quality":    self.combo_res.get(),
            "last_container":  self.combo_container.get(),
            "last_mode":       self.dl_mode,
            "download_count":  self.download_count,
        })
        self.lbl_stats_counter.configure(text=f"{self.download_count} Files")

    def _reset_info_display(self):
        self.current_info_url = None
        self.btn_download.configure(
            state="disabled", fg_color="#1E1E22", text_color="#55555F")
        self.lbl_info_title.configure(
            text="Judul Konten : -", text_color="#3A3A40")
        self.lbl_info_channel.configure(
            text="Uploader     : -", text_color="#3A3A40")
        self.lbl_info_meta1.configure(
            text="Durasi       : -   •   Rilis: -   •   Estimasi Ukuran: -",
            text_color="#3A3A40",
        )
        meta2_ph = (
            "Codec Video  : -   •   Codec Audio: -"
            if self.dl_mode == "video"
            else "Audio Rate   : -   •   Codec Audio: -"
        )
        self.lbl_info_meta2.configure(text=meta2_ph, text_color="#3A3A40")
        self.target_progress = 0.0
        self.lbl_percentage.configure(text="0%")
        self.lbl_status.configure(
            text="Status: Siap. Tempel tautan untuk mulai.")

    def _update_status(self, text: str, progress_val=None, percent_text: str | None = None):
        self.lbl_status.configure(text=f"Status: {text}")
        if progress_val is not None:
            self.target_progress = float(progress_val)
        if percent_text is not None:
            self.lbl_percentage.configure(text=percent_text)

    def _update_quality_vars(self, val: str):
        if self.dl_mode == "video":
            res_map = {
                "360p":       "bv*[height<=360]+ba/b[height<=360]/b",
                "480p":       "bv*[height<=480]+ba/b[height<=480]/b",
                "720p":       "bv*[height<=720]+ba/b[height<=720]/b",
                "1080p":      "bv*[height<=1080]+ba/b[height<=1080]/b",
                "2K (1440p)": "bv*[height<=1440]+ba/b[height<=1440]/b",
                "4K (2160p)": "bv*[height<=2160]+ba/b[height<=2160]/b",
            }
            self.vformat = res_map.get(val, "bv*+ba/b")
        else:
            try:
                # FIX: Tambahkan suffix "K" agar yt-dlp/ffmpeg menginterpretasikan
                # nilai sebagai CBR bitrate (misal "320K"), bukan VBR quality scale (0–10).
                # Tanpa "K", ffmpeg menerima "320" sebagai skala VBR yang tidak valid.
                self.aquality = val.split()[0] + "K"
            except Exception:
                self.aquality = "192K"

    def _update_container_vars(self, val: str):
        self.container = {"MP4": "mp4", "MKV": "mkv"}.get(val, "auto")

    def _paste_url(self):
        """Paste dari clipboard ke field URL."""
        try:
            text = self.clipboard_get().strip()
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, text)
        except Exception:
            pass

    def _clear_url(self):
        self.url_entry.delete(0, "end")
        self._last_video_resolutions = None          # hapus cache resolusi
        if self.dl_mode == "video":
            self.combo_res.configure(values=VIDEO_QUALITY_OPTIONS)
            self.combo_res.set(VIDEO_QUALITY_OPTIONS[0])
            self._update_quality_vars(VIDEO_QUALITY_OPTIONS[0])
        self._reset_info_display()

    def _on_ctrl_v(self, event=None):
        """
        FIX: Intercept Ctrl+V hanya jika fokus ada di luar url_entry.
        Jika fokus di url_entry, biarkan event default Tkinter yang handle
        agar tidak terjadi paste ganda.
        """
        focused = self.focus_get()
        if focused is self.url_entry:
            # Biarkan Tkinter handle paste default pada Entry
            return None

        # Jika fokus bukan di Entry, lakukan paste manual lalu cek URL
        self._paste_url()
        url = self.url_entry.get().strip()
        if url and is_valid_url(url):
            self._load_video_info()
        return "break"

    def _change_output_folder(self):
        selected = filedialog.askdirectory(initialdir=self.download_folder)
        if selected:
            self.download_folder = selected
            self.lbl_folder.configure(text=format_folder_label(selected))
            self._save_current_config()

    def _open_output_folder(self):
        if os.path.isdir(self.download_folder):
            os.startfile(self.download_folder)

    def _cancel_download(self):
        self._cancel_event.set()
        if self._dl_process:
            try:
                self._dl_process.terminate()
            except Exception:
                pass
        self._update_status("Mengirim sinyal pembatalan...", 0, "0%")
        self.btn_cancel.configure(state="disabled")

    # =====================================================
    #   DEPENDENCY CHECK + AUTO-DOWNLOAD (FFMPEG & YT-DLP)
    # =====================================================

    def _run_dependency_check(self):
        if engine_is_ready():
            self._update_status(
                "✅ Mesin utama siap. Masukkan URL untuk memulai.", 0.0, "0%")
            return

        os.makedirs(DEPENDENCY_DIR, exist_ok=True)
        self._splash = SplashOverlay(self)
        self.btn_check_url.configure(state="disabled")
        threading.Thread(target=self._download_dependencies,
                         daemon=True).start()

    def _download_dependencies(self):
        url_ytdlp = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        url_ffmpeg = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl-shared.zip"

        def _splash_update(text: str, pct: str = ""):
            if self._splash:
                # FIX: Cek self._splash di dalam lambda juga, karena antara
                # pengecekan di sini dan saat lambda berjalan di main thread,
                # _finish_splash mungkin sudah dipanggil dan men-set _splash = None.
                self.after(0, lambda t=text, p=pct:
                           self._splash and self._splash.set_status(t, p))

        def _splash_progress(value: float):
            if self._splash:
                self.after(0, lambda v=value:
                           self._splash and self._splash.set_progress(v))

        def _fetch_file(url: str, out_path: str, start_pct: float, end_pct: float, title: str):
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 65536
                last_pct = -1
                with open(out_path, "wb") as f:
                    while True:
                        # Hentikan unduhan dependency jika aplikasi ditutup
                        if self._shutdown_event.is_set():
                            return
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            ratio = downloaded / total_size
                            overall_pct = start_pct + \
                                (end_pct - start_pct) * ratio
                            pct_int = int(overall_pct * 100)
                            if pct_int != last_pct:
                                last_pct = pct_int
                                _splash_update(
                                    f"📥 Mengunduh {title}... ({format_size(downloaded)} / {format_size(total_size)})",
                                    f"{pct_int}%",
                                )
                                _splash_progress(overall_pct)

        zip_path = os.path.join(DEPENDENCY_DIR, "ffmpeg_temp.zip")

        try:
            if self._splash:
                self.after(0, lambda: self._splash.switch_to_determinate())

            # 1. Unduh yt-dlp
            _fetch_file(url_ytdlp, YTDLP_EXE, 0.0, 0.3, "Mesin Inti (yt-dlp)")

            # Validasi: pastikan file yt-dlp tidak corrupt/tidak lengkap
            if not os.path.exists(YTDLP_EXE) or os.path.getsize(YTDLP_EXE) < 1_000_000:
                raise Exception("File yt-dlp tidak lengkap. Koneksi mungkin terputus, coba jalankan ulang aplikasi.")

            # 2. Unduh FFmpeg
            _fetch_file(url_ffmpeg, zip_path, 0.3,
                        0.8, "Ekstensi Audio (FFmpeg)")

            # Validasi: pastikan zip FFmpeg tidak corrupt/tidak lengkap
            if not os.path.exists(zip_path) or os.path.getsize(zip_path) < 10_000_000:
                raise Exception("File FFmpeg tidak lengkap. Koneksi mungkin terputus, coba jalankan ulang aplikasi.")

            _splash_update("📦 Mengekstrak komponen mesin...", "85%")
            _splash_progress(0.85)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                for member in zip_ref.infolist():
                    fname = member.filename.replace("\\", "/")
                    if "/bin/" in fname and (fname.endswith(".exe") or fname.endswith(".dll")):
                        dest_path = os.path.join(
                            DEPENDENCY_DIR, os.path.basename(fname))
                        with zip_ref.open(member) as src, open(dest_path, "wb") as dst:
                            dst.write(src.read())

            if os.path.exists(zip_path):
                os.remove(zip_path)

            _splash_update(
                "✅ Semua komponen siap! Masukkan URL untuk mulai.", "100%")
            _splash_progress(1.0)

            self.after(900, self._finish_splash)
            self.after(0, lambda: self.btn_check_url.configure(state="normal"))
            self.after(0, lambda: self._update_status(
                "✅ Sistem siap. Masukkan URL untuk memulai."))

        except Exception as e:
            # Hapus file parsial agar tidak menyebabkan state corrupt pada
            # launch berikutnya (misal: yt-dlp.exe < 1MB atau zip tidak valid).
            for _partial in (YTDLP_EXE, zip_path):
                try:
                    if os.path.exists(_partial):
                        os.remove(_partial)
                except OSError:
                    pass

            err_str = str(e)
            if any(k in err_str.lower() for k in ("urlopen", "ssl", "timeout", "connection", "http")):
                err_msg = "❌ Gagal koneksi internet! Periksa jaringan, lalu restart aplikasi."
            else:
                err_msg = "❌ Diblokir Antivirus/Sistem! Letakkan yt-dlp.exe & ffmpeg.exe manual ke ~/.fetchdrop_engine"

            _splash_update(err_msg, "0%")
            self.after(4000, self._finish_splash)
            self.after(0, lambda: self.btn_check_url.configure(state="normal"))
            self.after(0, lambda m=err_msg: self._update_status(m, 0.0, "0%"))

    def _finish_splash(self):
        if self._splash:
            self._splash.dismiss()
            self._splash = None

    # =====================================================
    #   UPDATE ENGINE MANUAL
    # =====================================================

    def _update_engine(self):
        """Memperbarui modul yt-dlp secara mandiri."""
        # FIX: Cegah update saat sedang ada proses unduhan aktif
        if self._is_downloading:
            self._update_status(
                "⚠ Selesaikan unduhan terlebih dahulu sebelum update.", 0.0, "0%")
            return

        if not os.path.exists(YTDLP_EXE):
            self._update_status("❌ Mesin yt-dlp belum terpasang.", 0.0, "0%")
            return

        self.btn_update_engine.configure(
            state="disabled", text="⏳ Updating...")
        self._update_status(
            "Mengunduh pembaruan mesin pengunduh (yt-dlp)...", 0.5, "50%")

        def run_update():
            try:
                res = subprocess.run(
                    [YTDLP_EXE, "-U"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    startupinfo=get_startupinfo(),
                )
                if res.returncode == 0:
                    msg = "✅ Mesin berhasil diperbarui ke versi terbaru!"
                else:
                    msg = "⚠ Mesin sudah dalam versi terbaru (atau gagal akses server)."
                self.after(
                    0, lambda m=msg: self._update_status(m, 1.0, "100%"))
            except Exception as e:
                err = str(e)[:40]
                self.after(0, lambda m=err: self._update_status(
                    f"❌ Gagal update: {m}", 0, "0%"))
            finally:
                self.after(0, lambda: self.btn_update_engine.configure(
                    state="normal", text="🔄 Update Engine"
                ))

        threading.Thread(target=run_update, daemon=True).start()

    # =====================================================
    #   FETCH INFO MEDIA & DOWNLOAD
    # =====================================================

    def _load_video_info(self):
        url = self.url_entry.get().strip()
        if not url:
            return self._update_status("Form tautan kosong!", 0.0, "0%")

        if not os.path.exists(YTDLP_EXE):
            return self._update_status(
                "⚠ Mesin yt-dlp hilang! Tekan 'Update Engine' atau jalankan ulang aplikasi.", 0.0, "0%"
            )

        platform = detect_platform(url)
        if not platform:
            return self._update_status("Domain platform tidak didukung.", 0.0, "0%")

        self.current_platform = platform
        self.btn_check_url.configure(state="disabled")

        p_label = PLATFORM_LABELS[platform]
        msg_fetch = (
            f"🎬 Menganalisis video dari {p_label}..."
            if self.dl_mode == "video"
            else f"🎵 Menganalisis audio stream dari {p_label}..."
        )
        self._update_status(msg_fetch, 0.2, "20%")

        def _async_info():
            data, error = get_info(url, is_audio=(self.dl_mode == "audio"))

            if error:
                self.after(0, lambda: self._update_status(
                    "❌ Gagal memuat info video. Tautan terproteksi atau privat.", 0.0, "0%"
                ))
                self.after(0, lambda e=error: self.lbl_info_title.configure(
                    text=f"⚠ Validasi Gagal: {e[:60]}", text_color="#EF4444"
                ))
            else:
                # Update dropdown resolusi jika mode video
                if self.dl_mode == "video" and "available_resolutions" in data:
                    res = data["available_resolutions"]

                    def _apply_res(r=res):
                        self._last_video_resolutions = r   # simpan untuk mode switch
                        self.combo_res.configure(values=r)
                        self.combo_res.set(r[0])
                        self._update_quality_vars(r[0])
                    self.after(0, _apply_res)

                p_label_local = PLATFORM_LABELS.get(platform, platform)

                # FIX: Hindari tampilan "N/A Hz" atau "Unknown Hz" saat sample
                # rate tidak tersedia — Hz hanya ditampilkan jika nilainya valid.
                asr_val = data.get('asr', 'N/A')
                asr_str = f"{asr_val} Hz" if asr_val not in (
                    "N/A", "Unknown") else asr_val

                targets = [
                    (self.lbl_info_title,
                     f"[{p_label_local}] {data['title']}",
                     True),
                    (self.lbl_info_channel,
                     f"Uploader     : {data['channel']}",
                     False),
                    (self.lbl_info_meta1,
                     f"Durasi       : {data['duration']}   •   Rilis: {data['upload_date']}   •   Est. Ukuran: {data['size']}",
                     False),
                    (self.lbl_info_meta2,
                     (f"Codec Video  : {data.get('vcodec', 'N/A')}   •   Codec Audio: {data['acodec']}"
                      if self.dl_mode == "video"
                      else f"Audio Rate   : {asr_str}   •   Codec Audio: {data['acodec']}"),
                     False),
                ]

                # FIX: Mulai animasi fade-in dengan nomor versi baru agar
                # rantai animasi dari pemanggilan Cek Media sebelumnya dibatalkan.
                # Inkrement _fade_version dilakukan di main thread via after() agar aman.
                def _do_fade(tgts=targets):
                    self._fade_version += 1
                    self._fade_in_text(tgts, 0, self._fade_version)
                self.after(0, _do_fade)
                self.after(0, lambda u=url: setattr(
                    self, "current_info_url", u))

                msg_ready = (
                    "✅ Info video siap. Klik Download Video untuk mulai."
                    if self.dl_mode == "video"
                    else "✅ Info audio siap. Klik Extract MP3 untuk mulai."
                )
                self.after(
                    0, lambda m=msg_ready: self._update_status(m, 1.0, "100%"))
                self.after(0, lambda: self.btn_download.configure(
                    state="normal", fg_color=COLOR_ACCENT,
                    hover_color=COLOR_ACCENT_HOV, text_color=TEXT_MAIN,
                ))

            self.after(0, lambda: self.btn_check_url.configure(state="normal"))

        threading.Thread(target=_async_info, daemon=True).start()

    def _start_download(self):
        if not self.current_info_url or self._is_downloading:
            return

        self._is_downloading = True
        self._cancel_event.clear()

        self.btn_download.configure(
            state="disabled", fg_color="#1E1E22", text_color="#55555F")
        self.btn_check_url.configure(state="disabled")
        self.btn_cancel.configure(state="normal")

        url = self.current_info_url
        folder = self.download_folder
        platform = self.current_platform or "youtube"

        cmd = [YTDLP_EXE, "--newline", "--no-warnings"]
        ffmpeg_loc = get_ffmpeg_location()
        if ffmpeg_loc:
            cmd.extend(["--ffmpeg-location", ffmpeg_loc])

        if self.dl_mode == "video":
            # Untuk platform selain YouTube, gunakan format fallback yang lebih kompatibel
            fmt = self.vformat if platform == "youtube" else "b/bv*+ba/b"
            cmd.extend([
                "-f", fmt,
                "--restrict-filenames",
                "-o", os.path.join(folder,
                                   "%(uploader).20s - %(title).40s [%(height)sp].%(ext)s"),
            ])
            if self.container != "auto":
                cmd.extend(["--merge-output-format", self.container])
        else:
            cmd.extend([
                "-f", "ba/b",
                "--restrict-filenames",
                "-o", os.path.join(folder,
                                   "%(uploader).20s - %(title).40s.%(ext)s"),
                "--embed-thumbnail",
                "--add-metadata",
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", self.aquality,
            ])

        cmd.append(url)

        def _run_dl():
            self.after(0, lambda: self._update_status(
                "🎬 Menyiapkan instruksi unduhan...", 0.0, "0%"))

            try:
                self._dl_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    startupinfo=get_startupinfo(),
                )

                for line in self._dl_process.stdout:
                    if self._cancel_event.is_set() or self._shutdown_event.is_set():
                        self._dl_process.terminate()
                        break

                    line = line.strip()
                    if not line:
                        continue

                    if "[download]" in line and "%" in line and "ETA" in line:
                        try:
                            m = re.search(r"(\d+\.?\d*)%", line)
                            if m:
                                pct_val = float(m.group(1))
                                speed_eta = line.split(" at ")[-1].strip()
                                val = pct_val / 100.0
                                pct_disp = f"{int(pct_val)}%"
                                aksi = "🎬 Mengunduh video" if self.dl_mode == "video" else "🎵 Mengunduh audio"
                                self.after(0, lambda v=val, p=pct_disp, a=aksi, e=speed_eta:
                                           self._update_status(f"{a} • {e}", v, p))
                        except ValueError:
                            pass

                    elif line.startswith("[Merger]") or line.startswith("[ExtractAudio]"):
                        msg_finish = (
                            "⚙️ Menggabungkan track video & audio..."
                            if self.dl_mode == "video"
                            else "⚙️ Mengonversi ke MP3 & embed cover..."
                        )
                        self.after(
                            0, lambda m=msg_finish: self._update_status(m, 0.95, "95%"))

                self._dl_process.wait()

                if self._cancel_event.is_set():
                    self.after(0, lambda: self._update_status(
                        "⛔ Unduhan dibatalkan.", 0.0, "0%"))
                elif self._dl_process.returncode == 0:
                    self.download_count += 1
                    self._save_current_config()
                    msg_succ = (
                        "✅ Video berhasil disimpan."
                        if self.dl_mode == "video"
                        else "✅ MP3 berhasil diekstrak."
                    )
                    self.after(
                        0, lambda m=msg_succ: self._update_status(m, 1.0, "100%"))
                else:
                    self.after(0, lambda: self._update_status(
                        "❌ Gagal mengunduh berkas. Coba gunakan fitur Update Engine.", 0.0, "0%"
                    ))

            except Exception as e:
                err = str(e)[:50]
                self.after(0, lambda m=err: self._update_status(
                    f"❌ Error: {m}", 0.0, "0%"))
            finally:
                self._is_downloading = False
                self._dl_process = None
                # Jangan sentuh widget jika aplikasi sudah ditutup
                if not self._shutdown_event.is_set():
                    self.after(0, lambda: self.btn_download.configure(
                        state="normal", fg_color=COLOR_ACCENT,
                        hover_color=COLOR_ACCENT_HOV, text_color=TEXT_MAIN,
                    ))
                    self.after(
                        0, lambda: self.btn_check_url.configure(state="normal"))
                    self.after(0, lambda: self.btn_cancel.configure(
                        state="disabled"))

        threading.Thread(target=_run_dl, daemon=True).start()


if __name__ == "__main__":
    app = YTDownloaderApp()
    app.mainloop()
