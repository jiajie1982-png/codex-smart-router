param([Parameter(Mandatory=$true)][string]$ProjectRoot)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$taskProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop)
$taskIds = New-Object 'System.Collections.Generic.HashSet[uint32]'
foreach ($taskProcess in $taskProcesses) {
    if ($taskProcess.Name -match '(?i)^(codex|chatgpt)(\.exe)?$' -or $taskProcess.ExecutablePath -match '(?i)(\\OpenAI\\Codex\\|OpenAI\.Codex|\\ChatGPT\\)') {
        [void]$taskIds.Add([uint32]$taskProcess.ProcessId)
    }
}
do {
    $taskAdded = $false
    foreach ($taskProcess in $taskProcesses) {
        if ($taskIds.Contains([uint32]$taskProcess.ParentProcessId) -and $taskIds.Add([uint32]$taskProcess.ProcessId)) { $taskAdded = $true }
    }
} while ($taskAdded)
$taskNodeRepl = @($taskProcesses | Where-Object { $_.Name -match '(?i)^node(\.exe)?$' -and $_.CommandLine -match 'node_repl' })
$taskMemory = ($taskProcesses | Where-Object { $taskIds.Contains([uint32]$_.ProcessId) } | Measure-Object PrivatePageCount -Sum).Sum
$taskBusy = @($taskProcesses | Where-Object {
    $_.Name -match '(?i)^(node|npm|npx)(\.exe)?$' -and $_.CommandLine -and
    $_.CommandLine.IndexOf($ProjectRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    $_.CommandLine -notmatch 'node_repl'
})
@{nodeReplCount=$taskNodeRepl.Count; privateBytes=[long]$taskMemory; projectBusy=($taskBusy.Count -gt 0)} | ConvertTo-Json -Compress
