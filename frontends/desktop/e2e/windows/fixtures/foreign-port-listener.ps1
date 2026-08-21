param(
    [int]$Port = 14168,
    [string]$ReadyFile = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse("127.0.0.1"), $Port)
$listener.Start()

if ($ReadyFile) {
    $dir = Split-Path -Parent $ReadyFile
    if ($dir) {
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
    }
    [System.IO.File]::WriteAllText($ReadyFile, "ready", [System.Text.Encoding]::ASCII)
}

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            $stream = $client.GetStream()
            $body = "foreign listener"
            $response = "HTTP/1.1 404 Not Found`r`nContent-Type: text/plain`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n$body"
            $bytes = [System.Text.Encoding]::ASCII.GetBytes($response)
            $stream.Write($bytes, 0, $bytes.Length)
        } finally {
            $client.Close()
        }
    }
} finally {
    $listener.Stop()
}
