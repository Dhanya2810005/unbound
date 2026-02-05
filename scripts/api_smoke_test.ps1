$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$baseUrl = 'http://127.0.0.1:8000'

$listenPid = (Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -First 1 -ExpandProperty OwningProcess)
"LISTEN_PID=$listenPid"
if ($listenPid) {
  Get-Process -Id $listenPid | Select-Object Id, ProcessName, Path | Format-List | Out-String
}

"HEALTH:"
try {
  (Invoke-RestMethod -Uri "$baseUrl/health" -TimeoutSec 5) | ConvertTo-Json -Depth 10
} catch {
  "HEALTH_ERROR: $($_.Exception.Message)"
  exit 2
}

$wf = @{
  name = 'api-smoke'
  description = 'smoke test'
  steps = @(
    @{
      name = 'step0'
      order = 0
      model = 'kimi-k2-instruct-0905'
      prompt = 'Say hello world (must include the word hello)'
      system_prompt = $null
      validations = @(
        @{ type = 'contains'; expected = 'hello' }
      )
      max_retries = 0
    }
  )
}

"CREATE_WORKFLOW:"
$created = Invoke-RestMethod -Method Post -Uri "$baseUrl/workflows" -ContentType 'application/json' -Body ($wf | ConvertTo-Json -Depth 20) -TimeoutSec 20
$created | ConvertTo-Json -Depth 20

"START_RUN:"
$runReq = @{ initial_context = '' }
$run = Invoke-RestMethod -Method Post -Uri ("$baseUrl/workflows/{0}/run" -f $created.id) -ContentType 'application/json' -Body ($runReq | ConvertTo-Json -Depth 10) -TimeoutSec 20
$run | ConvertTo-Json -Depth 20

Start-Sleep -Seconds 2

"RUN_STATUS_POLL:"
$deadline = (Get-Date).AddSeconds(60)
do {
  $status = Invoke-RestMethod -Method Get -Uri ("$baseUrl/runs/{0}" -f $run.run_id) -TimeoutSec 20
  "status=" + $status.status + " started_at=" + $status.started_at + " finished_at=" + $status.finished_at
  if ($status.status -in @('completed','failed')) { break }
  Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

"RUN_STATUS_FINAL_JSON:"
$status | ConvertTo-Json -Depth 20
