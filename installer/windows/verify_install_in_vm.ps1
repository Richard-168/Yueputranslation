# Run inside a fresh, disposable Windows x64 VM. Keep the Inno data slices
# beside the setup EXE and copy the evidence folder out before reverting the VM.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Evidence,
    [switch]$DisposableVM
)
$ErrorActionPreference = 'Stop'
if (-not $DisposableVM -or -not [Environment]::Is64BitProcess) {
    throw 'Run from 64-bit PowerShell inside a disposable VM and specify -DisposableVM.'
}
$setup = (Get-Item -LiteralPath $Installer).FullName
if ([IO.Path]::GetExtension($setup) -ne '.exe') { throw 'Expected the compiled Inno installer EXE.' }
$definition = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'YuePuTranslate.iss') -Raw -Encoding UTF8
$id = [regex]::Match($definition, '(?m)^AppId=\{(\{[0-9A-Fa-f-]+\})\s*$')
if (-not $id.Success) { throw 'Cannot determine the application ID from the installer definition.' }
$groupName = [regex]::Match($definition, '(?m)^DefaultGroupName=([^\r\n]+)').Groups[1].Value
if (-not $groupName) { throw 'Cannot determine the start-menu group from the installer definition.' }
$group = Join-Path ([Environment]::GetFolderPath('Programs')) $groupName
if (Test-Path -LiteralPath $group) { throw 'The start-menu group already exists. Use a clean VM.' }
$uninstallKey = $id.Groups[1].Value + '_is1'
$keys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$uninstallKey"
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$uninstallKey"
    "HKCU:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$uninstallKey"
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\$uninstallKey"
)
if ($keys | Where-Object { Test-Path -LiteralPath $_ }) {
    throw 'This VM already contains a registered installation. Use a clean snapshot.'
}
$runName = 'YuePuCheck-' + [guid]::NewGuid().ToString('N')
$run = [IO.Directory]::CreateDirectory((Join-Path $Evidence $runName)).FullName
$target = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('Programs\' + $runName)
$result = [ordered]@{
    installer_sha256 = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash
    installed = $false
    registered = $false
    shortcut_verified = $false
    runtime_verified = $false
    uninstalled = $false
    errors = @()
}

function Run-Inno([string]$File, [string]$Options) {
    $process = Start-Process -FilePath $File -ArgumentList $Options -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "Inno returned exit code $($process.ExitCode)." }
}
try {
    $log = Join-Path $run 'install.log'
    Run-Inno $setup "/VERYSILENT /SUPPRESSMSGBOXES /SP- /NORESTART /DIR=`"$target`" /LOG=`"$log`""
    $result.installed = $true
    $registered = @($keys | Where-Object { Test-Path -LiteralPath $_ })
    if ($registered.Count -ne 1 -or $registered[0] -notlike 'HKCU:*') {
        throw 'Expected one current-user uninstall entry.'
    }
    $location = (Get-ItemProperty -LiteralPath $registered[0]).InstallLocation
    if (-not $location -or $location.TrimEnd('\') -ne $target) {
        throw 'The uninstall entry references another installation.'
    }
    $result.registered = $true
    $shell = New-Object -ComObject WScript.Shell
    $shortcuts = @(Get-ChildItem -LiteralPath $group -Filter '*.lnk' | ForEach-Object {
        $shell.CreateShortcut($_.FullName)
    } | Where-Object {
        $_.TargetPath -eq (Join-Path $target 'python\pythonw.exe') -and
        $_.Arguments -eq ('-I -B "' + (Join-Path $target 'launch.py') + '"')
    })
    if ($shortcuts.Count -ne 1) { throw 'The application shortcut is missing or points elsewhere.' }
    $result.shortcut_verified = $true
    & (Join-Path $target 'python\python.exe') -I -B -X utf8 (Join-Path $PSScriptRoot 'verify_runtime.py') --installation $target --evidence (Join-Path $run 'runtime')
    if ($LASTEXITCODE -ne 0) { throw "Installed runtime check returned $LASTEXITCODE." }
    $result.runtime_verified = $true
} catch {
    $result.errors += $_.Exception.Message
} finally {
    if ($result.installed) {
        try {
            $uninstallers = @(Get-ChildItem -LiteralPath $target -Filter 'unins*.exe' -File)
            if ($uninstallers.Count -ne 1) { throw 'Expected one uninstaller in the test installation.' }
            $log = Join-Path $run 'uninstall.log'
            Run-Inno $uninstallers[0].FullName "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$log`""
            if (($keys | Where-Object { Test-Path -LiteralPath $_ }) -or (Test-Path -LiteralPath $group)) {
                throw 'Uninstall left the start-menu group or uninstall registration behind.'
            }
            if ((Test-Path -LiteralPath $target) -and (Get-ChildItem -LiteralPath $target -Recurse -Force -File)) {
                throw 'Uninstall left files in the installation directory.'
            }
            $result.uninstalled = $true
        } catch {
            $result.errors += $_.Exception.Message
        }
    }
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'installation.json') -Encoding UTF8
    Write-Output "Evidence: $run"
}
if ($result.errors.Count) { throw ($result.errors -join [Environment]::NewLine) }
