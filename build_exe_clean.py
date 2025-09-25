"""
Clean Build Script for The Bucket Wizard
Creates executable using only production dependencies
"""
import subprocess
import sys
import os
from pathlib import Path

def run_command(command, description):
    """Run a command and handle output"""
    print(f"🔨 {description}")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        if e.stdout:
            print(f"Output: {e.stdout}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False

def main():
    print("📦 The Bucket Wizard - Clean Build Script")
    print("=" * 50)
    
    # Check if clean environment exists
    clean_env_path = Path(".venv_clean")
    if not clean_env_path.exists():
        print("❌ Clean environment not found!")
        print("📝 Run 'setup_clean_env.bat' first to create clean environment")
        return False
    
    # Check required files
    required_files = ["s3bucket_wizard.py", "requirements.txt", "wizard48p.ico"]
    required_dirs = ["templates", "static"]
    
    for file in required_files:
        if not os.path.exists(file):
            print(f"❌ Missing required file: {file}")
            return False
        print(f"✅ File found: {file}")
    
    for dir in required_dirs:
        if not os.path.exists(dir):
            print(f"❌ Missing required directory: {dir}")
            return False
        print(f"✅ Directory found: {dir}")
    
    # Activate clean environment and build
    activate_script = clean_env_path / "Scripts" / "activate.bat"
    
    # Build command using clean environment
    build_command = f"""
    call "{activate_script}" && ^
    python -m PyInstaller ^
        --onefile ^
        --windowed ^
        --name TheBucketWizard ^
        --distpath dist_fixed ^
        --workpath build_clean ^
        --clean ^
        --add-data "templates;templates" ^
        --add-data "static;static" ^
        --hidden-import webview ^
        --collect-all webview ^
        --icon static/wizard48p.ico ^
        s3bucket_wizard.py
    """
    
    print("🔨 Building executable with clean environment...")
    print("📋 Command:")
    print(build_command.strip())
    print()
    
    success = run_command(build_command, "Building with PyInstaller")
    
    if success:
        print("\n✅ Clean build completed successfully!")
        print("📁 Executable location: dist_clean/TheBucketWizard.exe")
        print("\n📊 This build should be much smaller and cleaner!")
        
        # Show file size comparison if regular build exists
        clean_exe = Path("dist_clean/TheBucketWizard.exe")
        regular_exe = Path("dist/TheBucketWizard.exe")
        
        if clean_exe.exists() and regular_exe.exists():
            clean_size = clean_exe.stat().st_size / (1024 * 1024)  # MB
            regular_size = regular_exe.stat().st_size / (1024 * 1024)  # MB
            print(f"\n📏 Size comparison:")
            print(f"   Clean build:   {clean_size:.1f} MB")
            print(f"   Regular build: {regular_size:.1f} MB")
            print(f"   Difference:    {regular_size - clean_size:.1f} MB ({((regular_size - clean_size) / regular_size * 100):.1f}% smaller)")
    else:
        print("\n❌ Build failed!")
        return False
    
    return True

if __name__ == "__main__":
    main()
