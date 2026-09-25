# Konfigurasi otomatis server Minecraft RaeHost

RaeHost memakai **Pterodactyl Panel** (`panel.raehost.com`). Folder ini berisi
skrip yang mengatur server Anda lewat API panel tersebut, jadi Anda tidak perlu
mengedit file satu per satu di File Manager.

Yang bisa diatur dari satu file, [`server-config.toml`](server-config.toml):

- **server.properties**: MOTD, jumlah pemain, difficulty, gamemode, PvP, whitelist, dan lainnya
- **Variabel startup**: versi Minecraft, build, dan sebagainya (dengan reinstall otomatis kalau diminta)
- **Plugin**: dipasang otomatis dari [Modrinth](https://modrinth.com/plugins) atau dari URL `.jar` langsung
- **Perintah konsol**: `op`, `whitelist add`, `gamerule`, dan perintah lain
- **Restart otomatis** setelah ada perubahan

Skrip hanya mengubah hal yang Anda tulis. Sebelum menulis `server.properties`,
salinan lamanya disimpan sebagai `server.properties.bak`. Kalau dijalankan
berulang kali tanpa perubahan di config, tidak ada yang diubah dan server tidak
di-restart.

## Langkah 1: Buat API key di panel RaeHost

1. Login ke <https://panel.raehost.com>.
2. Klik ikon akun (kanan atas), lalu **API Credentials**.
3. Isi *Description* dengan `GitHub`. Kosongkan *Allowed IPs* (IP GitHub
   Actions selalu berubah).
4. Klik **Create** lalu salin key yang diawali `ptlc_`. Key hanya ditampilkan
   sekali.

> API key ini memberi akses penuh ke semua server Anda di panel. Jangan tulis di
> file, jangan dikirim ke siapa pun. Kalau bocor, hapus di halaman yang sama
> dan buat yang baru.

## Langkah 2: Catat ID server

Buka server Anda di panel. ID-nya ada di URL:
`https://panel.raehost.com/server/`**`1a2b3c4d`**

## Langkah 3: Simpan sebagai secret di GitHub

Di repositori ini: **Settings → Secrets and variables → Actions → New repository secret**.
Buat dua secret:

| Name              | Secret                  |
| ----------------- | ----------------------- |
| `PTERO_API_KEY`   | key `ptlc_...` dari langkah 1 |
| `PTERO_SERVER_ID` | ID server dari langkah 2 |

## Langkah 4: Atur dan jalankan

1. Edit [`server-config.toml`](server-config.toml) (bisa langsung di GitHub
   dengan ikon pensil), lalu **Commit** ke branch `main`.
2. Workflow **Konfigurasi server Minecraft** berjalan otomatis. Lihat hasilnya
   di tab **Actions**.

Mau lihat dulu apa yang akan berubah? Buka tab **Actions → Konfigurasi server
Minecraft → Run workflow**, centang *Uji coba saja*, lalu **Run workflow**.

## Menjalankan dari komputer sendiri (opsional)

Butuh [Python 3.11+](https://www.python.org/downloads/). Tidak perlu install
paket lain.

```bash
# Linux / macOS
export PTERO_API_KEY="ptlc_..."
export PTERO_SERVER_ID="1a2b3c4d"
python3 minecraft/configure.py --dry-run   # uji coba
python3 minecraft/configure.py             # terapkan
```

```powershell
# Windows (PowerShell)
$env:PTERO_API_KEY = "ptlc_..."
$env:PTERO_SERVER_ID = "1a2b3c4d"
python minecraft\configure.py --dry-run
python minecraft\configure.py
```

Opsi lain: `--no-restart` (jangan restart server) dan `--config file.toml`
(pakai file konfigurasi lain).

## Kalau ada masalah

| Pesan | Artinya |
| ----- | ------- |
| `HTTP 401` | API key salah atau sudah dihapus. Buat ulang di langkah 1. |
| `HTTP 403` | Key tidak punya akses ke server ini, atau *Allowed IPs* di key membatasi IP. |
| `HTTP 404` saat membuka server | ID server salah. Salin lagi dari URL panel. |
| `Folder /plugins belum ada` | Server Anda bukan Paper/Spigot/Purpur. Ganti jenis server lewat fitur *Egg Changer* di panel kalau ingin pakai plugin. |
| `tidak mencantumkan versi Minecraft ...` | Plugin belum ada untuk versi itu di Modrinth. Kosongkan `game_version` atau pakai `url`. |
| `dikunci oleh RaeHost` | Variabel startup itu tidak boleh diubah oleh pelanggan. |
| Server tidak mau menyala | Buka tab **Console** di panel untuk melihat error. `server.properties.bak` berisi pengaturan sebelumnya. |

Untuk memperbarui plugin ke versi baru, hapus `.jar` lamanya di folder
`/plugins` lewat File Manager, lalu jalankan skrip lagi.
