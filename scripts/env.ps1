$ErrorActionPreference = 'Stop'
$ProjectRoot = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '..')).FullName
if ($ProjectRoot -match '^[Cc]:|^.:\\$') { throw "Invalid project root: $ProjectRoot" }
function Assert-ProjectPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $prefix = "$ProjectRoot\"
    if ($full -ne $ProjectRoot -and !$full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path outside project: $full"
    }
    for ($part = $full; $part; $part = [IO.Path]::GetDirectoryName($part)) {
        $entry = Get-Item -Force -LiteralPath $part -ErrorAction SilentlyContinue
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Reparse point: $part"
        }
    }
}
Assert-ProjectPath $ProjectRoot
$localPaths = @{
    TEMP='.tmp'; TMP='.tmp'; TMPDIR='.tmp'; PIP_CACHE_DIR='.cache/pip'
    PYTHONPYCACHEPREFIX='.cache/pycache'; KAGGLE_CONFIG_DIR='.secrets'
    KAGGLEHUB_CACHE='.cache/kaggle'; TFHUB_CACHE_DIR='.cache/tfhub'
    KERAS_HOME='.cache/keras'; MPLCONFIGDIR='.cache/matplotlib'
    XDG_CACHE_HOME='.cache'; XDG_CONFIG_HOME='.cache/config'
    JOBLIB_TEMP_FOLDER='.tmp'; npm_config_cache='.cache/npm'
    PLAYWRIGHT_BROWSERS_PATH='.cache/playwright'
}
foreach ($dir in @('.tools','.venv','.cache','.secrets','.tmp')) {
    $path = Join-Path $ProjectRoot $dir
    Assert-ProjectPath $path
    [IO.Directory]::CreateDirectory($path) | Out-Null
}
foreach ($variableName in $localPaths.Keys) {
    $localPath = Join-Path $ProjectRoot $localPaths[$variableName]
    Assert-ProjectPath $localPath
    [Environment]::SetEnvironmentVariable($variableName, $localPath, 'Process')
}
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:PIP_CONFIG_FILE = 'NUL'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$ProjectPython = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
Assert-ProjectPath $ProjectPython
