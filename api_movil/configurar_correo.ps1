$ErrorActionPreference = 'Stop'
$rutaEnvCorreo = Join-Path $PSScriptRoot '.env'
Write-Host 'Configurar Gmail para enviar codigos de Cafeteria ITCA'
Write-Host 'Usa una contrasena de aplicacion de Google, no tu contrasena normal.'
Write-Host 'Guia: https://support.google.com/accounts/answer/185833?hl=es'
$cuentaCorreo = Read-Host 'Cuenta Gmail que enviara los codigos'
if ($cuentaCorreo -notmatch '^[^\s@=]+@[^\s@=]+\.[^\s@=]+$') { throw 'Correo no valido.' }
$claveCorreoSegura = Read-Host 'Contrasena de aplicacion (entrada oculta)' -AsSecureString
$punteroCorreo = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($claveCorreoSegura)
try {
    $claveCorreoTexto = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($punteroCorreo).Replace(' ', '')
    if ($claveCorreoTexto -notmatch '^[a-zA-Z0-9]{16}$') { throw 'Se esperaba una contrasena de aplicacion de 16 caracteres.' }
    $lineasCorreo = [IO.File]::ReadAllLines($rutaEnvCorreo) | Where-Object { $_ -notmatch '^SMTP_(USER|PASSWORD)=' }
    $lineasCorreo += 'SMTP_USER=' + $cuentaCorreo.Trim()
    $lineasCorreo += 'SMTP_PASSWORD=' + $claveCorreoTexto
    [IO.File]::WriteAllLines($rutaEnvCorreo, $lineasCorreo, (New-Object Text.UTF8Encoding($false)))
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($punteroCorreo)
    $claveCorreoTexto = $null
    $claveCorreoSegura.Dispose()
}
Write-Host 'Configuracion guardada. Comprobando acceso a Gmail sin enviar correos...'
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'verificar_correo.py')
Read-Host 'Pulsa Enter para cerrar'
