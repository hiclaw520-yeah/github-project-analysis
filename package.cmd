@echo off
rem Windows double-click entry. Cross-platform logic lives in scripts/package.py.
rem Unix: ./package.sh  or  python3 scripts/package.py
python "%~dp0scripts\package.py" %*
pause
exit /b %errorlevel%
