@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: =======================
:: Config
:: =======================
set "PROXY_PORT=7890"
set "PROXY_HOST=127.0.0.1"

:: If you have a local proxy controller (like clash/mihomo/sing-box),
:: this script expects you to manage how to enable "proxy on/off".
:: It will set standard env vars for git/curl-like tools:
::   HTTP_PROXY / HTTPS_PROXY / ALL_PROXY
:: =======================

:: Automatically locate the Git root directory by searching for .git in current or parent directories
call :FindGitRoot "%~dp0"
if not defined GIT_ROOT (
    echo Git repository not found in current or parent directories.
    pause
    exit /b
)
cd /d "%GIT_ROOT%"

:MainMenu
cls
echo.
echo ================= Git Quick Actions Menu =================
echo Current Git project path: %GIT_ROOT%
echo.
echo 1. git pull
echo 2. git add .
echo 3. git commit (enter commit message)
echo 4. git push
echo 5. git status
echo 6. Exit
echo.
set /p "choice=Please select an option (1-6): "

if "%choice%"=="1" goto GitPull
if "%choice%"=="2" goto GitAdd
if "%choice%"=="3" goto GitCommit
if "%choice%"=="4" goto GitPush
if "%choice%"=="5" goto GitStatus
if "%choice%"=="6" goto ExitScript

echo Invalid option. Please try again.
timeout /t 2 /nobreak >nul
goto MainMenu

:: =======================
:: Git operations with fallback proxy
:: =======================

:GitPull
echo.
echo Running: git pull
call :RunGitWithProxyFallback git pull
echo.
pause
goto MainMenu

:GitAdd
echo.
echo Running: git add .
git add .
echo.
pause
goto MainMenu

:GitCommit
echo.
set /p "commit_msg=Enter commit message: "
if not defined commit_msg (
    echo Commit message cannot be empty.
    pause
    goto MainMenu
)
echo Running: git commit -m "%commit_msg%"
git commit -m "%commit_msg%"
echo.
pause
goto MainMenu

:GitPush
echo.
echo Running: git push
call :RunGitWithProxyFallback git push
echo.
pause
goto MainMenu

:GitStatus
echo.
echo Running: git status
git status
echo.
pause
goto MainMenu

:ExitScript
echo.
echo exit-ok
exit /b

:: =======================
:: Core: try without proxy, if fail then enable 7890 proxy and retry
:: =======================
:RunGitWithProxyFallback
:: %1.. = command line
:: Example: call :RunGitWithProxyFallback git pull
set "CMDLINE=%*"

echo [Stage 1] Attempt without proxy...
call :TryRunOnce "%CMDLINE%" NoProxy
set "RET1=!ERRORLEVEL!"

if "!RET1!"=="0" (
    exit /b 0
)

echo.
echo [Stage 2] Attempt with proxy on %PROXY_HOST%:%PROXY_PORT% ...
call :TryRunOnce "%CMDLINE%" Proxy7890
set "RET2=!ERRORLEVEL!"

if not "!RET2!"=="0" (
    echo.
    echo Both attempts failed. Return code: !RET2!
)

exit /b !RET2!

:TryRunOnce
:: %1 = command line (stored into variable by caller)
:: %2 = NoProxy or Proxy7890
set "CMDLINE=%~1"
set "MODE=%~2"

if /i "%MODE%"=="NoProxy" (
    set "HTTP_PROXY="
    set "HTTPS_PROXY="
    set "ALL_PROXY="
    set "NO_PROXY="
) else (
    set "HTTP_PROXY=http://%PROXY_HOST%:%PROXY_PORT%"
    set "HTTPS_PROXY=http://%PROXY_HOST%:%PROXY_PORT%"
    set "ALL_PROXY=http://%PROXY_HOST%:%PROXY_PORT%"
    set "NO_PROXY="
)

:: Execute without using "call %CMDLINE%" (to avoid breaking quoting).
:: We'll re-parse CMDLINE safely using cmd /c with delayed expansion disabled issues handled by quoting.
cmd /c "%CMDLINE%"

exit /b %ERRORLEVEL%

:: =======================
:: Find Git root helper
:: =======================
:FindGitRoot
set "dir=%~1"

:FindLoop
if exist "%dir%\.git" (
    set "GIT_ROOT=%dir%"
    exit /b
)

if "%dir:~1%"==":\" (
    set "GIT_ROOT="
    exit /b
)

for %%F in ("%dir%") do set "dir=%%~dpF"
set "dir=!dir:~0,-1!"
goto FindLoop