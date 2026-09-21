param([string]$Path = '.')
Get-ChildItem -Path $Path -File | Remove-Item -WhatIf
