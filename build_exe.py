#!/usr/bin/env python3
"""
Build script for The Bucket Wizard
Creates a standalone executable using PyInstaller
"""

import os
import sys
import subprocess

def check_icon():
    """Check if the wizard48p.ico file exists"""
    if os.path.exists("wizard48p.ico"):
        print("✅ Icon found: wizard48p.ico")
        return True
    else:
        print("⚠️  Icon not found: wizard48p.ico")
        print("ℹ️  Please ensure wizard48p.ico is in the current directory")
        return False

def check_directories():
    """Check if required directories exist"""
    directories = ['templates', 'static']
    missing = []
    
    for directory in directories:
        if os.path.exists(directory):
            print(f"✅ Directory found: {directory}")
        else:
            print(f"❌ Directory missing: {directory}")
            missing.append(directory)
    
    return missing

def install_dependencies():
    """Install required dependencies"""
    print("📦 Installing/updating dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Dependencies installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def build_executable():
    """Build the executable using PyInstaller"""
    
    # Check if PyInstaller is available
    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
    
    # Check for icon file
    has_icon = check_icon()
    
    # Check for required directories
    missing_dirs = check_directories()
    if missing_dirs:
        print(f"❌ Missing required directories: {', '.join(missing_dirs)}")
        print("Please ensure templates and static directories exist.")
        return False
    
    # PyInstaller command
    cmd = [
        sys.executable, "-m", "PyInstaller", # Use python module to avoid PATH issues
        "--onefile",                    # Create a single executable file
        "--windowed",                   # Hide the console window
        "--name", "TheBucketWizard", # Name of the executable
        "--distpath", "dist",           # Output directory
        "--workpath", "build",          # Temporary build directory
        "--clean",                      # Clean build directory before building
        "--add-data", "templates;templates", # Bundle templates
        "--add-data", "static;static",       # Bundle static files
        "--hidden-import", "webview",        # Ensure webview is included
        "--collect-all", "webview",          # Collect all webview files
    ]
    
    # Add icon if available
    if has_icon:
        cmd.extend(["--icon", "static/wizard48p.ico"])
    
    # Add the main script
    cmd.append("s3bucket_wizard.py")
    
    print("🔨 Building executable with command:")
    print(" ".join(cmd))
    print()
    
    try:
        subprocess.check_call(cmd)
        print("\n✅ Build completed successfully!")
        print("📁 Executable location: dist/TheBucketWizard.exe")
        print("\n📋 To distribute, simply copy the .exe file.")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Build failed with error: {e}")
        return False
    
    return True

if __name__ == "__main__":
    print("📦 The Bucket Wizard - Build Script")
    print("=" * 50)
    
    if not os.path.exists("s3bucket_wizard.py"):
        print("❌ s3bucket_wizard.py not found in current directory")
        sys.exit(1)
    
    # Install dependencies first
    if not install_dependencies():
        sys.exit(1)
    
    success = build_executable()
    
    if success:
        print("\n🎉 Build process completed!")
        print("\n💡 Usage instructions:")
        print("   1. Run the dist/TheBucketWizard.exe file.")
        print("   2. A desktop window will open with the application interface.")
        print("   3. The application will automatically find an available port.")
        print("   4. Close the window to stop the application.")
    else:
        print("\n❌ Build process failed")
        sys.exit(1) 