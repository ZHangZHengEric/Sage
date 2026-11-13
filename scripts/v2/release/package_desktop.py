"""Build platform installers from the Flutter release and embedded v2 runtime."""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[3]
VERSION = '2.2.0'


def build_windows_installer(nsis: str, script: Path, bundle: Path) -> None:
    """Give NSIS a short source path even for deeply nested runtime assets."""
    drives = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in reversed("DEFGHIJKLMNOPQRSTUVWXYZ"):
        if not drives & (1 << (ord(letter) - ord("A"))):
            drive = f"{letter}:"
            break
    else:
        raise RuntimeError("No drive letter is available for Windows installer staging")
    subprocess.run(["subst.exe", drive, str(bundle)], check=True)
    try:
        subprocess.run(
            [nsis, f"/DSAGE_BUNDLE_DRIVE={drive}", str(script)],
            check=True,
        )
    finally:
        subprocess.run(["subst.exe", drive, "/D"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=['macos', 'windows', 'linux'], required=True)
    parser.add_argument('--arch', choices=['arm64', 'x86_64'], required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    build = ROOT / 'app/v2/desktop/build'
    if args.platform == 'macos':
        source = next((build / 'macos/Build/Products/Release').glob('*.app'))
    elif args.platform == 'windows':
        source = build / 'windows/x64/runner/Release'
    else:
        source = build / f'linux/{"arm64" if args.arch == "arm64" else "x64"}/release/bundle'
    name = f'Sage-{VERSION}-{args.platform}-{args.arch}'
    with tempfile.TemporaryDirectory(prefix='sage-v2-installer-') as temp:
        stage = Path(temp) / 'build-location'
        bundle = stage / ('Sage.app' if args.platform == 'macos' else 'Sage')
        shutil.copytree(source, bundle, symlinks=True)
        if args.platform == 'windows':
            for runtime_name in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
                if not (bundle / runtime_name).is_file():
                    raise RuntimeError(f'Windows bundle is missing its MSVC runtime: {runtime_name}')
        subprocess.run([sys.executable, str(ROOT / 'scripts/v2/release/bundle_desktop.py'),
            '--bundle', str(bundle), '--wheel', str(args.wheel.resolve()),
            '--version', VERSION, '--commit', args.commit], check=True)
        # Moving the whole tree exposes absolute interpreter/library references.
        relocated = Path(temp) / 'relocated location'
        stage.rename(relocated)
        bundle = relocated / bundle.name
        runtime = bundle / ('Contents/Resources/sage-runtime' if args.platform == 'macos' else 'sage-runtime')
        subprocess.run([sys.executable, str(ROOT / 'scripts/v2/release/smoke_desktop.py'), str(runtime)], check=True)
        if args.platform == 'macos':
            subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(bundle)], check=True)
            subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
            (relocated / 'Applications').symlink_to('/Applications')
            subprocess.run(['hdiutil', 'create', '-volname', f'Sage {VERSION}', '-srcfolder', str(relocated),
                '-ov', '-format', 'UDZO', str(output / f'{name}.dmg')], check=True)
        elif args.platform == 'windows':
            # NSIS is present on GitHub's Windows runner; fail if it is unavailable.
            nsis = shutil.which('makensis') or r'C:\Program Files (x86)\NSIS\makensis.exe'
            installer = output / f'{name}-setup.exe'
            script = Path(temp) / 'sage.nsi'
            bootstrapper = Path(temp) / 'MicrosoftEdgeWebview2Setup.exe'
            urlretrieve('https://go.microsoft.com/fwlink/p/?LinkId=2124703', bootstrapper)
            subprocess.run([
                'powershell', '-NoProfile', '-Command',
                '$signature = Get-AuthenticodeSignature -LiteralPath $env:SAGE_WEBVIEW_BOOTSTRAPPER; '
                'if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "CN=Microsoft Corporation") { exit 1 }',
            ], env={**os.environ, 'SAGE_WEBVIEW_BOOTSTRAPPER': str(bootstrapper)}, check=True)
            webview_runtime = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
            script.write_text(f'''Unicode True
Name "Sage {VERSION}"
OutFile "{installer}"
InstallDir "$LOCALAPPDATA\\Programs\\Sage"
RequestExecutionLevel user
!include "MUI2.nsh"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
Section
ReadRegStr $0 HKCU "Software\\Microsoft\\EdgeUpdate\\Clients\\{webview_runtime}" "pv"
StrCmp $0 "" webview_machine
StrCmp $0 "0.0.0.0" webview_machine webview_ready
webview_machine:
SetRegView 32
ReadRegStr $0 HKLM "Software\\Microsoft\\EdgeUpdate\\Clients\\{webview_runtime}" "pv"
StrCmp $0 "" webview_install
StrCmp $0 "0.0.0.0" webview_install webview_ready
webview_install:
InitPluginsDir
SetOutPath "$PLUGINSDIR"
File "{bootstrapper}"
ExecWait '\"$PLUGINSDIR\\MicrosoftEdgeWebview2Setup.exe\" /silent /install' $0
StrCmp $0 "0" webview_ready
MessageBox MB_ICONSTOP "Microsoft Edge WebView2 Runtime installation failed ($0)."
Abort
webview_ready:
SetRegView 32
SetOutPath "$INSTDIR"
File /r "${{SAGE_BUNDLE_DRIVE}}\\*"
WriteUninstaller "$INSTDIR\\Uninstall.exe"
CreateShortcut "$DESKTOP\\Sage.lnk" "$INSTDIR\\sage_desktop_v2.exe"
CreateShortcut "$SMPROGRAMS\\Sage.lnk" "$INSTDIR\\sage_desktop_v2.exe"
WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SageV2" "DisplayName" "Sage {VERSION}"
WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SageV2" "DisplayVersion" "{VERSION}"
WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SageV2" "UninstallString" '$"$INSTDIR\\Uninstall.exe$"'
SectionEnd
Section "Uninstall"
Delete "$DESKTOP\\Sage.lnk"
Delete "$SMPROGRAMS\\Sage.lnk"
RMDir /r "$INSTDIR"
DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SageV2"
SectionEnd
''')
            build_windows_installer(nsis, script, bundle)
        else:
            subprocess.run(['tar', '-czf', str(output / f'{name}.tar.gz'), '-C', str(relocated), 'Sage'], check=True)
            deb = Path(temp) / 'deb'
            app = deb / 'opt/sage'
            shutil.copytree(bundle, app, symlinks=True)
            (deb / 'DEBIAN').mkdir(parents=True)
            (deb / 'DEBIAN/control').write_text(f'''Package: sage-desktop-v2
Version: {VERSION}
Architecture: {"arm64" if args.arch == "arm64" else "amd64"}
Maintainer: Sage <noreply@github.com>
Depends: libgtk-3-0, libwebkit2gtk-4.1-0, libstdc++6, liblzma5, bubblewrap
Description: Sage Desktop v2 with its Python runtime
''')
            desktop = deb / 'usr/share/applications'
            desktop.mkdir(parents=True)
            (desktop / 'sage.desktop').write_text('''[Desktop Entry]
Type=Application
Name=Sage
Exec=/opt/sage/sage_desktop_v2
Icon=/opt/sage/data/flutter_assets/assets/brand/sage_logo.png
Categories=Development;
Terminal=false
''')
            subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(deb), str(output / f'{name}.deb')], check=True)
    print(f'Verified installer packages: {output}')


if __name__ == '__main__':
    main()
