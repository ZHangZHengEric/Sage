# Sage Desktop User Manual

## Installation

### macOS
1.  Download the `.dmg` file from the latest release.
2.  Open the `.dmg` file.
3.  Drag the **Sage Desktop** icon to the **Applications** folder.
4.  Launch **Sage Desktop** from Launchpad or Applications.
    *   *Note*: On first launch, you may see a security warning. Go to **System Settings > Privacy & Security** and click **Open Anyway**.

### Windows
1.  Download the `.msi` installer or `.exe` setup file.
2.  Run the installer and follow the on-screen instructions.
3.  Launch **Sage Desktop** from the Start Menu or Desktop shortcut.

## Usage Guide

### Initial Setup
Upon first launch, the application will initialize the local environment:
-   **Database**: Created at `~/Library/Application Support/Sage/data` (macOS) or `%AppData%\Sage\data` (Windows).
-   **Files**: Local storage directory initialized.
-   **Vector Store**: Local vector database initialized.

### Main Interface
The interface is identical to the web version but runs entirely on your machine.
-   **Chat**: Interact with intelligent agents.
-   **Knowledge Base**: Upload files (PDF, TXT, MD) for local processing.
    *   *Note*: Processing large files may take time depending on your computer's performance.

### Data Management
All your data is stored locally.
-   **Backup**: You can backup your data by copying the `data` directory mentioned above.
-   **Uninstall**:
    -   macOS: Drag the app to Trash. To remove data, delete `~/Library/Application Support/Sage`.
    -   Windows: Use "Add or Remove Programs". To remove data, delete `%AppData%\Sage`.

## Troubleshooting

### App won't start
-   Check if another instance is running.
-   Restart your computer.

### "Backend not ready" error
-   The Python background service might have failed to start.
-   Check logs:
    -   macOS: `~/Library/Logs/Sage Desktop/`
    -   Windows: `%AppData%\Sage\logs\`
