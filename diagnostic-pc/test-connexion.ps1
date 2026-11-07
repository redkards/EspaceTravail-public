# PARADOXX - Test complet de connexion PC -> Internet -> Tailscale -> VPS
# Lancement (PowerShell) :  powershell -ExecutionPolicy Bypass -File .\test-connexion.ps1
# Reparations automatiques : uniquement sures et reversibles (vidage DNS, sortie Tailscale, DNS Tailscale).
# Aucun mot de passe demande ni affiche. Rapport : Bureau\diagnostic-paradoxx.txt (+ presse-papiers).

$ErrorActionPreference = 'Continue'
$VPS_TS   = if ($env:PARADOXX_VPS_IP) { $env:PARADOXX_VPS_IP } else { 'paradoxx-vps' }  # IP Tailscale : variable d'environnement PARADOXX_VPS_IP (voir README)
$VPS_NOM  = 'paradoxx-vps'
$SITES    = @('claude.ai','api.anthropic.com','github.com','google.com')
$rapport  = Join-Path ([Environment]::GetFolderPath('Desktop')) 'diagnostic-paradoxx.txt'
$lignes   = New-Object System.Collections.Generic.List[string]
function Log($t){ Write-Host $t; $lignes.Add($t) }
function Ok($t){ Log "[OK]    $t" }
function Ko($t){ Log "[ECHEC] $t" }
function Fix($t){ Log "[REPARE] $t" }

function Test-Dns($nom){
  try { Resolve-DnsName $nom -ErrorAction Stop -QuickTimeout | Out-Null; $true } catch { $false }
}
function Test-DnsAll { ($SITES | Where-Object { -not (Test-Dns $_) }).Count -eq 0 }

Log "=== Diagnostic PARADOXX - $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') - $env:COMPUTERNAME ==="

# 1. Reseau local
Log "`n--- 1. Reseau local ---"
$gw = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1)
if ($gw) { Ok "Passerelle par defaut : $($gw.NextHop) (interface $($gw.InterfaceAlias))" } else { Ko "Aucune route par defaut : cable/Wi-Fi coupe" }
$ipNet = Test-Connection 1.1.1.1 -Count 2 -Quiet -ErrorAction SilentlyContinue
if ($ipNet) { Ok "Internet par IP (1.1.1.1) joignable" } else { Ko "Internet injoignable meme par IP : box / Wi-Fi / exit node" }
$dnsSrv = Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object { $_.ServerAddresses } | ForEach-Object { "$($_.InterfaceAlias)=$($_.ServerAddresses -join ',')" }
Log "Serveurs DNS : $($dnsSrv -join ' | ')"

# 2. DNS
Log "`n--- 2. Resolution DNS ---"
foreach ($s in $SITES) { if (Test-Dns $s) { Ok "DNS $s" } else { Ko "DNS $s (ERR_NAME_NOT_RESOLVED)" } }
try { Resolve-DnsName claude.ai -Server 1.1.1.1 -ErrorAction Stop | Out-Null; Ok "DNS direct via 1.1.1.1 fonctionne (le probleme vient du DNS configure sur le PC)" }
catch { Ko "DNS direct via 1.1.1.1 echoue aussi (sortie Internet bloquee)" }

# 3. Tailscale
Log "`n--- 3. Tailscale ---"
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts) { $p = "$env:ProgramFiles\Tailscale\tailscale.exe"; if (Test-Path $p) { Set-Alias tailscale $p; $ts = $true } }
if ($ts) {
  $st = (tailscale status 2>&1 | Out-String)
  Log ($st.Trim())
  $prefs = (tailscale debug prefs 2>$null | Out-String)
  $exit  = ($prefs -match '"ExitNodeID":\s*"[^"]+"')
  $acdns = ($prefs -match '"CorpDNS":\s*true')
  Log "Exit node actif : $exit | DNS Tailscale (MagicDNS) : $acdns"
} else { Ko "Tailscale introuvable sur ce PC" }

# 4. Reparations automatiques (seulement si DNS casse)
if (-not (Test-DnsAll)) {
  Log "`n--- 4. Reparations automatiques ---"
  ipconfig /flushdns | Out-Null; Fix "Cache DNS vide"
  if (Test-DnsAll) { Ok "DNS retabli apres vidage du cache" }
  elseif ($ts -and $exit) {
    tailscale set --exit-node= 2>&1 | Out-Null; Start-Sleep 3; ipconfig /flushdns | Out-Null
    Fix "Exit node Tailscale desactive (le VPS ne sert plus de sortie Internet)"
  }
  if (-not (Test-DnsAll) -and $ts -and $acdns) {
    tailscale set --accept-dns=false 2>&1 | Out-Null; Start-Sleep 3; ipconfig /flushdns | Out-Null
    Fix "DNS Tailscale desactive sur ce PC (retour : tailscale set --accept-dns=true)"
  }
  if (Test-DnsAll) { Ok "DNS retabli" } else { Ko "DNS toujours casse : redemarrer la box, ou verifier antivirus/VPN tiers" }
} else { Log "`n--- 4. Aucune reparation necessaire ---" }

# 5. VPS
Log "`n--- 5. VPS ---"
if ($ts) {
  $tp = (tailscale ping --c 3 --timeout 3s $VPS_TS 2>&1 | Out-String).Trim()
  Log $tp
  if ($tp -match 'pong') { Ok "VPS joignable par Tailscale" } else { Ko "VPS injoignable par Tailscale (VPS eteint, tailscaled arrete, ou deconnecte)" }
}
$port = Test-NetConnection $VPS_TS -Port 22 -WarningAction SilentlyContinue
if ($port.TcpTestSucceeded) { Ok "Port SSH 22 ouvert via Tailscale" } else { Ko "Port SSH 22 ferme via Tailscale" }

$ssh = Get-Command ssh -ErrorAction SilentlyContinue
if ($ssh -and $port.TcpTestSucceeded) {
  $cmd = 'echo VPS=$(hostname); uptime -p; systemctl is-active tailscaled ssh fail2ban; tmux ls 2>&1 | head -3; pgrep -fa claude | head -2 || echo claude-absent; df -h / | tail -1; free -h | sed -n 2p; docker ps --format "{{.Names}} {{.Status}}" 2>/dev/null | head -10'
  $out = (ssh -o BatchMode=yes -o ConnectTimeout=8 paradoxx $cmd 2>&1 | Out-String).Trim()
  Log $out
  if ($out -match 'VPS=') { Ok "SSH par cle vers paradoxx OK" } else { Ko "SSH paradoxx refuse (cle, utilisateur ou sshd)" }
}

# 6. Synthese
Log "`n--- 6. Synthese ---"
if (Test-DnsAll) { Ok "Claude desktop / Claude Code / GitHub devraient se reconnecter : cliquer Actualiser" } else { Ko "Sans DNS, Claude desktop et Claude Code ne peuvent pas fonctionner" }
$lignes | Set-Content -Encoding UTF8 $rapport
try { $lignes -join "`r`n" | Set-Clipboard; Log "Rapport copie dans le presse-papiers et enregistre : $rapport" } catch { Log "Rapport enregistre : $rapport" }
