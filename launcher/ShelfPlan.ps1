<#
    Shelf Plan launcher -- a small window that installs, starts and opens the
    app so nobody has to touch a command prompt.

    Launched by "Shelf Plan.bat". Long jobs run in a background runspace and
    report through a timer, because PowerShell's WinForms loop is single
    threaded and a Docker build would otherwise freeze the window solid.
#>

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$DockerBin = "$env:ProgramFiles\Docker\Docker\resources\bin"
if (Test-Path $DockerBin) { $env:Path = "$DockerBin;$env:Path" }
$DockerExe  = Join-Path $DockerBin 'docker.exe'
$DesktopExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"

# ---------------------------------------------------------------- helpers --

function Get-Port {
    $p = 8000
    if (Test-Path "$Root\.env") {
        $m = Select-String -Path "$Root\.env" -Pattern '^SHELFPLAN_PORT=(\d+)' -ErrorAction SilentlyContinue
        if ($m) { $p = [int]$m.Matches[0].Groups[1].Value }
    }
    return $p
}

function Read-EnvMap {
    $map = [ordered]@{}
    if (Test-Path "$Root\.env") {
        foreach ($line in Get-Content "$Root\.env") {
            if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
            $k, $v = $line -split '=', 2
            $map[$k.Trim()] = $v.Trim()
        }
    }
    return $map
}

function Write-EnvMap($map) {
    $lines = foreach ($k in $map.Keys) { "$k=$($map[$k])" }
    Set-Content -Path "$Root\.env" -Value $lines -Encoding utf8
}

