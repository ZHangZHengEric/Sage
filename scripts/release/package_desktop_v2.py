"""Build platform installers from the Flutter release and embedded v2 runtime."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = '2.0.0'


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
        subprocess.run([sys.executable, str(ROOT / 'scripts/release/bundle_desktop_v2.py'),
            '--bundle', str(bundle), '--wheel', str(args.wheel.resolve()),
            '--version', VERSION, '--commit', args.commit], check=True)
        # Moving the whole tree exposes absolute interpreter/library references.
        relocated = Path(temp) / 'relocated location'
        stage.rename(relocated)
        bundle = relocated / bundle.name
        runtime = bundle / ('Contents/Resources/sage-runtime' if args.platform == 'macos' else 'sage-runtime')
        subprocess.run([sys.executable, str(ROOT / 'scripts/release/smoke_desktop_v2.py'), str(runtime)], check=True)
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
SetOutPath "$INSTDIR"
File /r "{bundle}\\*"
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
            subprocess.run([nsis, str(script)], check=True)
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
Depends: libgtk-3-0, libstdc++6, liblzma5, bubblewrap
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
