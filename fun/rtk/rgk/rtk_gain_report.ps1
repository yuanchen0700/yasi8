# rtk_gain_report.ps1 - Pure English, UTF-8 with BOM required

# --- Encoding fix: force UTF-8 when reading native command (rtk) output ---
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

function Run-Cmd {
    param([string]$cmd)
    try {
        $result = & cmd /c $cmd 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0 -and $result.Trim() -eq "") {
            return "Command failed (exit $LASTEXITCODE)"
        }
        return $result.Trim()
    } catch {
        return "Error: $_"
    }
}

function Parse-ByCommandTable {
    param([string]$output)
    $data = [ordered]@{}
    if (-not $output) { return $data }
    $inTable = $false
    foreach ($line in ($output -split "`r?`n")) {
        if ($line -match '^\s*#\s+Command') { $inTable = $true; continue }
        if (-not $inTable) { continue }
        if ($line -match '^\s*\-+\s*$') { continue }
        if ($line -match '^\s*(\d+)\.\s+(.+?)\s+(\d+)\s+(\d+)\s+([\d.]+%)\s+([\d.]+ms)') {
            $data[$Matches[2].Trim()] = @{
                count      = [int]$Matches[3]
                tokens     = [int]$Matches[4]
                percentage = $Matches[5]
                time       = $Matches[6]
            }
            continue
        }
        if ($line.Trim() -ne "" -and $line -notmatch '^\s*[─═]+\s*$') { break }
    }
    return $data
}

function Parse-DailyTable {
    param([string]$output)
    $data = [ordered]@{}
    if (-not $output) { return $data }
    $inTable = $false
    foreach ($line in ($output -split "`r?`n")) {
        if ($line -match '^\s*Date\s+Cmds') { $inTable = $true; continue }
        if (-not $inTable) { continue }
        if ($line -match '^\s*\-+\s*$') { continue }
        if ($line -match '^\s*(\d{4}-\d{2}-\d{2})\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+%)\s+([\d.]+ms)') {
            $data[$Matches[1].Trim()] = @{
                cmds   = [int]$Matches[2]
                input  = [int]$Matches[3]
                output = [int]$Matches[4]
                saved  = [int]$Matches[5]
                pct    = $Matches[6]
                time   = $Matches[7]
            }
            continue
        }
        if ($line.Trim() -ne "" -and $line -notmatch '^\s*[─═]+\s*$') { break }
    }
    return $data
}

Write-Host "Fetching RTK data ..." -ForegroundColor Cyan
$totalOut = Run-Cmd "rtk gain -f json"
$historyOut = Run-Cmd "rtk gain --history"
$dailyOut = Run-Cmd "rtk gain -d"

if ($totalOut -match "Command failed|Error|not found") {
    Write-Host "ERROR: Cannot run RTK. Please ensure it is installed." -ForegroundColor Red
    Write-Host $totalOut -ForegroundColor Yellow
    pause
    exit 1
}

# --- Summary from JSON (machine readable, stable) ---
$summary = $null
try { $summary = $totalOut | ConvertFrom-Json } catch { }
$totalSaved = "N/A"; $totalPct = ""; $totalCommands = "N/A"; $totalInput = "N/A"; $totalOutput = "N/A"; $totalTime = "N/A"
if ($summary -and $summary.summary) {
    $totalSaved = $summary.summary.total_saved
    $totalPct = "($([math]::Round([double]$summary.summary.avg_savings_pct, 1))%)"
    $totalCommands = $summary.summary.total_commands
    $totalInput = $summary.summary.total_input
    $totalOutput = $summary.summary.total_output
    $totalTime = "$($summary.summary.total_time_ms)ms"
}

# --- Per-command breakdown from the text table ---
$historyData = Parse-ByCommandTable $historyOut
$cmdCount = if ($historyData.Count -gt 0) { $historyData.Count } else { $totalCommands }

# Build JSON arrays for chart
$labelsJson = $historyData.Keys | ConvertTo-Json -Compress
$valuesJson = $historyData.Values | ForEach-Object { $_.tokens } | ConvertTo-Json -Compress

