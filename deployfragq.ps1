# Interactive first-time setup on Windows (Docker Desktop): writes .env and starts the containers.
#   powershell -ExecutionPolicy Bypass -File .\deployfragq.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Host "Docker is not installed."; exit 1 }
docker compose version *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "The Docker Compose plugin (docker compose) is required."; exit 1 }

function Start-Stack {
    New-Item -ItemType Directory -Force certs, backups | Out-Null
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Ask([string]$Prompt, [string]$Default) {
    $v = Read-Host "$Prompt [$Default]"
    if ([string]::IsNullOrWhiteSpace($v)) { return $Default } else { return $v.Trim() }
}

function Ask-Secret([string]$Prompt) {
    do {
        $s = Read-Host $Prompt -AsSecureString
        $v = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
    } while ([string]::IsNullOrWhiteSpace($v))
    return $v.Trim()
}

function New-Random([int]$Length) {
    $chars = [char[]]'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    $bytes = New-Object byte[] $Length
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

if (Test-Path .env) {
    $yn = Read-Host ".env already exists. Overwrite it? [y/N]"
    if ($yn -notmatch '^[Yy]') { Write-Host "Keeping existing .env. Starting..."; Start-Stack; exit 0 }
}

Write-Host ""
Write-Host "Discord application - create one at https://discord.com/developers/applications"
Write-Host "  Bot tab:    copy the token and enable the Presence, Server Members and"
Write-Host "              Message Content privileged intents."
Write-Host "  OAuth2 tab: copy the client id and client secret."
$values = [ordered]@{}
$values.DISCORD_BOT_TOKEN = Ask-Secret "Bot token"
$values.DISCORD_CLIENT_ID = Ask "Client id" ""
$values.DISCORD_CLIENT_SECRET = Ask-Secret "Client secret"
$values.DISCORD_OWNER_ID = Ask "Your Discord user id (bot owner, optional)" ""

$lan = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Select-Object -First 1).IPAddress
if (-not $lan) { $lan = "localhost" }
Write-Host ""
Write-Host "How will people reach the web interface? Enter a domain name (fragq.example.com),"
Write-Host "or your server's public IP if you don't have a domain. Your LAN IP looks like: $lan"
$values.SITE_HOST = Ask "Domain or IP" $lan
$values.HTTP_PORT = Ask "HTTP port" "80"
$values.HTTPS_PORT = Ask "HTTPS port" "443"
Write-Host ""
Write-Host "TLS modes: auto (Let's Encrypt with self-signed fallback), internal (self-signed),"
Write-Host "           custom (your own .\certs\cert.pem + key.pem), off (plain HTTP)"
$values.TLS_MODE = Ask "TLS mode" "auto"
$values.ACME_EMAIL = ""
if ($values.TLS_MODE -eq "auto") { $values.ACME_EMAIL = Ask "E-mail for Let's Encrypt notices (optional)" "" }

$firstHost = ($values.SITE_HOST -split ',')[0].Trim()
if ($values.TLS_MODE -eq "off") {
    $url = "http://$firstHost"; if ($values.HTTP_PORT -ne "80") { $url += ":" + $values.HTTP_PORT }
} else {
    $url = "https://$firstHost"; if ($values.HTTPS_PORT -ne "443") { $url += ":" + $values.HTTPS_PORT }
}
$values.PUBLIC_URL = (Ask "Public address of the web interface" $url).TrimEnd('/')
$values.SESSION_SECRET = New-Random 48
$values.MYSQL_PASSWORD = New-Random 32
$values.MYSQL_ROOT_PASSWORD = New-Random 32

$lines = Get-Content .env.example | ForEach-Object {
    $line = $_
    foreach ($k in $values.Keys) {
        if ($line -match "^$k=") { $line = "$k=" + $values[$k]; break }
    }
    $line
}
# UTF-8 without BOM, LF line endings: docker compose reads it fine either way, Linux tools prefer this.
[IO.File]::WriteAllText((Join-Path $PSScriptRoot ".env"), ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding $false))

Start-Stack

Write-Host ""
Write-Host "  FragQ is starting at:  $($values.PUBLIC_URL)"
Write-Host ""
Write-Host "  One more step in the Discord developer portal (OAuth2 tab > Redirects), add:"
Write-Host "      $($values.PUBLIC_URL)/auth/callback"
Write-Host ""
Write-Host "  Then invite the bot from the web interface and enable it on a channel."
Write-Host "  If the certificate is self-signed your browser will warn once."
Write-Host "  Logs:  docker compose logs -f app"
