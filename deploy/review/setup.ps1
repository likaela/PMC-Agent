param([switch]$GenerateRandomPasswords, [Parameter(Mandatory=$true)][string]$ApprovedDatasetVersion)
. (Join-Path $PSScriptRoot 'common.ps1')
if ((Test-Path -LiteralPath $reviewVault) -or (Test-Path -LiteralPath $reviewSettings)) {
    throw 'Private configuration already exists. It will not be overwritten or rotated.'
}
if (!(Test-Path -LiteralPath $reviewCaddy)) { throw 'Prepare the verified portable Caddy first.' }
$unitsPath = Join-Path $reviewRoot 'data/facts/confirmations/inventory_units.json'
$quantityPath = Join-Path $reviewRoot 'data/facts/confirmations/inventory_quantity_use.json'
$profile = Read-ReviewJson (Join-Path $reviewRoot 'data/facts/confirmations/review_slim.json')
$datasetPath = $profile.kq_z112_review_slim
$dataset = Read-ReviewJson (Join-Path $reviewRoot $datasetPath)
if ($dataset.dataset_version -ne $ApprovedDatasetVersion -or $dataset.synthetic -ne $false -or $dataset.retained_material_count -ne 34) {
    throw 'The explicitly approved real analysis dataset does not match.'
}
$units = (Read-ReviewJson $unitsPath).confirmations
if ($units.Count -ne 1) { throw 'One explicitly approved inventory source is required.' }
$inventory = Join-Path $reviewRoot $units[0].source_uri
if ((Get-FileHash -LiteralPath $inventory -Algorithm SHA256).Hash -ne $units[0].content_sha256) { throw 'Approved inventory checksum mismatch.' }
foreach ($path in @($quantityPath, (Join-Path $reviewRoot 'data/facts/pmc_facts.db'))) {
    if (!(Test-Path -LiteralPath $path)) { throw 'An approved private source is missing.' }
}
function New-ReviewSecret {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}
function Get-ReviewPasswordHash([string]$Plaintext) {
    # Password travels over stdin, never the process command line or console.
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $reviewCaddy; $info.Arguments = 'hash-password'
    $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $process = [Diagnostics.Process]::Start($info)
    try {
        # Caddy removes LF only; Windows WriteLine would leave CR in the password.
        $process.StandardInput.Write($Plaintext + "`n"); $process.StandardInput.Close()
        $hash = $process.StandardOutput.ReadToEnd().Trim(); $ignored = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0 -or !$hash.StartsWith('$2')) { throw 'Password hashing failed.' }
        return $hash
    } finally { $process.Dispose() }
}
$accounts = @{}
foreach ($entry in @(@('A','reviewer-a'), @('B','reviewer-b'), @('C','demo-only'))) {
    $secure = if ($GenerateRandomPasswords) { ConvertTo-SecureString (New-ReviewSecret) -AsPlainText -Force } else { Read-Host ('Password for ' + $entry[1]) -AsSecureString }
    $plain = Unlock-ReviewValue $secure
    if ($plain.Length -lt 16) { throw 'Use a unique password with at least 16 characters.' }
    $accounts[$entry[0]] = @{ User=$entry[1]; Password=$secure; Hash=(Get-ReviewPasswordHash $plain) }
    $plain = $null
}
$settings = @{
    facts_path='data/facts/pmc_facts.db'; inventory_path=$units[0].source_uri
    units_path='data/facts/confirmations/inventory_units.json'
    quantity_path='data/facts/confirmations/inventory_quantity_use.json'
    slim_dataset_path=$datasetPath
    users=@{ 'reviewer-a'=@('KQ-Z112','KQ-BHX3588M','DEMO-PMC-01'); 'reviewer-b'=@('KQ-Z112','KQ-BHX3588M','DEMO-PMC-01'); 'demo-only'=@('DEMO-PMC-01') }
}
$vault = @{ ProxySecret=(ConvertTo-SecureString (New-ReviewSecret) -AsPlainText -Force); Accounts=$accounts }
$vault | Export-Clixml -LiteralPath $reviewVault
[IO.File]::WriteAllText($reviewSettings, ($settings | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
foreach ($path in @($reviewVault,$reviewSettings)) {
    $acl = Get-Acl -LiteralPath $path
    $acl.SetAccessRuleProtection($true,$false)
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','Allow')
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $path -AclObject $acl
}
Write-Host 'Private configuration prepared. Three separate accounts are ready; no credentials were printed.'
Write-Host 'Passwords and proxy secret use Windows DPAPI for this Windows user/machine. Use show-credentials.ps1 locally to retrieve them.'
