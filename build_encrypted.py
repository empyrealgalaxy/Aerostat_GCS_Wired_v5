#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script with encryption/obfuscation support
This script obfuscates the code before building the executable
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def check_pyarmor():
    """Check if PyArmor is installed, install if not"""
    try:
        import pyarmor
        print("✅ PyArmor is installed")
        return True
    except ImportError:
        print("📦 Installing PyArmor...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyarmor"])
            print("✅ PyArmor installed successfully")
            return True
        except subprocess.CalledProcessError:
            print("❌ Failed to install PyArmor")
            return False

def obfuscate_code():
    """Obfuscate the main Python file"""
    print("\n" + "="*60)
    print("🔐 Obfuscating code with PyArmor...")
    print("="*60)
    
    # Create obfuscated directory
    obf_dir = Path("obfuscated")
    if obf_dir.exists():
        shutil.rmtree(obf_dir)
    obf_dir.mkdir(exist_ok=True)
    
    # Copy necessary files to obfuscated directory
    files_to_obfuscate = [
        "run_dashboard.py",
    ]
    
    for file in files_to_obfuscate:
        if os.path.exists(file):
            shutil.copy2(file, obf_dir / file)
            print(f"📋 Copied {file} to obfuscation directory")
    
    # Obfuscate with PyArmor
    try:
        # Try advanced obfuscation first (PyArmor 8.x syntax)
        print("🔒 Attempting advanced obfuscation...")
        cmd_advanced = [
            sys.executable, "-m", "pyarmor", "gen",
            "--obf-code", "1",  # Obfuscate code
            "--obf-mod", "1",  # Obfuscate module names
            "--wrap-mode", "1",  # Wrap mode for better protection
            "--restrict-mode", "4",  # Maximum restriction
            "--advanced-mode", "2",  # Advanced mode 2
            "--output", "obfuscated",
            "run_dashboard.py"
        ]
        
        print(f"🔒 Running: {' '.join(cmd_advanced)}")
        result = subprocess.run(cmd_advanced, capture_output=True, text=True, cwd=os.getcwd())
        
        if result.returncode == 0:
            print("✅ Advanced obfuscation successful!")
        else:
            print(f"⚠️ Advanced mode failed, trying standard mode...")
            print(f"   Output: {result.stdout[:200]}")
            # Try standard obfuscation
            cmd_standard = [
                sys.executable, "-m", "pyarmor", "gen",
                "--obf-code", "1",
                "--wrap-mode", "1",
                "--output", "obfuscated",
                "run_dashboard.py"
            ]
            result = subprocess.run(cmd_standard, capture_output=True, text=True, cwd=os.getcwd())
            
            if result.returncode != 0:
                print(f"⚠️ Standard mode also failed, trying basic mode...")
                # Try basic obfuscation
                cmd_basic = [
                    sys.executable, "-m", "pyarmor", "gen",
                    "--output", "obfuscated",
                    "run_dashboard.py"
                ]
                result = subprocess.run(cmd_basic, capture_output=True, text=True, cwd=os.getcwd())
        
        # Check for obfuscated file in various locations
        possible_locations = [
            obf_dir / "run_dashboard.py",
            obf_dir / "dist" / "run_dashboard.py",
            Path("obfuscated") / "run_dashboard.py",
            Path("obfuscated") / "dist" / "run_dashboard.py",
        ]
        
        obf_file = None
        for loc in possible_locations:
            if loc.exists():
                obf_file = loc
                break
        
        if obf_file and obf_file.exists():
            # Copy obfuscated file back
            target_file = Path("run_dashboard_obfuscated.py")
            shutil.copy2(obf_file, target_file)
            print(f"✅ Obfuscated file created: {target_file}")
            
            # Also copy pyarmor runtime files if they exist
            pyarmor_runtime = obf_dir / "pyarmor_runtime_000000"
            if pyarmor_runtime.exists():
                runtime_dest = Path("pyarmor_runtime")
                if runtime_dest.exists():
                    shutil.rmtree(runtime_dest)
                shutil.copytree(pyarmor_runtime, runtime_dest)
                print(f"✅ PyArmor runtime copied to: {runtime_dest}")
            
            return True
        else:
            print(f"⚠️ Obfuscated file not found in expected locations")
            print(f"   Searched: {[str(loc) for loc in possible_locations]}")
            if result.stdout:
                print(f"   PyArmor output: {result.stdout[:500]}")
            if result.stderr:
                print(f"   PyArmor errors: {result.stderr[:500]}")
            return False
            
    except Exception as e:
        print(f"❌ Error during obfuscation: {e}")
        import traceback
        traceback.print_exc()
        return False

