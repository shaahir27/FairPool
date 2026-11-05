# Keeps the free Render web service and the free Supabase project from sleeping by
# requesting /health and /ready. Run it from a scheduled task; the cadence, the
# enable-on-public step and the removal command are in docs/navigation-performance.md.
param(
  [string]$BaseUrl = 'https://fairpool-api.onrender.com',
  [string]$LogFile = (Join-Path $env:TEMP 'fairpool-keep-warm.log')
)

$ErrorActionPreference = 'Stop'

foreach ($path in @('/health', '/ready')) {
  $uri = $BaseUrl + $path
  try {
    $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 90
    $result = 'HTTP {0}' -f [int]$response.StatusCode
  } catch {
    $result = 'FAILED {0}' -f $_.Exception.Message
  }
  '{0} {1} {2}' -f (Get-Date -Format 's'), $path, $result | Add-Content -Path $LogFile -Encoding utf8
}
