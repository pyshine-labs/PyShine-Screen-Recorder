Add-Type -AssemblyName System.Drawing
$path = 'e:\PyShine-Screen-Recorder\docs\screenshot.png'
$img = [System.Drawing.Image]::FromFile($path)
Write-Output ("Dimensions: " + $img.Width + "x" + $img.Height)
$img.Dispose()
