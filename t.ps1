# Thin launcher so `t commit "fixed onnx flag"` works from any directory.
# Put this script's folder on PATH, or add to $PROFILE:
#   function t { & "D:\Personal Projects\personaltracker\t.ps1" @args }
python (Join-Path $PSScriptRoot 'tracker.py') @args
exit $LASTEXITCODE
