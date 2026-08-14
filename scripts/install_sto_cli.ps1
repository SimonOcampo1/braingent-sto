# Installs the `sto` function into this machine's PowerShell profiles.
# Idempotent: start.cmd runs it on every boot. It rewrites the whole block, so
# if you move the repo the next boot fixes the path on its own.
#
# It writes to BOTH profiles (PowerShell 7 and Windows PowerShell 5.1) because
# $PROFILE points at a different file in each host, and there is no telling
# which terminal you will open. Installing into only one makes `sto` "not
# exist" in the other.
$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$start = '# >>> STO CLI >>>'
$end = '# <<< STO CLI <<<'

$block = @"
$start
function sto {
    # @(...) is mandatory: without it, an if with a single element returns a
    # String and @splat over a String passes one argument per character.
    `$sto_args = @(if (`$args.Count) { `$args } else { 'status' })
    python "$repo\scripts\cli.py" @sto_args
}
$end
"@

# Both profiles hang off the same Documents (which may be redirected to OneDrive).
$docs = Split-Path (Split-Path $PROFILE)
$targets = @(
    (Join-Path $docs 'PowerShell\Microsoft.PowerShell_profile.ps1'),        # pwsh 7
    (Join-Path $docs 'WindowsPowerShell\Microsoft.PowerShell_profile.ps1')  # 5.1
)

foreach ($target in $targets) {
    New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
    $current = if (Test-Path $target) { Get-Content $target -Raw } else { '' }

    # Drop the old block if it is there, leave the rest of the profile intact.
    $stripped = [regex]::Replace(
        $current,
        "(?ms)^\s*$([regex]::Escape($start)).*?$([regex]::Escape($end))\s*$",
        ''
    ).TrimEnd()

    $new = if ($stripped) { "$stripped`n`n$block`n" } else { "$block`n" }
    if ($new -ne $current) {
        Set-Content -Path $target -Value $new -NoNewline
        Write-Host "sto CLI installed in $target (repo: $repo)"
    }
}
