$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "C:\Users\fengyutang\disk_treemap_analyzer"
python smoke_test_parallel_mft.py
Read-Host "Press Enter to exit"