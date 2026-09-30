#!/usr/bin/env python3
"""Build a self-contained arm64 macOS app without copying private archives."""
import os, plistlib, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('ARCHIVE_PYTHON_RUNTIME',str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python')))
APP=ROOT/'dist/聊天档案.app';CONTENTS=APP/'Contents';RES=CONTENTS/'Resources'
for directory in (CONTENTS/'MacOS',RES/'Engine',RES/'Python/bin'):directory.mkdir(parents=True,exist_ok=True)
subprocess.run(['swiftc','-module-cache-path','/tmp/claude-archive-module-cache','-swift-version','5','-O','-target','arm64-apple-macos15.0','-parse-as-library','-framework','SwiftUI','-framework','AppKit','-framework','WebKit',*[str(p) for p in sorted((ROOT/'Sources').glob('*.swift'))],'-o',str(CONTENTS/'MacOS/ClaudeArchive')],check=True)
for file in (ROOT/'Engine').glob('*.py'):shutil.copy2(file,RES/'Engine'/file.name)
shutil.copy2(RUNTIME/'bin/python3.12',RES/'Python/bin/python3.12')
shutil.copytree(RUNTIME/'lib/python3.12',RES/'Python/lib/python3.12',dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip','_tkinter*.so'))
for unused in (RES/'Python/lib/python3.12/lib-dynload').glob('_tkinter*.so'):unused.unlink()
# Generate every macOS icon resolution from the approved Figma export.
iconset=ROOT/'dist/AppIcon.iconset';iconset.mkdir(exist_ok=True)
for size in (16,32,128,256,512):
 for scale in (1,2):
  pixels=size*scale;suffix='@2x' if scale==2 else ''
  subprocess.run(['sips','-z',str(pixels),str(pixels),str(ROOT/'Design/app-icon-1024.png'),'--out',str(iconset/f'icon_{size}x{size}{suffix}.png')],check=True,capture_output=True)
subprocess.run(['iconutil','-c','icns',str(iconset),'-o',str(RES/'AppIcon.icns')],check=True)
with (CONTENTS/'Info.plist').open('wb') as f:plistlib.dump({'CFBundleName':'聊天档案','CFBundleDisplayName':'聊天档案','CFBundleIdentifier':'local.chatarchive.desktop','CFBundleExecutable':'ClaudeArchive','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.2.2','CFBundleVersion':'19','CFBundleIconFile':'AppIcon','LSMinimumSystemVersion':'15.0','NSHighResolutionCapable':True,'NSPrincipalClass':'NSApplication','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},'NSHumanReadableCopyright':'Local Chat Archive · Includes Python Software Foundation licensed CPython.'},f)
# Standalone runtime must have no Homebrew or user-directory dynamic dependencies.
for binary in [CONTENTS/'MacOS/ClaudeArchive',RES/'Python/bin/python3.12',*list((RES/'Python').rglob('*.so'))]:
 deps=subprocess.check_output(['otool','-L',str(binary)],text=True)
 if '/opt/homebrew/' in deps or '/Users/' in '\n'.join(deps.splitlines()[1:]):raise SystemExit('Nonportable dependency: '+str(binary))
 subprocess.run(['codesign','--force','--sign','-',str(binary)],check=True,capture_output=True)
subprocess.run(['codesign','--force','--deep','--sign','-',str(APP)],check=True)
print(APP)
if '--dmg' in sys.argv:
 staging=ROOT/'dist/installer';staging.mkdir(exist_ok=True)
 target=staging/APP.name
 if target.exists():shutil.rmtree(target)
 shutil.copytree(APP,target,symlinks=True)
 shortcut=staging/'Applications'
 if not shortcut.exists():shortcut.symlink_to('/Applications')
 (staging/'使用说明.txt').write_text('将聊天档案拖入 Applications。首次打开会检测环境，并由你选择聊天来源和备份位置。\n此构建采用本机临时签名，尚未进行 Developer ID 公证。其他 Mac 的 Gatekeeper 提示和实机兼容性需要单独验收。\n备份数据不包含在安装包中。\n',encoding='utf-8')
 subprocess.run(['hdiutil','create','-volname','聊天档案','-srcfolder',str(staging),'-ov','-format','UDZO',str(ROOT/'dist/聊天档案.dmg')],check=True)
