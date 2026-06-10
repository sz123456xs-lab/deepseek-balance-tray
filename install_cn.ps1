# DeepSeek DeskBand - 安装脚本（需要管理员权限）
# 以管理员身份运行 PowerShell，然后执行此脚本

Write-Host "正在安装 DeepSeek DeskBand..." -ForegroundColor Cyan

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$dllPath = Join-Path $scriptPath "bin\Release\net48\DeepSeekDeskBand.dll"

if (-not (Test-Path $dllPath)) {
    Write-Host "错误: 找不到 $dllPath" -ForegroundColor Red
    Write-Host "请先运行: dotnet build -c Release" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "注册 COM 组件..." -ForegroundColor Yellow
$regAsm = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"
& $regAsm $dllPath /codebase

if ($LASTEXITCODE -eq 0) {
    Write-Host "COM 注册成功！" -ForegroundColor Green
} else {
    Write-Host "COM 注册失败，请以管理员身份运行此脚本" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "重启任务栏..." -ForegroundColor Yellow
taskkill /f /im explorer.exe
Start-Sleep -Seconds 2
Start-Process explorer.exe

Write-Host ""
Write-Host "安装完成！" -ForegroundColor Green
Write-Host "请右键任务栏 → 工具栏 → 勾选 DeepSeek DeskBand" -ForegroundColor Cyan
Write-Host "然后左键点击组件 → 设置 API Key" -ForegroundColor Cyan
pause
