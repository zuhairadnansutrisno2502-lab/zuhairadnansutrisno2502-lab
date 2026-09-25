#!/usr/bin/env python3
"""Apply minecraft/server-config.toml to a Minecraft server on a Pterodactyl
panel (RaeHost uses Pterodactyl) through the panel's Client API.

Environment:
  PTERO_API_KEY    client API key (ptlc_...), required
  PTERO_SERVER_ID  server identifier, overrides [panel].server_id
  PTERO_PANEL_URL  panel URL, overrides [panel].url

Needs Python 3.11+ and nothing outside the standard library.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit("Butuh Python 3.11 atau lebih baru.")

USER_AGENT = "raehost-minecraft-config/1.0 (github.com/zuhairadnansutrisno2502-lab)"
MODRINTH_API = "https://api.modrinth.com/v2"
# The Pterodactyl Minecraft eggs rewrite these on every start.
PANEL_MANAGED_PROPERTIES = {"server-ip", "server-port", "query.port"}
PLAYER_NAME = re.compile(r"^[A-Za-z0-9_.]{2,16}$")
IN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"

problems = []


def log(message=""):
    print(message, flush=True)


def warn(message):
    problems.append(message)
    print(f"::warning::{message}" if IN_ACTIONS else f"PERINGATAN: {message}", flush=True)


def fail(message):
    print(f"::error::{message}" if IN_ACTIONS else f"GAGAL: {message}", file=sys.stderr, flush=True)
    sys.exit(1)


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(f"HTTP {status}: {detail}" if status else detail)
        self.status = status


def http(method, url, *, headers=None, data=None, timeout=120):
    headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise ApiError(error.code, error_detail(error.read())) from None
    except urllib.error.URLError as error:
        raise ApiError(0, f"tidak bisa terhubung ke {url}: {error.reason}") from None


def error_detail(body):
    try:
        errors = json.loads(body)["errors"]
        return "; ".join(e.get("detail") or e.get("code", "") for e in errors)
    except (ValueError, KeyError, TypeError):
        return body.decode("utf-8", "replace")[:300] or "(tanpa pesan)"


class Panel:
    def __init__(self, panel_url, api_key, server_id):
        self.base = f"{panel_url.rstrip('/')}/api/client/servers/{server_id}"
        self.api_key = api_key

    def call(self, method, path="", *, query=None, json_body=None, text_body=None, raw=False):
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif text_body is not None:
            data = text_body.encode()
            headers["Content-Type"] = "text/plain"
        body = http(method, url, headers=headers, data=data)
        if raw:
            return body.decode("utf-8", "replace")
        return json.loads(body) if body else None

    def server(self):
        return self.call("GET")["attributes"]

    def state(self):
        return self.call("GET", "/resources")["attributes"]["current_state"]

    def list_dir(self, directory):
        """File names in `directory`, or None when it does not exist."""
        try:
            listing = self.call("GET", "/files/list", query={"directory": directory})
        except ApiError as error:
            if error.status == 404:
                return None
            raise
        return [item["attributes"]["name"] for item in listing["data"]]


# ---------------------------------------------------------------------------
# server.properties
# ---------------------------------------------------------------------------

def property_text(key, value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    raise ValueError(f"nilai '{key}' harus teks, angka, atau true/false")


def decode_property(raw):
    """Unescape a Java .properties value."""
    raw = raw.lstrip()
    out, i = [], 0
    while i < len(raw):
        char = raw[i]
        if char == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "u":
                try:
                    out.append(chr(int(raw[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            out.append({"t": "\t", "n": "\n", "r": "\r", "f": "\f"}.get(nxt, nxt))
            i += 2
            continue
        out.append(char)
        i += 1
    # \uD83D\uDE00-style surrogate pairs back into one character
    return "".join(out).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def encode_property(value):
    """Escape a value so Java's Properties.load reads it back unchanged,
    whatever charset the server reads the file with."""
    out = []
    for index, char in enumerate(value):
        if char == "\\":
            out.append("\\\\")
        elif char == " " and index == 0:
            out.append("\\ ")
        elif 32 <= ord(char) < 127:
            out.append(char)
        else:
            units = char.encode("utf-16-be")
            out.extend(f"\\u{int.from_bytes(units[k:k + 2], 'big'):04X}" for k in range(0, len(units), 2))
    return "".join(out)


def merge_properties(text, wanted):
    """Return (new_text, changes) with `wanted` applied, keeping every other
    line, comment and the original order intact."""
    lines, changes, written = [], [], set()
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped and stripped[0] not in "#!" and "=" in stripped:
            key, _, raw_value = stripped.partition("=")
            key = key.strip()
            if key in wanted:
                written.add(key)
                old = decode_property(raw_value)
                if old != wanted[key]:
                    changes.append((key, old, wanted[key]))
                    line = f"{key}={encode_property(wanted[key])}"
        lines.append(line)
    for key, value in wanted.items():
        if key not in written:
            changes.append((key, None, value))
            lines.append(f"{key}={encode_property(value)}")
    return "\n".join(lines) + "\n", changes


def apply_properties(panel, settings, dry_run):
    wanted = {}
    for key, value in settings.items():
        if key in PANEL_MANAGED_PROPERTIES:
            warn(f"'{key}' diatur otomatis oleh panel, jadi dilewati.")
            continue
        wanted[key] = property_text(key, value)
    if not wanted:
        return False

    log("\n== server.properties ==")
    try:
        current = panel.call("GET", "/files/contents", query={"file": "/server.properties"}, raw=True)
    except ApiError as error:
        if error.status != 404:
            raise
        current = None
        log("server.properties belum ada (server belum pernah dinyalakan); file baru akan dibuat.")

    new_text, changes = merge_properties(current or "", wanted)
    if not changes:
        log("Sudah sesuai, tidak ada yang diubah.")
        return False
    for key, old, new in changes:
        log(f"  {key}: {'(baru)' if old is None else repr(old)} -> {new!r}")
    if dry_run:
        return True

    if current is not None:
        panel.call("POST", "/files/write", query={"file": "/server.properties.bak"}, text_body=current)
        log("Salinan lama disimpan sebagai server.properties.bak")
    panel.call("POST", "/files/write", query={"file": "/server.properties"}, text_body=new_text)
    log(f"{len(changes)} pengaturan diperbarui.")
    return True


# ---------------------------------------------------------------------------
# Startup variables
# ---------------------------------------------------------------------------

def apply_startup(panel, settings, dry_run):
    wanted = {key: property_text(key, value) for key, value in settings.items() if key != "reinstall_after_change"}

    log("\n== Variabel startup ==")
    variables = {v["attributes"]["env_variable"]: v["attributes"] for v in panel.call("GET", "/startup")["data"]}
    for name, var in variables.items():
        value = var["server_value"] if var["server_value"] is not None else var["default_value"]
        lock = "" if var["is_editable"] else "  [terkunci]"
        log(f"  {name} = {value!r}  ({var['name']}){lock}")

    changed = False
    for key, value in wanted.items():
        var = variables.get(key)
        if var is None:
            warn(f"Variabel startup '{key}' tidak ada di server ini. Pilihan: {', '.join(variables) or '-'}")
            continue
        current = var["server_value"] if var["server_value"] is not None else var["default_value"]
        if current == value:
            continue
        if not var["is_editable"]:
            warn(f"Variabel startup '{key}' dikunci oleh RaeHost dan tidak bisa diubah.")
            continue
        log(f"Ubah {key}: {current!r} -> {value!r}")
        if not dry_run:
            try:
                panel.call("PUT", "/startup/variable", json_body={"key": key, "value": value})
            except ApiError as error:
                warn(f"Gagal mengubah {key}: {error}")
                continue
        changed = True
    if not changed:
        log("Tidak ada variabel startup yang diubah.")
    return changed


def reinstall(panel, timeout):
    log("\nMenjalankan reinstall agar versi baru diunduh...")
    panel.call("POST", "/settings/reinstall")

    def installing():
        server = panel.server()
        return server.get("is_installing") or server.get("status") == "installing"

    deadline = time.monotonic() + 30
    while not installing() and time.monotonic() < deadline:
        time.sleep(3)
    deadline = time.monotonic() + timeout
    while installing():
        if time.monotonic() > deadline:
            fail("Reinstall belum selesai setelah batas waktu. Cek panel RaeHost.")
        time.sleep(5)
    if panel.server().get("status") == "install_failed":
        fail("Reinstall gagal. Cek tab Console di panel RaeHost.")
    log("Reinstall selesai.")


# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------

def plugin_stem(filename):
    """'LuckPerms-Bukkit-5.4.141.jar' -> 'luckperms-bukkit', so a different
    version of an installed plugin is recognised and not added twice."""
    stem = re.split(r"[-_ ]?v?\d", filename, maxsplit=1)[0]
    return stem.strip("-_ ").lower() or filename.lower()


def resolve_plugin(entry, settings):
    """Return (label, download_url, filename)."""
    if "modrinth" in entry:
        slug = entry["modrinth"]
        query = {"loaders": json.dumps(settings.get("loaders", ["paper", "spigot", "bukkit"]))}
        if settings.get("game_version"):
            query["game_versions"] = json.dumps([settings["game_version"]])
        url = f"{MODRINTH_API}/project/{urllib.parse.quote(slug)}/version?{urllib.parse.urlencode(query)}"
        try:
            versions = json.loads(http("GET", url))
        except ApiError as error:
            if error.status == 404:
                raise ValueError(f"plugin '{slug}' tidak ditemukan di Modrinth") from None
            raise
        if not versions:
            if settings.get("game_version"):
                raise ValueError(f"'{slug}' tidak mencantumkan versi Minecraft {settings['game_version']} di Modrinth; "
                                 "kosongkan game_version atau pakai url langsung")
            raise ValueError(f"'{slug}' tidak punya versi untuk loader {query['loaders']}")
        version = next((v for v in versions if v["version_type"] == "release"), versions[0])
        file = next((f for f in version["files"] if f["primary"]), version["files"][0])
        return entry.get("name", slug), file["url"], file["filename"]
    if "url" in entry:
        filename = entry.get("filename") or Path(urllib.parse.urlparse(entry["url"]).path).name
        if not filename.endswith(".jar"):
            raise ValueError(f"tambahkan filename = \"...jar\" untuk {entry['url']}")
        return entry.get("name", filename), entry["url"], filename
    raise ValueError("setiap plugin butuh 'modrinth' atau 'url'")


def upload_plugin(panel, url, filename):
    try:
        panel.call("POST", "/files/pull", json_body={
            "url": url, "directory": "/plugins", "filename": filename, "foreground": True,
        })
        return
    except ApiError as error:
        log(f"  Panel tidak bisa mengunduh langsung ({error}); mengunggah lewat skrip...")
    jar = http("GET", url, timeout=300)
    target = panel.call("GET", "/files/upload")["attributes"]["url"]
    target += "&directory=" + urllib.parse.quote("/plugins")
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        "Content-Type: application/java-archive\r\n\r\n"
    ).encode() + jar + f"\r\n--{boundary}--\r\n".encode()
    http("POST", target, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, data=body, timeout=300)


def install_plugins(panel, settings, dry_run):
    entries = settings.get("install", [])
    if not entries:
        return False

    log("\n== Plugin ==")
    existing = panel.list_dir("/plugins")
    if existing is None:
        log("Folder /plugins belum ada. Pastikan server Anda Paper/Spigot/Purpur, bukan Vanilla/Forge/Fabric.")
        if not dry_run:
            panel.call("POST", "/files/create-folder", json_body={"root": "/", "name": "plugins"})
        existing = []
    installed = {plugin_stem(name): name for name in existing if name.lower().endswith(".jar")}

    changed = False
    for entry in entries:
        try:
            label, url, filename = resolve_plugin(entry, settings)
        except (ValueError, ApiError) as error:
            warn(f"Plugin dilewati: {error}")
            continue
        present = installed.get(plugin_stem(filename))
        if present:
            note = "" if present == filename else f" (versi lain: {present}; hapus dulu untuk memperbarui)"
            log(f"  {label}: sudah terpasang{note}")
            continue
        log(f"  {label}: memasang {filename}")
        if not dry_run:
            try:
                upload_plugin(panel, url, filename)
            except ApiError as error:
                warn(f"Gagal memasang {label}: {error}")
                continue
        installed[plugin_stem(filename)] = filename
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Power and console
# ---------------------------------------------------------------------------

def console_commands(settings):
    commands = []
    for kind, template in (("ops", "op {}"), ("whitelist", "whitelist add {}")):
        names = settings.get(kind, [])
        for name in [names] if isinstance(names, str) else names:
            if PLAYER_NAME.match(name):
                commands.append(template.format(name))
            else:
                warn(f"Nama pemain '{name}' di console.{kind} tidak valid, dilewati.")
    extra = settings.get("commands", [])
    commands += [c.strip().lstrip("/") for c in ([extra] if isinstance(extra, str) else extra) if c.strip()]
    return commands


def wait_until_running(panel, timeout, restarting=False):
    """Poll until the server is running. Right after a restart it can still
    report running, so wait to see it go down first, but give up on that
    after a minute in case the restart finished between two polls."""
    log("Menunggu server menyala...")
    began = time.monotonic()
    went_down = not restarting
    started = False
    while time.monotonic() - began < timeout:
        time.sleep(3)
        state = panel.state()
        if state == "running" and (went_down or time.monotonic() - began > 60):
            log("Server sudah menyala.")
            return
        if state != "running":
            went_down = True
        if state == "starting":
            started = True
        elif state == "offline" and started:
            fail("Server mati lagi saat menyala (crash?). Cek tab Console di panel RaeHost.")
    fail("Server belum menyala setelah batas waktu. Cek panel RaeHost.")


def power(panel, signal, timeout):
    log(f"\nMengirim perintah {signal}...")
    panel.call("POST", "/power", json_body={"signal": signal})
    wait_until_running(panel, timeout, restarting=signal == "restart")


def ensure_running(panel, timeout):
    """Start the server if needed; True when it was (re)started."""
    state = panel.state()
    while state == "stopping":
        time.sleep(3)
        state = panel.state()
    if state == "offline":
        power(panel, "start", timeout)
        return True
    if state == "starting":
        wait_until_running(panel, timeout)
        return True
    return False


# ---------------------------------------------------------------------------

def load_config(path):
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        fail(f"File konfigurasi {path} tidak ditemukan.")
    except tomllib.TOMLDecodeError as error:
        fail(f"Format {path} salah: {error}")


def server_id_from(value):
    match = re.search(r"/server/([A-Za-z0-9-]+)", value)
    return (match.group(1) if match else value).strip()


def main():
    parser = argparse.ArgumentParser(description="Konfigurasi server Minecraft RaeHost secara otomatis.")
    parser.add_argument("--config", default=Path(__file__).with_name("server-config.toml"), type=Path)
    parser.add_argument("--dry-run", action="store_true", help="tampilkan perubahan tanpa menerapkannya")
    parser.add_argument("--no-restart", action="store_true", help="jangan restart server")
    args = parser.parse_args()

    config = load_config(args.config)
    panel_cfg = config.get("panel", {})
    panel_url = os.environ.get("PTERO_PANEL_URL") or panel_cfg.get("url") or "https://panel.raehost.com"
    server_id = server_id_from(os.environ.get("PTERO_SERVER_ID") or panel_cfg.get("server_id", ""))
    api_key = os.environ.get("PTERO_API_KEY", "").strip()
    if not api_key:
        fail("PTERO_API_KEY belum diisi. Lihat minecraft/README.md.")
    if api_key.startswith("ptla_"):
        fail("Itu Application API key (ptla_). Buat Client API key (ptlc_) di Account > API Credentials.")
    if not server_id:
        fail("ID server belum diisi (PTERO_SERVER_ID atau [panel].server_id).")

    panel = Panel(panel_url, api_key, server_id)
    try:
        server = panel.server()
    except ApiError as error:
        hint = {
            401: "API key salah atau sudah dihapus.",
            403: "API key tidak punya akses ke server ini, atau IP ini tidak diizinkan untuk key tersebut.",
            404: "ID server tidak ditemukan. Salin 8 karakter dari URL panel.raehost.com/server/<ID>.",
        }.get(error.status, "")
        fail(f"Tidak bisa membuka server ({error}). {hint}")
    log(f"Server: {server['name']} ({server['identifier']}) di {panel_url}")
    if server.get("is_suspended") or server.get("status") == "suspended":
        fail("Server sedang di-suspend. Hubungi RaeHost (cek tagihan).")
    if server.get("is_installing") or server.get("status") in ("installing", "restoring_backup"):
        fail("Server sedang install/restore. Coba lagi beberapa menit lagi.")
    if args.dry_run:
        log("Mode uji coba: tidak ada yang diubah di server.")

    power_cfg = config.get("power", {})
    timeout = int(power_cfg.get("wait_timeout_seconds", 300))
    startup_cfg = config.get("startup", {})
    was_running = panel.state() in ("running", "starting")

    try:
        changed = apply_properties(panel, config.get("properties", {}), args.dry_run)
        startup_changed = apply_startup(panel, startup_cfg, args.dry_run)
        changed = install_plugins(panel, config.get("plugins", {}), args.dry_run) or changed
        changed = changed or startup_changed
        commands = console_commands(config.get("console", {}))

        if args.dry_run:
            if commands:
                log("\n== Perintah konsol ==")
                log("\n".join(f"  {command}" for command in commands))
            log(f"\nUji coba selesai. {'Ada' if changed else 'Tidak ada'} perubahan yang akan diterapkan.")
            return

        reinstalled = bool(startup_changed and startup_cfg.get("reinstall_after_change"))
        if reinstalled:
            reinstall(panel, timeout)

        restart = changed and power_cfg.get("restart_after_changes", True) and not args.no_restart
        if restart and panel.state() == "running":
            power(panel, "restart", timeout)
            applied = True
        elif ((restart or reinstalled) and was_running) or commands:
            applied = ensure_running(panel, timeout)
        else:
            applied = False
        if changed and not applied:
            log("\nPerubahan baru dipakai setelah server dinyalakan (ulang).")

        if commands:
            log("\n== Perintah konsol ==")
            for command in commands:
                log(f"  > {command}")
                panel.call("POST", "/command", json_body={"command": command})
                time.sleep(1)
    except ApiError as error:
        fail(str(error))
    except ValueError as error:
        fail(f"Konfigurasi salah: {error}")

    log("\nSelesai." if not problems else f"\nSelesai dengan {len(problems)} peringatan (lihat di atas).")


if __name__ == "__main__":
    main()
