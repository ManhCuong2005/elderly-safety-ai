param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('Model','Catalog','Download','Inventory','Sheets','Split','Extract','Train','Evaluate','Posture','Web','Check','TelegramPair','TelegramTest')]
    [string]$Step,
    [switch]$All,
    [switch]$IncludeReview,
    [switch]$Rebuild,
    [switch]$FreshTest,
    [string]$Video,
    [string]$LinkCode,
    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8765,
    [string]$Cert,
    [string]$Key
)
. "$PSScriptRoot/env.ps1"
if (!(Test-Path -LiteralPath $ProjectPython -PathType Leaf)) { throw 'Run scripts/setup.ps1 first' }
Push-Location -LiteralPath $ProjectRoot
try {
    Write-Host "PROJECT_ROOT=$ProjectRoot"
    $params = switch ($Step) {
        'Model'     { '-m'; 'src.model_setup' }
        'Catalog'   { '-m'; 'src.dataset'; 'catalog' }
        'Download'  { '-m'; 'src.dataset'; 'download'; if ($All) {'--all'}; if ($Video) {'--clip'; $Video} }
        'Inventory' { '-m'; 'src.review'; 'inventory' }
        'Sheets'    { '-m'; 'src.review'; 'sheets'; if ($Video) {'--video'; $Video} }
        'Split'     { '-m'; 'src.train'; 'split'; if ($Rebuild) {'--rebuild'}; if ($FreshTest) {'--fresh-test'} }
        'Extract'   { '-m'; 'src.keypoints'; if ($IncludeReview) {'--include-review'} }
        'Train'     { '-m'; 'src.train'; 'train' }
        'Evaluate'  { '-m'; 'src.train'; 'evaluate' }
        'Posture'   { '-m'; 'src.posture' }
        'TelegramPair' { '-m'; 'src.telegram'; 'pair'; if ($LinkCode) {'--code'; $LinkCode} }
        'TelegramTest' { '-m'; 'src.telegram'; 'test' }
        'Web'       { '-m'; 'src.server'; '--host'; $HostAddress; '--port'; "$Port"; if ($Cert) {'--cert'; $Cert}; if ($Key) {'--key'; $Key} }
        'Check'     { '-m'; 'unittest'; 'discover'; '-s'; 'tests'; '-v' }
    }
    & $ProjectPython @params
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