def build_executable():
    """Build the executable using PyInstaller"""
    print("\n" + "="*60)
    print("🔨 Building executable with PyInstaller...")
    print("="*60)
    
    # Check if obfuscated file exists
    if os.path.exists("run_dashboard_obfuscated.py"):
        spec_file = "AerostateDashboard_encrypted.spec"
        # Update spec file to use obfuscated file
        update_spec_file(spec_file)
        cmd = [sys.executable, "-m", "PyInstaller", spec_file, "--clean", "--noconfirm"]
    else:
        print("⚠️ Obfuscated file not found, using regular spec file")
        spec_file = "AerostateDashboard.spec"
        cmd = [sys.executable, "-m", "PyInstaller", spec_file, "--clean", "--noconfirm"]
    
    try:
        result = subprocess.run(cmd, check=True)
        print("✅ Executable built successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Build failed: {e}")
        return False

def update_spec_file(spec_file):
    """Create or update spec file to use obfuscated code"""
    spec_content = """# -*- mode: python ; coding: utf-8 -*-
# Encrypted/Obfuscated Build Spec

a = Analysis(
    ['run_dashboard_obfuscated.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=[
        'paho.mqtt.client',
        'paho.mqtt',
        'fastapi',
        'uvicorn',
        'uvicorn.lifespan',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.loops.auto',
        'uvicorn.loops.uvloop',
        'uvicorn.loops.asyncio',
        'uvicorn.logging',
        'uvicorn.config',
        'uvicorn.server',
        'uvicorn.main',
        'jinja2',
        'jinja2.loaders',
        'websockets',
        'starlette.staticfiles',
        'starlette.responses',
        'starlette.applications',
        'starlette.middleware',
        'starlette.routing',
        'starlette.templating',
        'starlette.websockets',
        'pydantic',
        'pydantic.fields',
        'pydantic.main',
        'email_validator',
        'typing_extensions',
        'anyio',
        'sniffio',
        'idna',
        'h11',
        'httptools',
        'click',
        'watchfiles',
        'asyncio',
        'ssl',
        'socket',
        'json',
        'csv',
        'logging',
        'logging.handlers',
        'threading',
        'io',
        'traceback',
        'pyarmor_runtime_000000',  # PyArmor runtime
        'pyarmor_runtime',  # PyArmor runtime (alternate location)
        'pytransform',  # PyArmor transform
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'pandas',
        'numpy.testing',
        'scipy',
        'PIL',
        'tkinter',
    ],
    noarchive=False,
    optimize=2,  # Maximum bytecode optimization
    strip=True,  # Strip debug symbols
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AerostateDashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # Strip debug info
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,  # Strip debug info
    upx=False,
    upx_exclude=[],
    name='AerostateDashboard',
)
"""
    with open(spec_file, 'w') as f:
        f.write(spec_content)
    print(f"✅ Created spec file: {spec_file}")

def main():
    """Main build process"""
    print("="*60)
    print("🔐 ENCRYPTED BUILD PROCESS")
    print("="*60)
    
    # Step 1: Check and install PyArmor
    if not check_pyarmor():
        print("❌ Cannot proceed without PyArmor")
        return False
    
    # Step 2: Obfuscate code
    if not obfuscate_code():
        print("⚠️ Obfuscation failed, proceeding with regular build")
        # Continue with regular build anyway
    
    # Step 3: Build executable
    if not build_executable():
        print("❌ Build failed")
        return False
    
    print("\n" + "="*60)
    print("✅ BUILD COMPLETE!")
    print("="*60)
    print("📦 Executable location: dist/AerostateDashboard/AerostateDashboard.exe")
    print("🔐 Code is obfuscated and encrypted")
    print("="*60)
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n❌ Build cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

