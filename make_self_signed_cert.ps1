param(
    [string]$Subject = "CN=SeavoExplorer Development",
    [string]$OutputDir = ".signing",
    [string]$PfxPassword = "",
    [switch]$TrustLocal
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not [System.IO.Path]::IsPathRooted($OutputDir)) {
    $OutputDir = Join-Path $root $OutputDir
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$cerPath = Join-Path $OutputDir "SeavoExplorer-dev.cer"
$pfxPath = Join-Path $OutputDir "SeavoExplorer-dev.pfx"
if (Test-Path -LiteralPath $cerPath) {
    throw "证书文件已存在，拒绝覆盖: $cerPath"
}
if ($PfxPassword -and (Test-Path -LiteralPath $pfxPath)) {
    throw "PFX 文件已存在，拒绝覆盖: $pfxPath"
}

$cert = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -KeyUsage DigitalSignature `
    -FriendlyName "SeavoExplorer Development" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -NotAfter (Get-Date).AddYears(3)

Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null

if ($PfxPassword) {
    $secure = ConvertTo-SecureString -String $PfxPassword -AsPlainText -Force
    Export-PfxCertificate -Cert $cert -FilePath $pfxPath -Password $secure | Out-Null
}

if ($TrustLocal) {
    Import-Certificate -FilePath $cerPath -CertStoreLocation "Cert:\CurrentUser\TrustedPublisher" | Out-Null
    Import-Certificate -FilePath $cerPath -CertStoreLocation "Cert:\CurrentUser\Root" | Out-Null
}

Write-Host "Subject: $($cert.Subject)"
Write-Host "Thumbprint: $($cert.Thumbprint)"
Write-Host "Certificate: $cerPath"
if ($PfxPassword) {
    Write-Host "PFX: $pfxPath"
}
Write-Host ""
Write-Host "Set these environment variables before build_onefile.py:"
Write-Host "  `$env:SEAVO_SIGN_MODE='store'"
Write-Host "  `$env:SEAVO_SIGN_CERT_SHA1='$($cert.Thumbprint)'"
Write-Host "  `$env:SEAVO_SIGN_TIMESTAMP_URL='http://timestamp.digicert.com'"
Write-Host "  `$env:SEAVO_SIGN_ALLOW_UNTRUSTED='1'"
