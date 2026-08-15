@echo off
rem ============================================================
rem  Audio Duck - Upload helper
rem  Pushes this project to https://github.com/AutumnIsPro/QYAudioDuck
rem ============================================================
cd /d "%~dp0"
title Audio Duck - Upload to GitHub

rem --- locate git: PATH first, then standard install locations ---
set "GIT=git"
git --version >nul 2>nul
if not errorlevel 1 goto :gitok
if exist "C:\Program Files\Git\cmd\git.exe" set "GIT=C:\Program Files\Git\cmd\git.exe"
if exist "C:\Program Files\Git\bin\git.exe" set "GIT=C:\Program Files\Git\bin\git.exe"
"%GIT%" --version >nul 2>nul
if errorlevel 1 goto :nogit
:gitok
echo Using git: %GIT%

rem --- init repo if needed ---
if not exist ".git" (
    echo [1/4] Initializing git repository...
    "%GIT%" init -b main
    "%GIT%" remote add origin https://github.com/AutumnIsPro/QYAudioDuck.git
) else (
    echo [1/4] Git repository found, updating remote...
    "%GIT%" remote set-url origin https://github.com/AutumnIsPro/QYAudioDuck.git
)

rem --- ensure identity: re-prompt until both are filled ---
:identity
"%GIT%" config user.name >nul 2>nul
if not errorlevel 1 goto :identity_ok
echo.
echo Please enter your GitHub identity - required for commit:
set /p GNAME=  GitHub username: 
set /p GEMAIL=  GitHub email: 
if "%GNAME%"=="" goto :identity
if "%GEMAIL%"=="" goto :identity
"%GIT%" config user.name "%GNAME%"
"%GIT%" config user.email "%GEMAIL%"
:identity_ok

echo [2/4] Adding files...
"%GIT%" add -A
echo [3/4] Committing...
"%GIT%" commit -m "Audio Duck v1.0.0 - Audio ducking assistant"
if errorlevel 1 goto :commitfail

echo [4/4] Pushing to GitHub...
"%GIT%" push -u origin main
if errorlevel 1 goto :pushfail

echo.
echo [DONE] Uploaded successfully! Check: https://github.com/AutumnIsPro/QYAudioDuck
pause
exit /b 0

:nogit
echo [ERROR] Git not found.
echo   Install Git: https://git-scm.com/download/win
echo   Or add to PATH: setx PATH "%%PATH%%;C:\Program Files\Git\cmd"
pause
exit /b 1

:commitfail
echo.
echo [ERROR] Commit failed. Please fix the problem above and run this script again.
pause
exit /b 1

:pushfail
echo.
echo [ERROR] Push failed.
echo   If a login window appeared, complete it and run this script again.
echo   If it asked for a password, use a Personal Access Token:
echo   https://github.com/settings/tokens  -^> Generate new token  -^> tick repo
pause
exit /b 1
