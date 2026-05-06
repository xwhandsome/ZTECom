param(
    [string]$PythonBaseUrl = "http://127.0.0.1:8000",
    [string]$JavaBaseUrl = "http://127.0.0.1:8080",
    [string]$ExpectedModelPath = "E:\app\llm_models\qwen2.5-1.5b-instruct-q5_k_m.gguf"
)

$ErrorActionPreference = "Stop"

function Invoke-Json {
    param(
        [string]$Method,
        [string]$Url,
        [object]$Body = $null
    )
    if ($Body -eq $null) {
        return Invoke-RestMethod -Method $Method -Uri $Url
    }
    $json = $Body | ConvertTo-Json -Depth 12
    return Invoke-RestMethod -Method $Method -Uri $Url -ContentType "application/json; charset=utf-8" -Body $json
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function U {
    param([string]$Text)
    return [System.Text.RegularExpressions.Regex]::Unescape($Text)
}

$pythonHealth = Invoke-Json -Method Get -Url "$PythonBaseUrl/api/health"
Assert-True ($pythonHealth.status -eq "ok") "Python health failed"
Assert-True ($pythonHealth.kb_chunks -gt 0) "Knowledge base is empty"
Assert-True ($pythonHealth.llm.model_path -eq $ExpectedModelPath) "Unexpected model path: $($pythonHealth.llm.model_path)"

$javaHealth = Invoke-Json -Method Get -Url "$JavaBaseUrl/showcase/api/health"
Assert-True ($javaHealth.status -eq "ok") "Java health proxy failed"

Invoke-Json -Method Post -Url "$JavaBaseUrl/showcase/api/reset" -Body @{ session_id = "demo" } | Out-Null

$created = Invoke-Json -Method Post -Url "$JavaBaseUrl/showcase/api/chat" -Body @{
    session_id = "demo"
    user_text = (U "\u660e\u65e97\u70b9\u63d0\u9192\u5976\u5976\u5403\u964d\u538b\u836f")
    mode = "health_assistant"
}
Assert-True ($created.intent -eq "create_reminder") "Create reminder intent failed"

$rag = Invoke-Json -Method Post -Url "$JavaBaseUrl/showcase/api/chat" -Body @{
    session_id = "demo"
    user_text = (U "\u8fd9\u4e2a\u836f\u996d\u524d\u8fd8\u662f\u996d\u540e\u5403")
    mode = "health_assistant"
}
Assert-True ($rag.knowledge_refs.Count -gt 0) "RAG references missing"

$short = Invoke-Json -Method Post -Url "$JavaBaseUrl/showcase/api/chat" -Body @{
    session_id = "demo"
    user_text = (U "\u8fd9\u4e2a\u836f\u996d\u524d\u8fd8\u662f\u996d\u540e\u5403")
    mode = "tool_short"
}
Assert-True ($short.knowledge_refs.Count -eq 0) "tool_short should not return RAG references"

$envRule = Invoke-Json -Method Post -Url "$JavaBaseUrl/showcase/api/chat" -Body @{
    session_id = "demo"
    user_text = (U "\u5982\u679c\u5367\u5ba4\u4f4e\u4e8e20\u5ea6\uff0c\u665a\u4e0a9\u70b9\u540e\u81ea\u52a8\u5f00\u7a7a\u8c03\u523024\u5ea6")
    mode = "health_assistant"
}
Assert-True (($envRule.tool_events | Where-Object { $_.tool_name -eq "control_device" }).Count -gt 0) "Environment linkage did not trigger control_device"

$pending = Invoke-Json -Method Post -Url "$JavaBaseUrl/showcase/api/chat" -Body @{
    session_id = "demo"
    user_text = (U "\u901a\u77e5\u6211\u513f\u5b50\u6211\u4eca\u665a\u4e0d\u8212\u670d")
    mode = "tool_short"
}
Assert-True ($pending.requires_confirmation -eq $true) "Notify should require confirmation"

$confirmed = Invoke-Json -Method Post -Url "$JavaBaseUrl/showcase/api/confirm" -Body @{
    session_id = "demo"
    action_id = $pending.pending_action.action_id
    approved = $true
    mode = "tool_short"
}
Assert-True (($confirmed.tool_events | Where-Object { $_.tool_name -eq "notify_family" }).Count -gt 0) "Notify confirmation did not execute"

Write-Host "Smoke test passed."
