param([switch]$Check)
$ErrorActionPreference = 'Stop'
$taskCandidates = New-Object 'System.Collections.Generic.List[string]'
# Prefer a normal user Python install. The Codex runtime is an optional fallback.
$taskNormalPython = Get-Command python.exe -ErrorAction SilentlyContinue
if ($taskNormalPython -and $taskNormalPython.Source -notmatch 'WindowsApps') { $taskCandidates.Add($taskNormalPython.Source) }
$taskPy = Get-Command py.exe -ErrorAction SilentlyContinue
if ($taskPy) {
    try {
        $taskDetected = & $taskPy.Source -3 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $taskDetected) { $taskCandidates.Add(($taskDetected | Select-Object -Last 1).Trim()) }
    } catch { }
}
$taskCandidates.Add((Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'))
$taskScript = Join-Path $PSScriptRoot 'scripts\app.py'
foreach ($taskCandidate in ($taskCandidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $taskCandidate -PathType Leaf)) { continue }
    try { & $taskCandidate -c 'import sys, tkinter; assert sys.version_info >= (3, 10); r=tkinter.Tk(); r.withdraw(); r.destroy()' 2>$null } catch { continue }
    if ($LASTEXITCODE -ne 0) { continue }
    if ($Check) { Write-Output 'Python 3.10+ and Tk check passed'; exit 0 }
    $taskPythonWindowless = Join-Path (Split-Path -Parent $taskCandidate) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $taskPythonWindowless)) { $taskPythonWindowless = $taskCandidate }
    Start-Process -FilePath $taskPythonWindowless -ArgumentList ('"' + $taskScript + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    exit 0
}
if ($Check) { Write-Error 'Python 3.10+ with working Tk is required.'; exit 1 }
Add-Type -AssemblyName System.Windows.Forms
[void][System.Windows.Forms.MessageBox]::Show('Install Python 3.10 or later with Tcl/Tk and Codex desktop, then try again. See README.md.', 'Smart Model Router')
exit 1
