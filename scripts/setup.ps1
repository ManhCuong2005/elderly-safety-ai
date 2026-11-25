param()
. "$PSScriptRoot/env.ps1"
Push-Location -LiteralPath $ProjectRoot
try {
    Write-Host "PROJECT_ROOT=$ProjectRoot"
    if (!(Test-Path -LiteralPath $ProjectPython -PathType Leaf)) {
        $version = '3.12.10'
        $checksum = '0EB85C2DFCCCCF1B17352DE4C397F69194035B7D37149EACC16F1147D93DE3B8'
        $archive = Join-Path $ProjectRoot '.tools/python.nupkg'
        Assert-ProjectPath $archive
        if (!(Test-Path -LiteralPath $archive)) {
            $free = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($ProjectRoot)).AvailableFreeSpace
            if ($free -lt 768MB) { throw 'Need 768 MB for Python and wheels' }
            & curl.exe -q -fSL --retry 2 --max-time 120 -o $archive "https://api.nuget.org/v3-flatcontainer/python/$version/python.$version.nupkg"
            if ($LASTEXITCODE -ne 0) { throw 'Unable to download Python from NuGet' }
        }
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash -ne $checksum) {
            throw 'Python archive checksum mismatch'
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $package = [IO.Compression.ZipFile]::OpenRead($archive)
        try {
            foreach ($entry in $package.Entries) {
                if ($entry.FullName -match '(^/)|(^|/)\.\.(/|$)|[:\\]' -or
                    ($entry.ExternalAttributes -shr 16 -band 61440) -eq 40960) {
                    throw 'Unsafe runtime entry'
                }
            }
            foreach ($entry in $package.Entries) {
                if (!$entry.FullName.StartsWith('tools/') -or !$entry.Name) { continue }
                $target = Join-Path "$ProjectRoot/.tools/cpython" $entry.FullName
                Assert-ProjectPath $target
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
                if (!(Test-Path -LiteralPath $target)) {
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $false)
                } elseif ((Get-Item -LiteralPath $target).Length -ne $entry.Length) {
                    throw "Incomplete runtime file: $target"
                }
            }
        } finally {
            $package.Dispose()
        }
        $bootstrap = Join-Path $ProjectRoot '.tools/cpython/tools/python.exe'
        & $bootstrap -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Unable to create .venv' }
    }
    & $ProjectPython --version
    & $ProjectPython -m pip --isolated install --cache-dir $env:PIP_CACHE_DIR -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency setup failed' }
    & $ProjectPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed' }
} finally {
    Pop-Location
}
