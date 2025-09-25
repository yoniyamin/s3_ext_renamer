@echo off
echo Creating clean production environment...

REM Deactivate current environment
call deactivate 2>nul

REM Remove existing environment
rmdir /s /q .venv_clean 2>nul

REM Create new clean environment
python -m venv .venv_clean

REM Activate new environment
call .venv_clean\Scripts\activate

REM Install only production dependencies
pip install -r requirements.txt

echo.
echo ✅ Clean environment created!
echo 📁 Location: .venv_clean
echo 🚀 To use: call .venv_clean\Scripts\activate
