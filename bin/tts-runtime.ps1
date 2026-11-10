<#
.SYNOPSIS
  tts-runtime 启动器（Windows）：不安装也能直接跑。

.EXAMPLE
  .\bin\tts-runtime.ps1 doctor --json
  .\bin\tts-runtime.ps1 synth --engine mock --text "你好" --out out\a.wav

.NOTES
  需要 Python 3.9+。可用 $env:ARK_TTS_RUNTIME_PYTHON 指定解释器路径。
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = if ($env:ARK_TTS_RUNTIME_PYTHON) { $env:ARK_TTS_RUNTIME_PYTHON } else { 'python' }

if (-not (Get-Command $python -ErrorAction SilentlyContinue)) {
    Write-Error "tts-runtime: 找不到 $python，请安装 Python 3.9+ 或设置 `$env:ARK_TTS_RUNTIME_PYTHON"
    exit 2
}

$env:PYTHONPATH = if ($env:PYTHONPATH) { "$root;$env:PYTHONPATH" } else { $root }
& $python -m tts_runtime @Arguments
exit $LASTEXITCODE
