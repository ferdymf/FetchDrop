# ⚡ FetchDrop

**FetchDrop** adalah aplikasi pengunduh media universal (Video & Audio Extractor) berantarmuka grafis modern. Dibangun menggunakan Python dan **CustomTkinter**, aplikasi ini menerapkan arsitektur *Decoupled Engine* di mana komponen pengunduh inti (`yt-dlp` dan `FFmpeg`) dipisahkan dari paket *executable* utama dan akan diunduh secara otomatis ke direktori lokal saat aplikasi pertama kali dijalankan.

## ✨ Fitur Utama

* **Arsitektur Decoupled Engine:** Membuat ukuran aplikasi sangat ringan. Mesin inti (`yt-dlp.exe` dan `ffmpeg`) tidak dibungkus di dalam `.exe`, melainkan diunduh otomatis ke folder `~/.fetchdrop_engine` saat pertama kali dijalankan.
* **Multi-Platform Support:** Mendukung ekstraksi dan pengunduhan media dari berbagai platform populer:
* YouTube (Video, Shorts, Playlist, Music)
* TikTok
* Instagram (Reels, Post, TV)
* X / Twitter


* **Ekstraktor MP3 Pintar:** Mengonversi video menjadi format audio murni (MP3) dengan *Constant Bitrate* (CBR) yang bisa disesuaikan (hingga 320 kbps), lengkap dengan penyuntikan *metadata* dan *cover art*.
* **Resolusi Cerdas (Anti-Storyboard):** Filter pintar pada sistem pendeteksi resolusi asli (hingga 4K) yang otomatis mengabaikan format *thumbnail* atau *storyboard* pratinjau.
* **Modern & Asynchronous UI:** Menggunakan tema *Dark Mode* dari CustomTkinter. Antarmuka GUI dipastikan tidak akan pernah membeku (*freeze*) karena setiap proses berat berjalan di latar belakang menggunakan *asynchronous threading*, dilengkapi animasi *progress bar* yang halus serta dukungan *DPI Awareness* (anti-blur pada layar resolusi tinggi).
* **Graceful Shutdown:** Mekanisme penghentian proses latar belakang secara bersih (*clean kill*) terhadap *subprocess* `yt-dlp` yang sedang aktif ketika jendela aplikasi ditutup oleh pengguna.

---

## 🛠️ Prasyarat (Untuk Developer)

Jika Anda ingin menjalankan aplikasi dari *source code* atau melakukan kompilasi mandiri, pastikan sistem Anda memenuhi spesifikasi berikut:

* **Python 3.10** atau versi di atasnya.
* Sistem Operasi Windows 10 / 11.

Library Python pihak ketiga yang diperlukan:

* `customtkinter`
* `Pillow`
* `darkdetect`

---

## 🚀 Instalasi & Kompilasi (Jadikan .exe)

Jalankan perintah berikut di Command Prompt atau Terminal untuk menyiapkan proyek dan membangun file `.exe`:

**1. Unduh Proyek**
git clone [https://github.com/USERNAME_ANDA/FetchDrop.git](https://www.google.com/search?q=https://github.com/USERNAME_ANDA/FetchDrop.git)
cd FetchDrop

**2. Instal Dependensi**
Anda dapat langsung menginstal dependensi ke *environment* global Python Anda. Namun, menggunakan *Virtual Environment* (Venv) **sangat disarankan** khusus saat proses *build* agar PyInstaller tidak ikut menarik library global lain yang tidak digunakan (mencegah ukuran file `.exe` membengkak).

# (Opsional - Sangat Direkomendasikan) Membuat & mengaktifkan virtual environment

python -m venv env
env\Scripts\activate

# Menginstal library yang dibutuhkan aplikasi

pip install -r requirements.txt

**3. Build Menggunakan PyInstaller**
Gunakan perintah optimal berikut untuk menghasilkan file *Single Executable* (`.exe`) mandiri yang bersih dari *false positive* Antivirus (Windows Defender):
pyinstaller --noconsole --onefile --noupx --clean --icon=icon.ico --add-data "icon.ico;." --collect-all customtkinter -n FetchDrop fetchdrop.py

> **Catatan:** Setelah proses kompilasi selesai, file aplikasi siap pakai bernama `FetchDrop.exe` dapat Anda temukan di dalam folder `dist/`.

---

## 💡 Cara Penggunaan

1. Jalankan aplikasi **FetchDrop** (pada *first run*, biarkan aplikasi menyelesaikan unduhan komponen mesin di latar belakang hingga selesai).
2. Pilih kategori unduhan pada *sidebar* kiri (**Video Downloader** atau **Audio MP3 Extractor**).
3. Tempel (*paste*) tautan media ke kolom input URL, lalu klik tombol **Cek Media**.
4. Setelah informasi media muncul, tentukan opsi kualitas resolusi atau bitrate MP3 serta format container (MP4/MKV) yang diinginkan.
5. Klik **MULAI UNDUH**. Berkas yang terunduh secara otomatis akan tersimpan di folder tujuan pilihan Anda (default: folder `Downloads` sistem).

---

## 👨‍💻 Author

**Ferdy M. Firdaus**

## 📜 Lisensi

Proyek ini dilisensikan di bawah **MIT License** — Bebas digunakan, dimodifikasi, dan didistribusikan dengan tetap menyertakan kredit hak cipta asli. Lihat berkas `LICENSE` untuk informasi selengkapnya.
