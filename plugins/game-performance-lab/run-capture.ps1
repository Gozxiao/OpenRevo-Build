# OpenRevo Game Performance Lab - optional manual Intel PresentMon capture.
# Explicit opt-in only; never monitors background processes automatically.
[CmdletBinding()]
param(
    [string]$GameExe = "",
    [int]$Seconds = 60
)
$ErrorActionPreference = 'Stop'
try {
    $presentMon = Join-Path $PSScriptRoot 'PresentMon-2.6.0-x64.exe'
    if (-not (Test-Path -LiteralPath $presentMon -PathType Leaf)) {
        throw "找不到 Intel PresentMon 控制台程序，确认使用 GitHub Actions 构建的完整插件 ZIP。"
    }
    if ([string]::IsNullOrWhiteSpace($GameExe)) {
        $GameExe = Read-Host "请输入游戏 EXE 进程名（例如 game.exe，不要输入完整路径）"
    }
    $GameExe = $GameExe.Trim()
    if ($GameExe -notmatch '^[\p{L}\p{N}_. -]+\.exe$' -or $GameExe.Contains('..')) {
        throw "只允许输入游戏进程文件名，例如 game.exe，不允许路径或命令。"
    }
    if ($Seconds -eq 60) {
        $choice = Read-Host "录制时长（秒，直接回车默认 60，最大 900）"
        if (-not [string]::IsNullOrWhiteSpace($choice)) {
            $parsed = 0
            if (-not [int]::TryParse($choice,[ref]$parsed)) { throw "录制时长必须为整数。" }
            $Seconds = $parsed
        }
    }
    if ($Seconds -lt 5 -or $Seconds -gt 900) { throw "录制时长必须在 5～900 秒之间。" }

    $documents = [Environment]::GetFolderPath('MyDocuments')
    if (-not $documents) { $documents = $HOME }
    $folder = Join-Path $documents 'OpenRevo-Performance\captures'
    New-Item -ItemType Directory -Path $folder -Force | Out-Null

    $name = $GameExe -replace '[^\p{L}\p{N}_. -]','_'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $out = Join-Path $folder ("PresentMon-{0}-{1}.csv" -f $name,$stamp)

    Write-Host ("准备录制 {0}，持续 {1} 秒" -f $GameExe, $Seconds) -ForegroundColor Cyan
    Write-Host "请切回游戏。录制结束后导入生成的 CSV。" -ForegroundColor Gray
    & $presentMon --process_name $GameExe --output_file $out --timed $Seconds --terminate_after_timed --no_console_stats
    $code=$LASTEXITCODE
    if ($code -ne 0) { throw "PresentMon 退出码 $code。可能需要管理员权限、游戏尚未运行或系统不支持采集。" }
    if (-not (Test-Path -LiteralPath $out -PathType Leaf) -or (Get-Item -LiteralPath $out).Length -lt 40) {
        throw "录制完成，但没有收到足够的帧数据。检查进程名称、游戏是否在运行及是否被反作弊保护。"
    }
    Write-Host "CSV 录制成功：" -ForegroundColor Green
    Write-Host $out -ForegroundColor Yellow
    Write-Host "请回到 OpenRevo 的「游戏性能实验室」导入该文件。"
} catch {
    Write-Host ("录制失败：" + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
