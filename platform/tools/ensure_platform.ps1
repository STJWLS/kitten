# KittenPuppy4Ever 新引擎保活（计划任务每 5 分钟跑一次，幂等）
$ErrorActionPreference = 'SilentlyContinue'
$dir = 'D:\KittenPuppy4Ever\platform\tools'
$log = 'D:\KittenPuppy4Ever\platform\data\_migration\ensure_platform.log'

function WriteL([string]$m) {
  Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $m) -Encoding UTF8
}

# 守护进程在不在（不能只看 8772：守护死了但引擎还活着时，隧道没人管）
$guard = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like '*kp_guard.py*' }

if (-not $guard) {
  WriteL 'guard not running -> start guard'
  Start-Process -FilePath 'wscript.exe' -ArgumentList ('"' + (Join-Path $dir 'run_guard.vbs') + '"') -WindowStyle Hidden
}
