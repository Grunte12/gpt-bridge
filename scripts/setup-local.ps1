<##
Create a safe local .env and start the two default services.

This intentionally does not expose a key to the network or print it to the
terminal. Open .env locally and copy the generated key into the Console when it
asks for it.
##>

[CmdletBinding()]
param(
    [switch]$RotateKey,
    [switch]$NoStart
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$examplePath = Join-Path $repoRoot '.env.example'
$envPath = Join-Path $repoRoot '.env'

if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath $examplePath -Destination $envPath
}

$contents = Get-Content -LiteralPath $envPath -Raw
$keyPattern = '(?m)^CHATGPT_API_KEY=(.*)$'
$keyMatch = [regex]::Match($contents, $keyPattern)
$currentKey = if ($keyMatch.Success) { $keyMatch.Groups[1].Value.Trim() } else { '' }
$needsKey = $RotateKey -or -not $currentKey -or $currentKey -eq 'REPLACE_WITH_A_LONG_RANDOM_LOCAL_SECRET' -or $currentKey -eq 'local-dev-key'

if ($needsKey) {
    $bytes = [byte[]]::new(32)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $newKey = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    if ($keyMatch.Success) {
        $contents = [regex]::Replace($contents, $keyPattern, "CHATGPT_API_KEY=$newKey", 1)
    } else {
        $contents = "CHATGPT_API_KEY=$newKey`r`n$contents"
    }
    Set-Content -LiteralPath $envPath -Value $contents -NoNewline
    Write-Host 'Created a new local API key in .env.'
} else {
    Write-Host 'Keeping the existing local API key in .env.'
}

Write-Host 'Next: open http://127.0.0.1:8080 and copy the key from .env into the Console connection settings.'
if (-not $NoStart) {
    Push-Location $repoRoot
    try {
        docker compose up -d --build --remove-orphans gpt-bridge bridge-console
    } finally {
        Pop-Location
    }
}
