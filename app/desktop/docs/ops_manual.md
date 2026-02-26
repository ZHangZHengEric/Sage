# Sage Desktop Deployment & Operations Manual

This guide covers deployment strategies for system administrators.

## Silent Installation

### macOS
Use `installer` command line tool:
```bash
sudo installer -pkg Sage_Desktop.pkg -target /
```
Note: The `.dmg` usually contains the `.app`. For automated deployment, consider packaging the `.app` into a `.pkg` using `pkgbuild`.

### Windows
Use `msiexec` for silent installation:
```powershell
msiexec /i Sage_Desktop.msi /quiet /norestart
```

## Configuration via Group Policy (Windows) / Profiles (macOS)

Sage Desktop supports configuration via environment variables or a global config file.
The app looks for `sage_config.json` in:
-   **Windows**: `%ProgramData%\Sage\config.json`
-   **macOS**: `/Library/Application Support/Sage/config.json`

Example `config.json`:
```json
{
  "logLevel": "INFO",
  "disableUpdates": true,
  "proxy": "http://proxy.example.com:8080"
}
```

## Backup & Restore

### Backup Script (Example)
```bash
# macOS
cp -r ~/Library/Application\ Support/Sage/data /path/to/backup/
# Windows (PowerShell)
Copy-Item -Recurse $env:APPDATA\Sage\data D:\Backups\Sage
```

### Restore Script (Example)
```bash
# Stop the app first!
killall Sage
cp -r /path/to/backup/data ~/Library/Application\ Support/Sage/
```

## Log Management

Logs are rotated daily and kept for 7 days by default.
To change log level, set the `LOG_LEVEL` environment variable before launching, or use the `config.json` mentioned above.

## Security Considerations

-   **Data Encryption**: Ensure the user's disk is encrypted (FileVault / BitLocker).
-   **Network**: The app binds to `127.0.0.1` only. No firewall rules needed for inbound traffic.
-   **Updates**: To disable auto-updates, use the configuration file or block `api.github.com` (if using GitHub releases).
