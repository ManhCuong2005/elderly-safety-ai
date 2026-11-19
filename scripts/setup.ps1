$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsRoot = Join-Path $projectRoot 'tools'
New-Item -ItemType Directory -Force -Path "$toolsRoot\tmp", "$projectRoot\ai_engine\models" | Out-Null
$env:TEMP = "$toolsRoot\tmp"
$env:TMP = $env:TEMP
$env:MPLCONFIGDIR = "$toolsRoot\matplotlib"
$pythonExe = "$toolsRoot\python\python.exe"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile "$toolsRoot\python.zip" -UseBasicParsing
    Expand-Archive -LiteralPath "$toolsRoot\python.zip" -DestinationPath "$toolsRoot\python"
    Set-Content -LiteralPath "$toolsRoot\python\python312._pth" -Value @('python312.zip', '.', '..\..', '..\..\ai_engine', 'import site')
}
& $pythonExe -m pip --version 2>$null
if ($LASTEXITCODE -ne 0) {
    Invoke-WebRequest 'https://bootstrap.pypa.io/get-pip.py' -OutFile "$toolsRoot\get-pip.py" -UseBasicParsing
    & $pythonExe "$toolsRoot\get-pip.py" --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw 'pip bootstrap failed' }
}
$requirements = "$projectRoot\ai_engine\requirements-lock.txt"
if (-not (Test-Path -LiteralPath $requirements)) { $requirements = "$projectRoot\ai_engine\requirements.txt" }
& $pythonExe -m pip install --no-warn-script-location --cache-dir "$toolsRoot\pip-cache" -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
$modelPath = "$projectRoot\ai_engine\models\pose_landmarker_lite.task"
if (-not (Test-Path -LiteralPath $modelPath)) {
    Invoke-WebRequest 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task' -OutFile $modelPath -UseBasicParsing
}
$fullModelPath = "$projectRoot\ai_engine\models\pose_landmarker_full.task"
if (-not (Test-Path -LiteralPath $fullModelPath)) {
    Invoke-WebRequest 'https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task' -OutFile $fullModelPath -UseBasicParsing
}
if ((Get-FileHash -LiteralPath $fullModelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1') {
    throw 'Full pose model SHA-256 mismatch; verify the download before running'
}
Push-Location "$projectRoot\flutter_app"
try { flutter pub get; if ($LASTEXITCODE -ne 0) { throw 'Flutter dependencies failed' } } finally { Pop-Location }
Write-Output 'Setup complete. Dataset download is a separate bounded operation.'
