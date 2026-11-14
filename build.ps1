param([switch]$SkipTests, [string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
    & $pythonPath -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
}
if (-not $SkipTests) {
    & $pythonPath -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw '核心测试未通过' }
    $qaPath = Join-Path $PSScriptRoot ('artifacts\build-smoke-' + [Guid]::NewGuid().ToString('N'))
    & $pythonPath main.py --smoke-test --data-dir $qaPath
    if ($LASTEXITCODE -ne 0) { throw '桌面界面测试未通过' }
}
& $pythonPath tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw '生成图标失败' }
$originalBuildPath = $env:PATH
$originalBuildConfig = $env:PYINSTALLER_CONFIG_DIR
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $PSScriptRoot 'build\pyinstaller-cache'
    # Exclude host tools' unrelated ICU DLLs; Qt uses the Windows ICU API.
    $env:PATH = ((Join-Path $PSScriptRoot '.venv\Scripts'), [Environment]::SystemDirectory, $env:WINDIR) -join ';'
    & $pythonPath -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --distpath $OutputDirectory --name '自律伴侣' --icon assets\companion.ico --add-data 'assets;assets' --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick main.py
    if ($LASTEXITCODE -ne 0) { throw '打包失败' }
} finally {
    $env:PATH = $originalBuildPath
    $env:PYINSTALLER_CONFIG_DIR = $originalBuildConfig
}
Copy-Item -LiteralPath '使用说明.md' -Destination (Join-Path $OutputDirectory '使用说明.md') -Force
Copy-Item -LiteralPath 'THIRD_PARTY_NOTICES.md' -Destination (Join-Path $OutputDirectory 'THIRD_PARTY_NOTICES.md') -Force
if (Test-Path -LiteralPath '验收报告.md') { Copy-Item -LiteralPath '验收报告.md' -Destination (Join-Path $OutputDirectory '验收报告.md') -Force }
if (-not $SkipTests) {
    & $pythonPath tools\test_packaged.py --exe-path (Join-Path $OutputDirectory '自律伴侣.exe')
    if ($LASTEXITCODE -ne 0) { throw '独立 exe 验证未通过' }
}
Write-Output ('已生成：' + (Join-Path $OutputDirectory '自律伴侣.exe'))
