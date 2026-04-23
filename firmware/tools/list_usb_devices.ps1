# List PnP devices that may be the Leonardo / HORI gamepad
Get-PnpDevice -PresentOnly | Where-Object {
  $n = $_.FriendlyName
  $n -match 'Arduino|Leonardo|HORI|Pokken|0F0D|Game|controller|joystick|HID|USB.*Serial|Composite' 
} | Sort-Object FriendlyName | Format-Table Status, Class, FriendlyName -AutoSize
