<div align="center">

<img src="https://img.shields.io/badge/FetchDrop-v1.0-red?style=for-the-badge&logo=lightning&logoColor=white" alt="FetchDrop"/>

# ⚡ FetchDrop
### Universal Media Downloader — Video & Audio Extractor

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-green?style=flat-square)](https://github.com/TomSchimansky/CustomTkinter)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey?style=flat-square&logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![yt-dlp](https://img.shields.io/badge/Engine-yt--dlp%20%2B%20FFmpeg-red?style=flat-square)](https://github.com/yt-dlp/yt-dlp)

**FetchDrop** adalah aplikasi pengunduh media universal dengan antarmuka grafis modern. Dibangun menggunakan Python dan CustomTkinter, dengan arsitektur *Decoupled Engine* yang ringan dan efisien.

</div>

---

## 🖥️ Preview Tampilan

![FetchDrop GUI Preview](preview.PNG)

> *Antarmuka Video Downloader dengan tema gelap (Dark Mode) yang bersih dan modern.*

---

## ✨ Fitur Utama

| Fitur | Deskripsi |
|-------|-----------|
| 🔌 **Decoupled Engine** | Mesin inti (`yt-dlp.exe` + `ffmpeg`) tidak di-bundle ke `.exe`, diunduh otomatis ke `~/.fetchdrop_engine` saat *first run* — ukuran aplikasi tetap ringan |
| 🎬 **Multi-Platform** | Mendukung YouTube (Video, Shorts, Playlist, Music), TikTok, Instagram (Reels, Post, TV), dan X / Twitter |
| 🎵 **MP3 Extractor Pintar** | Konversi video ke MP3 murni dengan *Constant Bitrate* (CBR) hingga 320 kbps, lengkap dengan metadata dan cover art |
| 🎯 **Resolusi Cerdas** | Filter Anti-Storyboard yang memilih resolusi asli (hingga 4K) dan mengabaikan format thumbnail/storyboard palsu |
| ⚡ **UI Asinkronus** | Antarmuka tidak pernah *freeze* berkat implementasi `threading` penuh, progress bar smooth, dan dukungan DPI Awareness |
| 🛡️ **Error Handling** | Penghentian proses bersih (*graceful shutdown*), deteksi error jaringan, dan penanganan intervensi Windows Defender |

---

## 🌐 Platform yang Didukung

<div align="center">

|  | Platform | Format |
|--|----------|--------|
| 📺 | **YouTube** | Video, Shorts, Playlist, Music |
| 🎵 | **TikTok** | Video, Slideshow |
| 📸 | **Instagram** | Reels, Post, TV |
| 🐦 | **X / Twitter** | Video, GIF |

</div>

---

## 🛠️ Prasyarat (Untuk Developer)

Sebelum menjalankan atau melakukan *build* dari *source code*, pastikan sistem Anda memiliki:

- **Python 3.10** atau lebih baru
- **OS Windows 10 / 11**
- **Koneksi internet** (untuk unduh mesin otomatis saat pertama kali dijalankan)

### Dependencies

Instal semua library yang dibutuhkan menggunakan `requirements.txt`:

```
customtkinter
Pillow
darkdetect
```

```bash
pip install -r requirements.txt
```

---

## 🚀 Instalasi & Build

### Langkah 1 — Clone Repositori

```bash
git clone https://github.com/USERNAME_ANDA/FetchDrop.git
cd FetchDrop
```

### Langkah 2 — Siapkan Virtual Environment & Instal Dependensi

> Disarankan menggunakan *Virtual Environment* yang bersih agar ukuran *build* tetap kecil.

```bash
python -m venv env
env\Scripts\activate
pip install -r requirements.txt
```

### Langkah 3 — Build ke `.exe` menggunakan PyInstaller

Jalankan perintah berikut untuk kompilasi optimal (bebas *false positive* antivirus):

```bash
pyinstaller --noconsole --onefile --noupx --clean --icon=icon.ico --add-data "icon.ico;." --collect-all customtkinter -n FetchDrop fetchdrop.py
```

> **📁 Output:** File hasil *build* akan berada di `dist/FetchDrop.exe`

---

## 💡 Cara Penggunaan

```
1. Buka FetchDrop.exe
   └── Saat pertama kali, aplikasi otomatis mengunduh mesin (yt-dlp + ffmpeg)
   
2. Pilih mode di sidebar kiri
   ├── 🎬 Video Downloader
   └── 🎵 Audio MP3 Extractor

3. Tempel (paste) URL video di kolom input
   └── Klik tombol [Cek Media]

4. Tunggu analisis selesai
   └── Judul, uploader, durasi, resolusi, dan estimasi ukuran akan tampil

5. Sesuaikan pengaturan
   ├── Kualitas Video (Best / 1080p / 720p / dll)
   └── Format Container (MP4 / MKV / Format Asli)

6. Klik [DOWNLOAD VIDEO] atau [EKSTRAK MP3]
   └── File otomatis tersimpan di folder Downloads (atau folder yang dipilih)
```

---

## 🗂️ Struktur Proyek

```
FetchDrop/
├── fetchdrop.py        # Source code utama
├── icon.ico            # Ikon aplikasi
├── requirements.txt    # Daftar dependensi Python
├── preview.PNG         # Screenshot tampilan GUI
├── LICENSE             # Lisensi MIT
└── README.md           # Dokumentasi ini
```

---

## ❓ FAQ

**Q: Apakah saya perlu menginstal yt-dlp atau ffmpeg secara manual?**
> Tidak. FetchDrop akan mengunduh dan mengonfigurasi kedua mesin ini secara otomatis ke folder `~/.fetchdrop_engine` saat pertama kali dijalankan.

**Q: Windows Defender memblokir aplikasi. Apa yang harus dilakukan?**
> Ini adalah *false positive* umum pada aplikasi Python yang di-*compile*. Tambahkan `FetchDrop.exe` ke *exclusion list* Windows Defender, atau jalankan langsung dari *source code*.

**Q: Mengapa unduhan gagal pada beberapa video?**
> Kemungkinan mesin `yt-dlp` sudah kedaluwarsa. Klik tombol **Update Engine** di sidebar kiri untuk memperbarui ke versi terbaru.

**Q: Di mana file hasil unduhan tersimpan?**
> Secara default di folder `Downloads` sistem Anda. Lokasi ini bisa diubah melalui tombol **Ubah** di bagian bawah aplikasi.

---

## 📜 Lisensi

Proyek ini didistribusikan di bawah **MIT License**.
Lihat file [`LICENSE`](LICENSE) untuk informasi lengkap.

---

<div align="center">

Dibuat dengan ❤️ menggunakan Python & CustomTkinter

⭐ Jika proyek ini bermanfaat, jangan lupa beri bintang di GitHub!

</div>