# Read the HTML template (here-string)
$htmlTemplate = @'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RTK Token Savings Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; }
        body { font-family: 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; margin: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        .card { background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 24px; margin-bottom: 24px; }
        h1, h2 { margin-top: 0; }
        .stat-grid { display: flex; gap: 24px; flex-wrap: wrap; }
        .stat-item { flex: 1; min-width: 140px; }
        .stat-item .label { color: #888; font-size: 14px; text-transform: uppercase; letter-spacing: 0.5px; }
        .stat-item .value { font-size: 36px; font-weight: 700; color: #1e293b; }
        .stat-item .value .pct { font-size: 20px; color: #10b981; margin-left: 8px; }
        table { width: 100%; border-collapse: collapse; margin-top: 16px; }
        th, td { text-align: left; padding: 12px 8px; border-bottom: 1px solid #e9e9e9; }
        th { background: #f8fafc; font-weight: 600; color: #475569; }
        td.num, th.num { text-align: right; }
        .raw-output { background: #f1f5f9; padding: 16px; border-radius: 8px; font-family: 'JetBrains Mono', monospace; font-size: 13px; white-space: pre-wrap; overflow-x: auto; }
        .chart-container { height: 280px; margin: 16px 0 8px 0; }
        .footer { text-align: center; color: #94a3b8; font-size: 13px; margin-top: 20px; }
        .error { color: #dc2626; background: #fee2e2; padding: 12px; border-radius: 8px; }
    </style>
</head>
<body>
<div class="container">
    <h1>RTK Token Savings Overview</h1>
    <!-- TOTAL_CARD -->
    <!-- DAILY_CARD -->
    <!-- HISTORY_TABLE -->
    <div class="card">
        <h2>Raw Command Output</h2>
        <div class="raw-output">RAW_OUTPUT</div>
    </div>
    <div class="footer">Report generated by rtk_gain_report.ps1</div>
</div>
<script>
    // CHART_SCRIPT
</script>
</body>
</html>
'@

# Build total card
if ($totalOut -match "Error|Command failed|not found") {
    $totalCard = "<div class=`"card`"><div class=`"error`">ERROR: $totalOut</div></div>"
} else {
    $totalCard = @"
<div class="card">
    <div class="stat-grid">
        <div class="stat-item">
            <div class="label">Total Tokens Saved</div>
            <div class="value">$totalSaved <span class="pct">$totalPct</span></div>
        </div>
        <div class="stat-item">
            <div class="label">Commands</div>
            <div class="value">$totalCommands</div>
        </div>
        <div class="stat-item">
            <div class="label">Input Tokens</div>
            <div class="value">$totalInput</div>
        </div>
        <div class="stat-item">
            <div class="label">Output Tokens</div>
            <div class="value">$totalOutput</div>
        </div>
        <div class="stat-item">
            <div class="label">Exec Time</div>
            <div class="value">$totalTime</div>
        </div>
    </div>
</div>
"@
}

# Build history table
if ($historyData.Count -eq 0) {
    $historyTable = @"
<div class="card">
    <h2>Command Breakdown</h2>
    <p>No history data yet. Run at least one RTK proxy command (e.g., <code>rtk git status</code>).</p>
</div>
"@
} else {
    $rows = ""
    foreach ($cmd in $historyData.Keys) {
        $info = $historyData[$cmd]
        $pctDisplay = if ($info.percentage) { $info.percentage } else { '&mdash;' }
        $rows += "<tr><td><code>$cmd</code></td><td class=`"num`">$($info.count)</td><td class=`"num`">$($info.tokens)</td><td class=`"num`">$pctDisplay</td><td class=`"num`">$($info.time)</td></tr>`n"
    }
    $historyTable = @"
<div class="card">
    <h2>Command Breakdown</h2>
    <div class="chart-container">
        <canvas id="savingsChart"></canvas>
    </div>
    <table>
        <thead><tr><th>Command</th><th class="num">Count</th><th class="num">Saved Tokens</th><th class="num">Avg%</th><th class="num">Time</th></tr></thead>
        <tbody>
$rows
        </tbody>
    </table>
</div>
"@
}

# Build daily savings card
$dailyData = Parse-DailyTable $dailyOut

# Persistent daily store: survives rtk's 90-day history window
$dailyStore = Join-Path $PSScriptRoot "rtk_gain_daily.json"
$persisted = [ordered]@{}
if (Test-Path $dailyStore) {
    try {
        $loaded = Get-Content -Path $dailyStore | ConvertFrom-Json
        foreach ($p in $loaded) {
            if ($p.date) {
                $persisted[[string]$p.date] = @{
                    cmds   = [int]$p.cmds
                    input  = [int]$p.input
                    output = [int]$p.output
                    saved  = [int]$p.saved
                    pct    = [string]$p.pct
                    time   = [string]$p.time
                }
            }
        }
    } catch { $persisted = [ordered]@{} }
}
foreach ($day in $dailyData.Keys) { $persisted[$day] = $dailyData[$day] }
$sortedKeys = @($persisted.Keys | Sort-Object)
$dailyData = [ordered]@{}
foreach ($key in $sortedKeys) { $dailyData[$key] = $persisted[$key] }
$storeRows = @()
foreach ($key in $dailyData.Keys) {
    $d = $dailyData[$key]
    $storeRows += [pscustomobject]@{ date = $key; cmds = $d.cmds; input = $d.input; output = $d.output; saved = $d.saved; pct = $d.pct; time = $d.time }
}
try { $storeRows | ConvertTo-Json | Out-File -FilePath $dailyStore -Encoding UTF8 } catch { }

if ($dailyData.Count -eq 0) {
    $dailyCard = @"
<div class="card">
    <h2>Daily Savings</h2>
    <p>No daily data yet. Run at least one RTK proxy command (e.g., <code>rtk git status</code>).</p>
</div>
"@
    $dailyChartScript = ""
} else {
    $dailyLabelsJson = $dailyData.Keys | ConvertTo-Json -Compress
    $dailyValuesJson = $dailyData.Values | ForEach-Object { $_.saved } | ConvertTo-Json -Compress
    $dailyMaxSaved = ($dailyData.Values | ForEach-Object { [int]$_.saved } | Measure-Object -Maximum).Maximum
    $yMax = 0
    if ($dailyMaxSaved -gt 0) {
        $mag = [math]::Pow(10, [math]::Floor([math]::Log10([double]$dailyMaxSaved)))
        $norm = [double]$dailyMaxSaved / $mag
        $nice = if ($norm -le 1) { 1 } elseif ($norm -le 2) { 2 } elseif ($norm -le 5) { 5 } else { 10 }
        $yMax = [math]::Max(1, [int]($nice * $mag))
    }
    $dailyRows = ""
    foreach ($day in $dailyData.Keys) {
        $d = $dailyData[$day]
        $dailyRows += "<tr><td><code>$day</code></td><td class=`"num`">$($d.cmds)</td><td class=`"num`">$($d.input)</td><td class=`"num`">$($d.output)</td><td class=`"num`">$($d.saved)</td><td class=`"num`">$($d.pct)</td><td class=`"num`">$($d.time)</td></tr>`n"
    }
    $chartHeight = [math]::Max(280, $dailyData.Count * 36)
    $dailyCard = @"
<div class="card">
    <h2>Daily Savings <span style="font-size:14px;color:#888">($($dailyData.Count) days)</span></h2>
    <div class="chart-container" style="height:${chartHeight}px">
        <canvas id="dailyChart"></canvas>
    </div>
    <table>
        <thead><tr><th>Date</th><th class="num">Cmds</th><th class="num">Input</th><th class="num">Output</th><th class="num">Saved</th><th class="num">Save%</th><th class="num">Time</th></tr></thead>
        <tbody>
$dailyRows
        </tbody>
    </table>
</div>
"@
    $dailyChartScript = @"
const dctx = document.getElementById('dailyChart').getContext('2d');
const dailyLabels = $dailyLabelsJson;
const dailyValues = $dailyValuesJson;
const yAxisMax = $yMax;
new Chart(dctx, {
    type: 'bar',
    data: {
        labels: dailyLabels,
        datasets: [{
            label: 'Tokens Saved per Day',
            data: dailyValues,
            backgroundColor: 'rgba(59, 130, 246, 0.6)',
            borderColor: 'rgba(59, 130, 246, 1)',
            borderWidth: 1,
            borderRadius: 4
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
            y: { beginAtZero: true, max: yAxisMax, grid: { color: '#e9e9e9' } },
            x: { grid: { display: false }, ticks: { autoSkip: true, maxTicksLimit: 15, maxRotation: 45, minRotation: 0 } }
        }
    }
});
"@
}

# Chart script
if ($historyData.Count -gt 0) {
    $chartScript = @"
const ctx = document.getElementById('savingsChart').getContext('2d');
const labels = $labelsJson;
const values = $valuesJson;
new Chart(ctx, {
    type: 'bar',
    data: {
        labels: labels,
        datasets: [{
            label: 'Tokens Saved',
            data: values,
            backgroundColor: 'rgba(16, 185, 129, 0.6)',
            borderColor: 'rgba(16, 185, 129, 1)',
            borderWidth: 1,
            borderRadius: 4
        }]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
            y: { beginAtZero: true, grid: { color: '#e9e9e9' } },
            x: { grid: { display: false } }
        }
    }
});
"@
} else {
    $chartScript = ""
}

# Escape raw output for HTML
$escapedRaw = $historyOut -replace '&','&amp;' -replace '<','&lt;' -replace '>','&gt;'

# Replace placeholders in template (literal replace to avoid regex pitfalls)
$html = $htmlTemplate
$html = $html.Replace('<!-- TOTAL_CARD -->', $totalCard)
$html = $html.Replace('<!-- DAILY_CARD -->', $dailyCard)
$html = $html.Replace('<!-- HISTORY_TABLE -->', $historyTable)
$html = $html.Replace('RAW_OUTPUT', $escapedRaw)
$html = $html.Replace('// CHART_SCRIPT', $chartScript + "`n" + $dailyChartScript)

# Write output file
$outFile = Join-Path $PSScriptRoot "rtk_gain_report.html"
$html | Out-File -FilePath $outFile -Encoding UTF8
Write-Host "Report saved to: $outFile" -ForegroundColor Green
Start-Process $outFile
# If you want to keep the window open for errors, uncomment:
# Read-Host "Press Enter to exit"
