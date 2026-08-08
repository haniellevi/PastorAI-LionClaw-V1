$ErrorActionPreference = 'Stop'

$vps = 'root@76.13.234.127'
$sshKey = Join-Path $env:USERPROFILE '.ssh\pastorai_vps'
$oneDriveRoot = Join-Path $env:USERPROFILE 'OneDrive\Documentos\Backups\PastorAI'
$masterKey = Join-Path $oneDriveRoot 'pastorai-backup-master.key.dpapi'
$openssl = 'C:\Program Files\Git\usr\bin\openssl.exe'
$logFile = Join-Path $oneDriveRoot 'backup-sync.log'

New-Item -ItemType Directory -Path $oneDriveRoot -Force | Out-Null

if (-not (Test-Path -LiteralPath $sshKey)) {
    throw "Chave SSH ausente: $sshKey"
}
if (-not (Test-Path -LiteralPath $openssl)) {
    throw "OpenSSL ausente: $openssl"
}

if (-not (Test-Path -LiteralPath $masterKey)) {
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $password = [Convert]::ToBase64String($bytes)
    ConvertTo-SecureString $password -AsPlainText -Force |
        ConvertFrom-SecureString |
        Set-Content -LiteralPath $masterKey -Encoding ascii
    $password = $null
}

$latest = (& ssh -i $sshKey -o BatchMode=yes -o ConnectTimeout=15 $vps `
    "find /root/pastorai-backups -maxdepth 1 -type f -name 'pastorai-backup-*.tar.gz' -printf '%f\n' | sort -r | head -n 1").Trim()

if ($latest -notmatch '^pastorai-backup-(\d{8}T\d{6}Z)\.tar\.gz$') {
    throw "Nome de backup inesperado: $latest"
}

$stamp = $Matches[1]
$destination = Join-Path $oneDriveRoot $stamp
$encrypted = Join-Path $destination "$latest.enc"
$checksumDestination = Join-Path $destination "$latest.plaintext.sha256"

if ((Test-Path -LiteralPath $encrypted) -and
    (Test-Path -LiteralPath $checksumDestination)) {
    Add-Content -LiteralPath $logFile -Encoding utf8 `
        -Value "$(Get-Date -Format o) BACKUP_ALREADY_SYNCED stamp=$stamp"
    exit 0
}

$tempRoot = [IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "Temp\PastorAI-Backup-Sync-$stamp")
)
$allowedTemp = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Temp\'))
if (-not $tempRoot.StartsWith($allowedTemp, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Diretório temporário fora do local permitido'
}

New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
New-Item -ItemType Directory -Path $destination -Force | Out-Null

$plain = Join-Path $tempRoot $latest
$checksum = Join-Path $tempRoot "$latest.sha256"
$restoreTest = Join-Path $tempRoot 'restore-verification.tar.gz'
$encryptedPart = "$encrypted.part"

try {
    & scp -i $sshKey -o BatchMode=yes "${vps}:/root/pastorai-backups/$latest" $plain
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao copiar o pacote da VPS' }
    & scp -i $sshKey -o BatchMode=yes "${vps}:/root/pastorai-backups/$latest.sha256" $checksum
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao copiar o checksum da VPS' }

    $expected = (Get-Content -LiteralPath $checksum -Raw).Split(' ')[0].Trim().ToLowerInvariant()
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $plain).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw 'Checksum do pacote copiado não confere' }

    $secure = Get-Content -LiteralPath $masterKey | ConvertTo-SecureString
    $env:PASTORAI_BACKUP_PASSWORD = [Net.NetworkCredential]::new('', $secure).Password

    & $openssl enc -aes-256-cbc -salt -pbkdf2 -iter 600000 `
        -in $plain -out $encryptedPart -pass env:PASTORAI_BACKUP_PASSWORD
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criptografar o backup' }

    & $openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 `
        -in $encryptedPart -out $restoreTest -pass env:PASTORAI_BACKUP_PASSWORD
    if ($LASTEXITCODE -ne 0) { throw 'Falha no teste de descriptografia' }

    $restoredHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $restoreTest).Hash.ToLowerInvariant()
    if ($restoredHash -ne $expected) { throw 'Checksum após descriptografia não confere' }

    [IO.File]::Move($encryptedPart, $encrypted, $true)
    Copy-Item -LiteralPath $checksum -Destination $checksumDestination -Force
    Add-Content -LiteralPath $logFile -Encoding utf8 `
        -Value "$(Get-Date -Format o) BACKUP_SYNC_OK stamp=$stamp sha256=$actual"
}
finally {
    $env:PASTORAI_BACKUP_PASSWORD = $null
    foreach ($path in @($plain, $checksum, $restoreTest, $encryptedPart)) {
        if ([IO.File]::Exists($path)) { [IO.File]::Delete($path) }
    }
    if ([IO.Directory]::Exists($tempRoot)) {
        [IO.Directory]::Delete($tempRoot, $false)
    }
}
