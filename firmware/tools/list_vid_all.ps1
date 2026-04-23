Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_0F0D' } |
  Select-Object Status, Class, FriendlyName, InstanceId | Format-Table -AutoSize
