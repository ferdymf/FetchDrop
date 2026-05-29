# ⚡ FetchDrop

**FetchDrop** adalah aplikasi pengunduh media universal (Video & Audio Extractor) berantarmuka grafis modern. Dibangun menggunakan Python dan **CustomTkinter**, aplikasi ini menggunakan arsitektur *Decoupled Engine* di mana komponen pengunduh inti (`yt-dlp` dan `FFmpeg`) dipisahkan dari *source code* utama dan diunduh secara otomatis pada saat aplikasi pertama kali dijalankan.

## ✨ Fitur Utama

* **Arsitektur Decoupled Engine:** Aplikasi ini sangat ringan. Mesin inti (`yt-dlp.exe` dan `ffmpeg`) tidak di-*bundle* ke dalam `.exe`, melainkan diunduh otomatis ke `~/.fetchdrop_engine` saat *first run*.
* **Multi-Platform Support:** Mendukung ekstraksi media dari platform populer:
* YouTube (Video, Shorts, Playlist, Music)
* TikTok
* Instagram (Reels, Post, TV)
* X / Twitter


* **Ekstraktor MP3 Pintar:** Mengonversi video menjadi format audio murni (MP3) dengan *Constant Bitrate* (CBR) yang bisa disesuaikan (hingga 320 kbps), lengkap dengan *metadata* dan *cover art*.
* **Resolusi Cerdas (Anti-Storyboard):** Filter pintar yang menyeleksi resolusi asli (hingga 4K) dan mengabaikan format *thumbnail/storyboard* palsu.
* **Modern & Asynchronous UI:** Dibangun dengan CustomTkinter (Dark Mode). Antarmuka tidak akan pernah *freeze* berkat implementasi `threading` penuh untuk setiap tugas berat, lengkap dengan animasi *progress bar* yang *smooth* dan dukungan *DPI Awareness* untuk resolusi layar tinggi.
* **Graceful Shutdown & Error Handling:** Penghentian proses latar belakang secara bersih (*clean kill*) saat aplikasi ditutup paksa, serta pemisahan deteksi *error* antara masalah koneksi jaringan dan intervensi Windows Defender.

---

## 🛠️ Prasyarat (Untuk Developer)

Jika Anda ingin menjalankan atau melakukan *build* dari *source code*, pastikan sistem Anda memiliki:

* **Python 3.10** atau lebih baru.
* OS Windows 10/11.

Library yang dibutuhkan (bisa diinstal via `requirements.txt`):

* `customtkinter`
* `Pillow`
* `darkdetect`

---

## 🚀 Instalasi & Build (Jadikan .exe)

Bagi Anda yang ingin mengompilasi ulang *source code* ini menjadi *Single Executable* (`.exe`), ikuti langkah berikut:

**1. Clone Repositori**

```bash
git clone https://github.com/USERNAME_ANDA/FetchDrop.git
cd FetchDrop

```

**2. Siapkan Virtual Environment & Instal Dependensi**
Disarankan menggunakan *Virtual Environment* yang bersih agar ukuran *build* tetap kecil.

```bash
python -m venv env
env\Scripts\activate
pip install -r requirements.txt

```

**3. Build menggunakan PyInstaller**
Jalankan perintah ini untuk melakukan kompilasi dengan setelan paling optimal (bebas *false positive* Antivirus):

```bash
pyinstaller --noconsole --onefile --noupx --clean --icon=icon.ico --add-data "icon.ico;." --collect-all customtkinter -n FetchDrop fetchdrop.py

```

> **Catatan:** File hasil *build* akan berada di dalam folder `dist/FetchDrop.exe`.

---

## 💡 Cara Penggunaan

1. Buka aplikasi **FetchDrop**. (Pada penggunaan pertama, aplikasi akan mengunduh mesin di latar belakang).
2. Pilih mode unduhan di *sidebar* kiri (**Video Downloader** atau **Audio MP3 Extractor**).
3. Tempel (*paste*) tautan video di kolom yang disediakan, lalu klik **Cek Media**.
4. Tunggu aplikasi menganalisis data, resolusi, dan estimasi ukuran *file*.
5. Sesuaikan **Kualitas** dan **Format Container** (MP4/MKV) sesuai kebutuhan.
6. Klik **MULAI UNDUH**. Berkas akan otomatis tersimpan di folder `Downloads` (atau folder yang Anda tentukan).

---

## 👨‍💻 Author

**Ferdy M. Firdaus**

## 📜 Lisensi

Proyek ini didistribusikan di bawah lisensi **MIT License**. Silakan lihat file `LICENSE` untuk informasi lebih lanjut.
