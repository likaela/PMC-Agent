# Local interactive retrieval only: never writes passwords to console/log/file.
. (Join-Path $PSScriptRoot 'common.ps1')
$vault = Import-Clixml -LiteralPath $reviewVault
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object Windows.Forms.Form
$form.Text='PMC local account credentials'; $form.Width=650; $form.Height=280
$form.StartPosition='CenterScreen'
$label=New-Object Windows.Forms.Label; $label.Text='Private credentials. Share only with authorized reviewers through a separate secure channel.'
$label.SetBounds(15,15,610,35); $form.Controls.Add($label)
$row=55
foreach ($key in @('A','B','C')) {
    $account=$vault.Accounts[$key]
    $name=New-Object Windows.Forms.Label; $name.Text=$account.User; $name.SetBounds(15,$row,110,25); $form.Controls.Add($name)
    $box=New-Object Windows.Forms.TextBox; $box.ReadOnly=$true; $box.UseSystemPasswordChar=$true
    $box.Text=Unlock-ReviewValue $account.Password; $box.SetBounds(130,$row,490,25); $form.Controls.Add($box)
    $row+=40
}
$toggle=New-Object Windows.Forms.CheckBox; $toggle.Text='Show locally (ensure nobody can see your screen)'; $toggle.SetBounds(15,180,590,25)
$toggle.Add_CheckedChanged({ foreach ($control in $form.Controls) { if ($control -is [Windows.Forms.TextBox]) { $control.UseSystemPasswordChar=!$toggle.Checked } } })
$form.Controls.Add($toggle)
try { [void]$form.ShowDialog() } finally { foreach ($control in $form.Controls) { if ($control -is [Windows.Forms.TextBox]) { $control.Text='' } }; $form.Dispose() }
