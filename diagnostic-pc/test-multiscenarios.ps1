# PARADOXX - Test multiscénario de stabilité PC -> VPS (lecture seule, aucune modification)
# Lancement : powershell -ExecutionPolicy Bypass -File .\test-multiscenarios.ps1  [-Minutes 3]
# Couvre S1, S2, S4, S5, S9 et l'exposition publique (pare-feu Hostinger + ufw). Rapport : Bureau\multiscenarios-paradoxx.txt
param([int]$Minutes = 3)
$VPS_TS  = if ($env:PARADOXX_VPS_IP) { $env:PARADOXX_VPS_IP } else { 'paradoxx-vps' }
$VPS_PUB = if ($env:PARADOXX_VPS_PUBLIC) { $env:PARADOXX_VPS_PUBLIC } else { 'vps.example.invalid' }
$L = New-Object System.Collections.Generic.List[string]
function Log($t){ Write-Host $t; $L.Add($t) }
function R($id,$ok,$t){ Log ("[{0}] {1,-4} {2}" -f ($(if($ok){'OK   '}else{'ECHEC'}), $id, $t)) }
$ts = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if (-not $ts) { $ts = "$env:ProgramFiles\Tailscale\tailscale.exe" }
Log "=== Multiscénario PARADOXX - $(Get-Date -Format 'dd/MM/yyyy HH:mm') - durée stabilité $Minutes min ==="

# S1 - DNS public
$dns = @('claude.ai','github.com','api.notion.com') | ForEach-Object { try { Resolve-DnsName $_ -QuickTimeout -ErrorAction Stop | Out-Null; $true } catch { $false } }
R 'S1' (-not ($dns -contains $false)) "DNS public (claude.ai, github.com, api.notion.com)"

# S2 - l'alias SSH ne dépend pas de MagicDNS
$cfg = (ssh -G paradoxx 2>$null) -join "`n"
$hn = if ($cfg -match '(?m)^hostname (\S+)') { $Matches[1] } else { '?' }
R 'S2' ($hn -eq $VPS_TS) "Alias ssh paradoxx -> $hn (attendu : IP Tailscale)"
$ka = if ($cfg -match '(?m)^serveraliveinterval (\d+)') { [int]$Matches[1] } else { 0 }
R 'S5a' ($ka -gt 0 -and $ka -le 60) "ServerAliveInterval = $ka (attendu 30)"

# S4 - chemin direct ou relais DERP + qualité NAT
$p = (& $ts ping --c 5 $VPS_TS 2>&1 | Out-String)
$direct = $p -match 'via \d+\.\d+\.\d+\.\d+:\d+'
R 'S4' $direct ("Chemin Tailscale : " + $(if($direct){'direct'}else{'relais DERP (plus lent)'}))
$nc = (& $ts netcheck 2>&1 | Out-String)
if ($nc -match 'UDP: (\w+)') { R 'S4b' ($Matches[1] -eq 'true') "UDP sortant du PC : $($Matches[1])" }
if ($nc -match 'Nearest DERP: (.+)') { Log "       DERP le plus proche : $($Matches[1].Trim())" }

# S9 - Tailscale SSH (secours sans clé) annoncé par le VPS
$st = (& $ts status --json 2>$null | ConvertFrom-Json)
$peer = $st.Peer.PSObject.Properties.Value | Where-Object { $_.TailscaleIPs -contains $VPS_TS }
R 'S9' ($peer -and $peer.sshHostKeys) "Tailscale SSH disponible sur le VPS (secours si clé perdue)"
if ($peer) { R 'S7' ($null -eq $peer.KeyExpiry -or $peer.KeyExpiry -like '0001*') ("Expiration clé VPS : " + $(if($peer.KeyExpiry){$peer.KeyExpiry}else{'désactivée'})) }

# Exposition publique : SSH ne doit PAS répondre sur l'IP publique
$pub = Test-NetConnection $VPS_PUB -Port 22 -WarningAction SilentlyContinue
R 'EXP' (-not $pub.TcpTestSucceeded) "Port 22 public fermé (pare-feu Hostinger + ufw)"
$web = Test-NetConnection $VPS_PUB -Port 443 -WarningAction SilentlyContinue
Log ("       443 public : " + $(if($web.TcpTestSucceeded){'ouvert (cockpit/site)'}else{'fermé'}))

# S5 - stabilité : une connexion SSH toutes les 10 s pendant $Minutes minutes
$n = [math]::Max(1, $Minutes * 6); $okc = 0; $lat = @()
for ($i = 1; $i -le $n; $i++) {
  $t = Measure-Command { $o = ssh -o BatchMode=yes -o ConnectTimeout=8 paradoxx 'echo pong' 2>$null }
  if ($o -eq 'pong') { $okc++; $lat += [int]$t.TotalMilliseconds }
  Write-Progress -Activity 'Stabilité SSH' -Status "$i / $n" -PercentComplete ($i * 100 / $n)
  Start-Sleep 10
}
$moy = if ($lat) { [int](($lat | Measure-Object -Average).Average) } else { 0 }
$max = if ($lat) { ($lat | Measure-Object -Maximum).Maximum } else { 0 }
R 'S5' ($okc -eq $n) "Stabilité : $okc/$n connexions réussies, ouverture SSH moy. $moy ms, max $max ms"

Log "`nÀ faire à la main (non automatisable sans couper le réseau) : S3 Termius en 4G Wi-Fi coupé ; S5 couper le Wi-Fi 20 s pendant une session Mosh."
$out = Join-Path ([Environment]::GetFolderPath('Desktop')) 'multiscenarios-paradoxx.txt'
$L | Set-Content -Encoding UTF8 $out; Log "Rapport : $out"
