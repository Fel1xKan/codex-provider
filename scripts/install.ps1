param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("cpx", "clpx", "cupx", "apx", "opx")]
    [string]$Command,
    [string]$Repo = "Fel1xKan/codex-provider",
    [string]$Version = "latest",
    [string]$InstallDir = "$HOME\.local\bin"
)

$ErrorActionPreference = "Stop"

function Get-Version {
    if ($Version -eq "latest") {
        $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "install" }
        return $release.tag_name.TrimStart("v")
    }
    return $Version.TrimStart("v")
}

$ver = Get-Version
$asset = "$Command-$ver-windows-x86_64.exe"
$base = "https://github.com/$Repo/releases/download/v$ver"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$target = Join-Path $InstallDir "$Command.exe"

Write-Host "downloading $asset"
Invoke-WebRequest -Uri "$base/$asset" -OutFile $target
$expected = (Invoke-WebRequest -Uri "$base/$asset.sha256").Content.Split(" ")[0]
$actual = (Get-FileHash -Algorithm SHA256 -Path $target).Hash.ToLower()
if ($actual -ne $expected) {
    Remove-Item -Force $target
    throw "checksum mismatch"
}

Write-Host "installed $Command to $target"
Write-Host "run: $Command --help"
if ($env:Path -notlike "*$InstallDir*") {
    Write-Host "note: add $InstallDir to your PATH to use $Command"
}
