# 一键配置并测试:让你输入密钥(输入不显示),写入 .env,立刻跑一次真实调用。
# 用法(任选其一):
#   1. 在资源管理器里双击 setup_key.bat
#   2. 项目终端: powershell -NoProfile -ExecutionPolicy Bypass -File .\vlm\setup_key.ps1
# 密钥只写进 .env(已在 .gitignore),不会打印,也不会出现在命令行参数里。
# 注意:本文件必须以 UTF-8 BOM 保存,否则 Windows PowerShell 5.1 会按 GBK 读中文而报语法错。

param(
    [string]$Provider = "openai",
    [string]$BaseUrl  = "https://api.deepseek.com",
    [string]$Model    = "deepseek-flash",
    [string]$EnvPath  = "",
    [string]$Key      = ""    # 仅用于自动化测试;正常使用请留空,走隐藏输入
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $EnvPath) { $EnvPath = Join-Path $root ".env" }

if ($Key) {
    $plain = $Key.Trim()
} else {
    Write-Host ""
    Write-Host "请粘贴 DeepSeek 的 API 密钥,然后回车(输入过程不显示):" -ForegroundColor Cyan
    $sec = Read-Host "密钥"
    # 真实控制台返回 SecureString;输入被重定向时只返回普通字符串,两种情况都要能处理。
    if ($sec -is [System.Security.SecureString]) {
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
        try   { $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr).Trim() }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    } else {
        $plain = "$sec".Trim()
    }
}

if (-not $plain) {
    Write-Host "没有输入密钥,已退出。" -ForegroundColor Red
    exit 1
}

$lines = @(
    "VLM_PROVIDER=$Provider",
    "VLM_API_KEY=$plain",
    "VLM_BASE_URL=$BaseUrl",
    "VLM_MODEL=$Model"
)
try {
    Set-Content -Path $EnvPath -Value $lines -Encoding utf8
} catch {
    Write-Host "写不进 $EnvPath : $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "可能是文件只读或没有权限。" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "已写入 $EnvPath (密钥长度 $($plain.Length),内容不显示)" -ForegroundColor Green
Write-Host "开始测试调用..." -ForegroundColor Cyan
Write-Host ""

Push-Location $root
try {
    $py = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { Write-Host "找不到 $py" -ForegroundColor Red; exit 1 }
    & $py -m vlm.selftest
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host ""
if ($code -eq 0) {
    Write-Host "测试通过。上面那句就是模型对这张图的回答。" -ForegroundColor Green
} else {
    Write-Host "测试没有通过,完整报错见上。" -ForegroundColor Red
}
exit $code
