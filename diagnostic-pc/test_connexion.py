"""PARADOXX - Test complet de connexion PC -> Internet -> Tailscale -> VPS (Python 3.14, stdlib seule).
Lancement :  py test_connexion.py   (ou via la commande en 1 ligne du README)
Réparations automatiques sûres et réversibles, seulement si le DNS est cassé.
Aucun mot de passe demandé ni affiché. Rapport : Bureau/diagnostic-paradoxx.txt
"""
import datetime, os, pathlib, platform, shutil, socket, subprocess

VPS_TS, PORT = os.environ.get("PARADOXX_VPS_IP", "paradoxx-vps"), 22  # IP Tailscale : variable PARADOXX_VPS_IP
SITES = ["claude.ai", "api.anthropic.com", "github.com", "google.com"]
WIN = platform.system() == "Windows"
lignes: list[str] = []


def log(t=""):
    print(t)
    lignes.append(t)


ok = lambda t: log(f"[OK]     {t}")
ko = lambda t: log(f"[ECHEC]  {t}")
fix = lambda t: log(f"[REPARE] {t}")


def run(cmd: list[str], timeout=20) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"(erreur : {e})"


def dns(nom: str) -> bool:
    try:
        socket.getaddrinfo(nom, 443)
        return True
    except OSError:
        return False


def dns_ok() -> bool:
    return all(dns(s) for s in SITES)


def tcp(hote: str, port: int, t=4) -> bool:
    try:
        with socket.create_connection((hote, port), timeout=t):
            return True
    except OSError:
        return False


def flush():
    run(["ipconfig", "/flushdns"] if WIN else ["resolvectl", "flush-caches"])


def tailscale_bin():
    b = shutil.which("tailscale")
    if not b and WIN:
        p = pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        b = str(p) if p.exists() else None
    return b


log(f"=== Diagnostic PARADOXX - {datetime.datetime.now():%d/%m/%Y %H:%M:%S} - {platform.node()} ===")

log("\n--- 1. Internet ---")
ok("Internet par IP (1.1.1.1:443)") if tcp("1.1.1.1", 443) else ko("Internet injoignable même par IP : box / Wi-Fi / exit node")

log("\n--- 2. DNS ---")
for s in SITES:
    ok(f"DNS {s}") if dns(s) else ko(f"DNS {s} (ERR_NAME_NOT_RESOLVED)")
if WIN:
    out = run(["nslookup", "claude.ai", "1.1.1.1"])
    ok("DNS direct via 1.1.1.1 OK : le problème vient du DNS réglé sur le PC") if "Addresses" in out or "Address:" in out.split("Name:")[-1] else ko("DNS direct via 1.1.1.1 KO aussi")

log("\n--- 3. Tailscale ---")
ts = tailscale_bin()
exit_node = magic = False
if ts:
    log(run([ts, "status"]))
    prefs = run([ts, "debug", "prefs"])
    exit_node = '"ExitNodeID": "' in prefs and '"ExitNodeID": ""' not in prefs
    magic = '"CorpDNS": true' in prefs
    log(f"Exit node actif : {exit_node} | DNS Tailscale (MagicDNS) : {magic}")
else:
    ko("Tailscale introuvable sur ce PC")

if not dns_ok():
    log("\n--- 4. Réparations automatiques ---")
    flush(); fix("Cache DNS vidé")
    if not dns_ok() and ts and exit_node:
        run([ts, "set", "--exit-node="]); flush(); fix("Exit node Tailscale désactivé")
    if not dns_ok() and ts and magic:
        run([ts, "set", "--accept-dns=false"]); flush()
        fix("DNS Tailscale désactivé (retour : tailscale set --accept-dns=true)")
    ok("DNS rétabli") if dns_ok() else ko("DNS toujours cassé : redémarrer la box, vérifier antivirus / VPN tiers")
else:
    log("\n--- 4. Aucune réparation nécessaire ---")

log("\n--- 5. VPS ---")
if ts:
    p = run([ts, "ping", "--c", "3", "--timeout", "3s", VPS_TS], timeout=30)
    log(p)
    ok("VPS joignable par Tailscale") if "pong" in p else ko("VPS injoignable par Tailscale (éteint, tailscaled arrêté ou déconnecté)")
port = tcp(VPS_TS, PORT)
ok("Port SSH 22 ouvert via Tailscale") if port else ko("Port SSH 22 fermé via Tailscale")
if port and shutil.which("ssh"):
    distant = ('echo VPS=$(hostname); uptime -p; systemctl is-active tailscaled ssh fail2ban; '
               'tmux ls 2>&1 | head -3; pgrep -fa claude | head -2 || echo claude-absent; '
               'df -h / | tail -1; free -h | sed -n 2p; '
               'docker ps --format "{{.Names}} {{.Status}}" 2>/dev/null | head -10')
    out = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "paradoxx", distant], timeout=40)
    log(out)
    ok("SSH par clé vers paradoxx OK") if "VPS=" in out else ko("SSH paradoxx refusé (clé, utilisateur ou sshd)")

log("\n--- 6. Synthèse ---")
ok("Claude desktop / Claude Code / GitHub devraient revenir : cliquer Actualiser") if dns_ok() else ko("Sans DNS, Claude desktop et Claude Code ne peuvent pas fonctionner")

bureau = pathlib.Path.home() / ("Desktop" if (pathlib.Path.home() / "Desktop").exists() else "")
rapport = bureau / "diagnostic-paradoxx.txt"
rapport.write_text("\n".join(lignes), encoding="utf-8")
print(f"\nRapport enregistré : {rapport}")
