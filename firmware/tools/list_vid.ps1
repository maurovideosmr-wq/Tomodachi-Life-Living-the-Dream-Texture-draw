Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_0F0D|VID_2341|VID_2A03' } |
  Select-Object Status, Class, FriendlyName, InstanceId | Format-List
