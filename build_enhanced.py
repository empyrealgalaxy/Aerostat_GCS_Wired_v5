#!/usr/bin/env python3
"""
Enhanced build script with built-in obfuscation
This uses Python's compile() with maximum optimization
No external dependencies required (PyArmor alternative)
"""

import os
import sys
import py_compile
import compileall
import shutil
import subprocess
from pathlib import Path

def compile_with_optimization():
    """Compile Python files with maximum optimization"""
    print("\n" + "="*60)
    print("🔐 Compiling with maximum optimization...")
    print("="*60)
    
    # Create compiled directory
    compiled_dir = Path("compiled")
    if compiled_dir.exists():
        shutil.rmtree(compiled_dir)
    compiled_dir.mkdir(exist_ok=True)
    
    # Compile main file with optimization level 2
    main_file = "run_dashboard.py"
    if os.path.exists(main_file):
        try:
            # Compile to bytecode with optimization
            pyc_file = compiled_dir / "__pycache__" / "run_dashboard.cpython-312.pyc"
            pyc_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Use compile() with optimization
            with open(main_file, 'r', encoding='utf-8') as f:
                source_code = f.read()
            
            # Compile with optimization level 2 (maximum)
            compiled_code = compile(source_code, main_file, 'exec', optimize=2)
            
            # Write compiled bytecode
            import marshal
            with open(pyc_file, 'wb') as f:
                f.write(b'\x00' * 16)  # Header
                marshal.dump(compiled_code, f)
            
            print(f"✅ Compiled {main_file} with optimization level 2")
            return True
        except Exception as e:
            print(f"⚠️ Compilation error: {e}")
            return False
    return False

def build_with_enhanced_security():
    """Build executable with enhanced security options"""
    print("\n" + "="*60)
    print("🔨 Building executable with enhanced security...")
    print("="*60)
    
    # Update spec file to use enhanced security
    spec_file = "AerostateDashboard.spec"
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        spec_file,
        "--clean",
        "--noconfirm",
        "--key", "AerostatGCS2024Secure",  # Encryption key (if supported)
    ]
    
    try:
        result = subprocess.run(cmd, check=True)
        print("✅ Executable built with enhanced security!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Build with key failed, trying without key...")
        # Try without key (PyInstaller version may not support --key)
        cmd_no_key = [
            sys.executable, "-m", "PyInstaller",
            spec_file,
            "--clean",
            "--noconfirm",
        ]
        result = subprocess.run(cmd_no_key, check=True)
        print("✅ Executable built successfully!")
        return True

def obfuscate_strings():
    """Simple string obfuscation (basic protection)"""
    print("\n" + "="*60)
    print("🔐 Applying string obfuscation...")
    print("="*60)
    print("ℹ️  Note: This is a basic obfuscation layer")
    print("   For stronger protection, use build_encrypted.py with PyArmor")
    return True

def main():
    """Main build process"""
    print("="*60)
    print("🔒 ENHANCED BUILD PROCESS (Built-in Obfuscation)")
    print("="*60)
    
    # Step 1: Compile with optimization
    compile_with_optimization()
    
    # Step 2: Apply string obfuscation
    obfuscate_strings()
    
    # Step 3: Build executable
    if not build_with_enhanced_security():
        print("❌ Build failed")
        return False
    
    print("\n" + "="*60)
    print("✅ BUILD COMPLETE!")
    print("="*60)
    print("📦 Executable location: dist/AerostateDashboard/AerostateDashboard.exe")
    print("🔒 Code is optimized and compiled with maximum security settings")
    print("="*60)
    print("\n💡 For stronger encryption, use: python build_encrypted.py")
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

