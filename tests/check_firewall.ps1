Get-NetFirewallRule -Direction Inbound -Action Allow |
    Where-Object { $_.DisplayName -match 'NDI|ndi|python|ffmpeg|Python' } |
    Select-Object DisplayName, Profile, Enabled |
    Format-Table -AutoSize
