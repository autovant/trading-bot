This directory stores the Windows NATS Server binary used by scripts/deploy-local.ps1.

The deployment script automatically checks for `nats-server.exe` before startup:
1. If the executable exists here, it is reused.
2. If missing, the script downloads the latest Windows AMD64 release from the official NATS GitHub repository, extracts it, and copies `nats-server.exe` into this folder.
3. Any download or extraction failure is reported with guidance to manually place a binary in this location.

You can pre-populate this folder with a vetted `nats-server.exe` if outbound internet access is restricted. The script will leave the file untouched on subsequent runs.