function New-Secret {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Initialize-Env {
    <# First run: make a .env with a real secret so nothing is left at a default. #>
    if (-not (Test-Path "$Root\.env")) {
        if (Test-Path "$Root\.env.example") {
            Copy-Item "$Root\.env.example" "$Root\.env"
        } else {
            Set-Content "$Root\.env" "SHELFPLAN_PORT=8000" -Encoding utf8
        }
    }
    $map = Read-EnvMap
    $changed = $false
    if (-not $map['SESSION_SECRET']) { $map['SESSION_SECRET'] = New-Secret; $changed = $true }
    if (-not $map.Contains('SHELFPLAN_PORT')) { $map['SHELFPLAN_PORT'] = '8000'; $changed = $true }
    if (-not $map.Contains('COOKIE_SECURE')) { $map['COOKIE_SECURE'] = '0'; $changed = $true }
    if (-not $map.Contains('SIGNUP_MODE')) { $map['SIGNUP_MODE'] = 'open'; $changed = $true }
    if (-not $map.Contains('DATABASE_URL')) {
        $map['DATABASE_URL'] = 'sqlite:////app/data/shelfplan.db'; $changed = $true
    }
    if ($changed) { Write-EnvMap $map }
}

function Test-DockerInstalled { Test-Path $DockerExe }

function Test-DockerRunning {
    if (-not (Test-DockerInstalled)) { return $false }
    try {
        & $DockerExe info --format '{{.ServerVersion}}' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Test-AppRunning {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$(Get-Port)/api/health" -TimeoutSec 3 -UseBasicParsing
        return $r.StatusCode -eq 200
    } catch { return $false }
}

# ------------------------------------------------------------ background ---
# One job at a time; the timer drains its output into the log box.

$script:Job = $null
$script:OnDone = $null

function Start-Work {
    param([string]$Label, [scriptblock]$Work, [scriptblock]$Done)
    $script:Job = Start-Job -ScriptBlock $Work -ArgumentList $Root, $DockerExe, $DesktopExe
    $script:OnDone = $Done
    Set-Busy $true $Label
}

# ------------------------------------------------------------------- UI ----

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Shelf Plan'
$form.Size = New-Object System.Drawing.Size(560, 460)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedSingle'
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(246, 248, 245)
$icoPath = Join-Path $Root 'webapp\static\icons\shelfplan.ico'
if (Test-Path $icoPath) { try { $form.Icon = New-Object System.Drawing.Icon($icoPath) } catch {} }

$title = New-Object System.Windows.Forms.Label
$title.Text = 'Shelf Plan'
$title.Font = New-Object System.Drawing.Font('Segoe UI', 20, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(19, 23, 20)
$title.Location = New-Object System.Drawing.Point(26, 20)
$title.Size = New-Object System.Drawing.Size(400, 36)
$form.Controls.Add($title)

$statusDot = New-Object System.Windows.Forms.Label
$statusDot.Text = [char]0x25CF
$statusDot.Font = New-Object System.Drawing.Font('Segoe UI', 13)
$statusDot.Location = New-Object System.Drawing.Point(27, 62)
$statusDot.Size = New-Object System.Drawing.Size(20, 24)
$form.Controls.Add($statusDot)

$status = New-Object System.Windows.Forms.Label
$status.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$status.ForeColor = [System.Drawing.Color]::FromArgb(73, 83, 75)
$status.Location = New-Object System.Drawing.Point(48, 64)
$status.Size = New-Object System.Drawing.Size(470, 22)
$form.Controls.Add($status)

$primary = New-Object System.Windows.Forms.Button
$primary.Text = 'Start Shelf Plan'
$primary.Font = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
$primary.Location = New-Object System.Drawing.Point(26, 100)
$primary.Size = New-Object System.Drawing.Size(230, 46)
$primary.FlatStyle = 'Flat'
$primary.FlatAppearance.BorderSize = 0
$primary.BackColor = [System.Drawing.Color]::FromArgb(47, 107, 79)
$primary.ForeColor = [System.Drawing.Color]::White
$primary.Cursor = 'Hand'
$form.Controls.Add($primary)

$openBtn = New-Object System.Windows.Forms.Button
$openBtn.Text = 'Open in browser'
$openBtn.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$openBtn.Location = New-Object System.Drawing.Point(266, 100)
$openBtn.Size = New-Object System.Drawing.Size(150, 46)
$openBtn.FlatStyle = 'Flat'
$openBtn.BackColor = [System.Drawing.Color]::White
$openBtn.Enabled = $false
$openBtn.Cursor = 'Hand'
$form.Controls.Add($openBtn)

$stopBtn = New-Object System.Windows.Forms.Button
$stopBtn.Text = 'Stop'
$stopBtn.Font = New-Object System.Drawing.Font('Segoe UI', 10)
$stopBtn.Location = New-Object System.Drawing.Point(426, 100)
$stopBtn.Size = New-Object System.Drawing.Size(92, 46)
$stopBtn.FlatStyle = 'Flat'
$stopBtn.BackColor = [System.Drawing.Color]::White
$stopBtn.Enabled = $false
$stopBtn.Cursor = 'Hand'
$form.Controls.Add($stopBtn)

$addr = New-Object System.Windows.Forms.LinkLabel
$addr.Font = New-Object System.Drawing.Font('Consolas', 10)
$addr.Location = New-Object System.Drawing.Point(26, 158)
$addr.Size = New-Object System.Drawing.Size(492, 44)
$addr.LinkColor = [System.Drawing.Color]::FromArgb(47, 107, 79)
$form.Controls.Add($addr)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Location = New-Object System.Drawing.Point(26, 206)
$bar.Size = New-Object System.Drawing.Size(492, 6)
$bar.Style = 'Marquee'
$bar.MarqueeAnimationSpeed = 0
$form.Controls.Add($bar)

$log = New-Object System.Windows.Forms.TextBox
$log.Multiline = $true
$log.ScrollBars = 'Vertical'
$log.ReadOnly = $true
$log.Font = New-Object System.Drawing.Font('Consolas', 8.5)
$log.Location = New-Object System.Drawing.Point(26, 222)
$log.Size = New-Object System.Drawing.Size(492, 140)
$log.BackColor = [System.Drawing.Color]::FromArgb(238, 241, 237)
$log.BorderStyle = 'FixedSingle'
$form.Controls.Add($log)

$settingsBtn = New-Object System.Windows.Forms.Button
$settingsBtn.Text = 'Settings'
$settingsBtn.Location = New-Object System.Drawing.Point(26, 372)
$settingsBtn.Size = New-Object System.Drawing.Size(110, 32)
$settingsBtn.FlatStyle = 'Flat'
$settingsBtn.BackColor = [System.Drawing.Color]::White
$settingsBtn.Cursor = 'Hand'
$form.Controls.Add($settingsBtn)

$shortcutBtn = New-Object System.Windows.Forms.Button
$shortcutBtn.Text = 'Add desktop shortcut'
$shortcutBtn.Location = New-Object System.Drawing.Point(144, 372)
$shortcutBtn.Size = New-Object System.Drawing.Size(170, 32)
$shortcutBtn.FlatStyle = 'Flat'
$shortcutBtn.BackColor = [System.Drawing.Color]::White
$shortcutBtn.Cursor = 'Hand'
$form.Controls.Add($shortcutBtn)

$helpBtn = New-Object System.Windows.Forms.Button
$helpBtn.Text = 'Handbook'
$helpBtn.Location = New-Object System.Drawing.Point(408, 372)
$helpBtn.Size = New-Object System.Drawing.Size(110, 32)
$helpBtn.FlatStyle = 'Flat'
$helpBtn.BackColor = [System.Drawing.Color]::White
$helpBtn.Cursor = 'Hand'
$form.Controls.Add($helpBtn)

function Add-Log([string]$text) {
    if (-not $text) { return }
    foreach ($line in ($text -split "`r?`n")) {
        if ($line.Trim()) { $log.AppendText($line.TrimEnd() + "`r`n") }
    }
    $log.SelectionStart = $log.TextLength
    $log.ScrollToCaret()
}

function Set-Dot([string]$state) {
    switch ($state) {
        'on'    { $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(47, 107, 79) }
        'busy'  { $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(138, 100, 16) }
        default { $statusDot.ForeColor = [System.Drawing.Color]::FromArgb(156, 58, 44) }
    }
}

function Set-Busy([bool]$busy, [string]$label) {
    $bar.MarqueeAnimationSpeed = if ($busy) { 30 } else { 0 }
    $primary.Enabled = -not $busy
    $stopBtn.Enabled = (-not $busy) -and $stopBtn.Tag -eq 'able'
    $settingsBtn.Enabled = -not $busy
    if ($label) { $status.Text = $label }
    if ($busy) { Set-Dot 'busy' }
}

function Update-State {
    $port = Get-Port
    if (-not (Test-DockerInstalled)) {
        Set-Dot 'off'
        $status.Text = 'Docker is not installed yet. One click sets it up.'
        $primary.Text = 'Install Docker'
        $openBtn.Enabled = $false
        $stopBtn.Tag = ''; $stopBtn.Enabled = $false
        $addr.Text = ''
        return
    }
    if (Test-AppRunning) {
        Set-Dot 'on'
        $status.Text = 'Running. Ready to use.'
        $primary.Text = 'Restart'
        $openBtn.Enabled = $true
        $stopBtn.Tag = 'able'; $stopBtn.Enabled = $true
        $links = @("http://localhost:$port")
        $ts = "$env:ProgramFiles\Tailscale\tailscale.exe"
        if (Test-Path $ts) {
            try {
                $name = (& $ts status --json 2>$null | ConvertFrom-Json).Self.DNSName
                if ($name) { $links += "http://$($name.TrimEnd('.')):$port" }
            } catch {}
        }
        $addr.Text = ($links -join "`r`n")
        $addr.Links.Clear()
        $offset = 0
        foreach ($l in $links) {
            $addr.Links.Add($offset, $l.Length, $l) | Out-Null
            $offset += $l.Length + 2
        }
        return
    }
    Set-Dot 'off'
    $status.Text = if (Test-DockerRunning) { 'Stopped.' } else { 'Docker is not running.' }
    $primary.Text = 'Start Shelf Plan'
    $openBtn.Enabled = $false
    $stopBtn.Tag = ''; $stopBtn.Enabled = $false
    $addr.Text = ''
}

# ---------------------------------------------------------------- actions --

$primary.Add_Click({
    if (-not (Test-DockerInstalled)) {
        Add-Log 'Installing Docker Desktop. Windows will ask for permission -- say yes.'
        Add-Log 'This downloads about 600 MB and takes a few minutes.'
        Start-Work 'Installing Docker Desktop...' {
            param($root, $docker, $desktop)
            & winget.exe install --id Docker.DockerDesktop -e --source winget `
                --accept-package-agreements --accept-source-agreements 2>&1 | Out-String
        } { Add-Log 'Docker installed. Press Start again to launch Shelf Plan.' }
        return
    }

    Initialize-Env
    Add-Log 'Starting. The first run builds the app and can take a few minutes.'
    Start-Work 'Starting Shelf Plan...' {
        param($root, $docker, $desktop)
        Set-Location $root
        $out = ''
        & $docker info 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $out += "Starting Docker Desktop...`n"
            Start-Process -FilePath $desktop
            foreach ($i in 1..48) {
                Start-Sleep -Seconds 5
                & $docker info 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { $out += "Docker is ready.`n"; break }
            }
        }
        $out += (& $docker compose up -d --build 2>&1 | Out-String)
        return $out
    } { Add-Log 'Started.' }
})

$stopBtn.Add_Click({
    Start-Work 'Stopping...' {
        param($root, $docker, $desktop)
        Set-Location $root
        & $docker compose down 2>&1 | Out-String
    } { Add-Log 'Stopped. Your data is kept.' }
})

$openBtn.Add_Click({ Start-Process "http://localhost:$(Get-Port)" })

$addr.Add_LinkClicked({ Start-Process $_.Link.LinkData })

$helpBtn.Add_Click({
    Start-Process 'https://claude.ai/code/artifact/609cf294-69bf-4dc6-93f6-4f8ffb85c192'
})

$shortcutBtn.Add_Click({
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnk = Join-Path $desktop 'Shelf Plan.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = Join-Path $Root 'Shelf Plan.bat'
    $s.WorkingDirectory = $Root
    $s.Description = 'Meal plans and grocery prices'
    $ico = Join-Path $Root 'webapp\static\icons\shelfplan.ico'
    if (Test-Path $ico) { $s.IconLocation = $ico }
    $s.Save()
    Add-Log "Shortcut added to your desktop."
    [System.Windows.Forms.MessageBox]::Show(
        'A "Shelf Plan" shortcut is on your desktop. Double-click it any time.',
        'Shortcut added', 'OK', 'Information') | Out-Null
})

$settingsBtn.Add_Click({
    $map = Read-EnvMap
    $d = New-Object System.Windows.Forms.Form
    $d.Text = 'Settings'
    $d.Size = New-Object System.Drawing.Size(520, 470)
    $d.StartPosition = 'CenterParent'
    $d.FormBorderStyle = 'FixedDialog'
    $d.BackColor = $form.BackColor

    $y = 18
    function Add-Field($label, $key, $hint, [bool]$secret = $false) {
        $l = New-Object System.Windows.Forms.Label
        $l.Text = $label
        $l.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
        $l.Location = New-Object System.Drawing.Point(20, $script:y)
        $l.Size = New-Object System.Drawing.Size(460, 18)
        $d.Controls.Add($l)
        $t = New-Object System.Windows.Forms.TextBox
        $t.Text = $map[$key]
        $t.Location = New-Object System.Drawing.Point(20, ($script:y + 20))
        $t.Size = New-Object System.Drawing.Size(460, 24)
        if ($secret) { $t.UseSystemPasswordChar = $true }
        $t.Tag = $key
        $d.Controls.Add($t)
        if ($hint) {
            $h = New-Object System.Windows.Forms.Label
            $h.Text = $hint
            $h.Font = New-Object System.Drawing.Font('Segoe UI', 8)
            $h.ForeColor = [System.Drawing.Color]::FromArgb(121, 131, 123)
            $h.Location = New-Object System.Drawing.Point(20, ($script:y + 46))
            $h.Size = New-Object System.Drawing.Size(460, 16)
            $d.Controls.Add($h)
            $script:y += 68
        } else { $script:y += 52 }
        return $t
    }

    $script:y = 18
    $tPort = Add-Field 'Port' 'SHELFPLAN_PORT' 'Change only if 8000 is already used by something else.'
    $tMode = Add-Field 'Who can sign up' 'SIGNUP_MODE' 'open, invite or closed. Use invite once others can reach it.'
    $tCode = Add-Field 'Invite code' 'SIGNUP_INVITE_CODE' 'Only needed when the mode above is invite.'
    $tUser = Add-Field 'Email address for sending' 'SMTP_USER' 'Used to send password reset links. Leave blank to skip.'
    $tPass = Add-Field 'Email app password' 'SMTP_PASSWORD' 'Gmail needs an App Password, not your normal password.' $true

    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = 'Save'
    $ok.Location = New-Object System.Drawing.Point(300, 380)
    $ok.Size = New-Object System.Drawing.Size(85, 32)
    $ok.BackColor = [System.Drawing.Color]::FromArgb(47, 107, 79)
    $ok.ForeColor = [System.Drawing.Color]::White
    $ok.FlatStyle = 'Flat'
    $d.Controls.Add($ok)

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = 'Cancel'
    $cancel.Location = New-Object System.Drawing.Point(395, 380)
    $cancel.Size = New-Object System.Drawing.Size(85, 32)
    $cancel.FlatStyle = 'Flat'
    $cancel.BackColor = [System.Drawing.Color]::White
    $d.Controls.Add($cancel)
    $cancel.Add_Click({ $d.Close() })

    $ok.Add_Click({
        foreach ($c in @($tPort, $tMode, $tCode, $tUser, $tPass)) {
            $map[[string]$c.Tag] = $c.Text.Trim()
        }
        if ($map['SMTP_USER']) {
            if (-not $map['SMTP_HOST']) { $map['SMTP_HOST'] = 'smtp.gmail.com' }
            if (-not $map['SMTP_PORT']) { $map['SMTP_PORT'] = '587' }
            $map['SMTP_FROM'] = $map['SMTP_USER']
        }
        Write-EnvMap $map
        $d.Close()
        Add-Log 'Settings saved. Press Restart to apply them.'
    })

    $d.ShowDialog($form) | Out-Null
})

# ------------------------------------------------------------------ pump ---

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 900
$timer.Add_Tick({
    if ($script:Job) {
        Receive-Job $script:Job -ErrorAction SilentlyContinue | ForEach-Object { Add-Log ([string]$_) }
        if ($script:Job.State -in 'Completed', 'Failed', 'Stopped') {
            Receive-Job $script:Job -ErrorAction SilentlyContinue | ForEach-Object { Add-Log ([string]$_) }
            Remove-Job $script:Job -Force -ErrorAction SilentlyContinue
            $script:Job = $null
            Set-Busy $false ''
            if ($script:OnDone) { & $script:OnDone; $script:OnDone = $null }
            Update-State
        }
        return
    }
    Update-State
})
$timer.Start()

Initialize-Env
Update-State
Add-Log 'Ready. Press Start Shelf Plan.'

# Offer the shortcut once, on the very first run -- but only after the window
# is actually on screen. Prompting before ShowDialog puts a modal box in front
# of nothing, which looks like an error rather than a welcome.
$form.Add_Shown({
    $stamp = Join-Path $Root '.launcher-seen'
    if (Test-Path $stamp) { return }
    New-Item -ItemType File -Path $stamp -Force | Out-Null
    $ans = [System.Windows.Forms.MessageBox]::Show(
        $form,
        "Add a Shelf Plan shortcut to your desktop, so you can open it with a double-click from now on?",
        'Welcome to Shelf Plan', 'YesNo', 'Question')
    if ($ans -eq 'Yes') { $shortcutBtn.PerformClick() }
})

[void]$form.ShowDialog()
$timer.Stop()
