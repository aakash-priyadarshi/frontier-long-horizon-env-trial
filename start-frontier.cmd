@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_frontier.ps1" %*
set "FRONTIER_EXIT=%ERRORLEVEL%"

echo.
if not "%FRONTIER_EXIT%"=="0" (
  echo Frontier did not start successfully. Review the message above.
) else (
  echo Frontier is ready. This window can now be closed.
)
echo Press any key to close this window. The started services will keep running.
pause >nul
exit /b %FRONTIER_EXIT%
