@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0.."

set BRANCH=feature/encoder-backend
set MSGFILE=scripts\commit_message.txt

echo ==========================================================
echo  career-jikimi : branch + commit + push
echo  branch : %BRANCH%
echo ==========================================================
echo.

echo [1/6] Verifying .gitignore ...
git check-ignore -q backend/models/context_checker/model.safetensors
if errorlevel 1 (
  echo   FAIL - backend/models is NOT ignored.
  echo   The 300MB model would be staged and GitHub rejects files over 100MB.
  echo   Add "backend/models/" to .gitignore, then run again.
  exit /b 1
)
git check-ignore -q .env
if errorlevel 1 (
  echo   FAIL - .env is NOT ignored. Secrets would be committed.
  exit /b 1
)
echo   OK - model weights and .env are ignored.
echo.

echo [2/6] Un-tracking large paths if they were added before ...
git rm -r --cached --quiet backend/models 2>nul
git rm -r --cached --quiet benchmark_out 2>nul
echo   done.
echo.

echo [3/6] Creating branch ...
git rev-parse --verify --quiet %BRANCH% >nul
if errorlevel 1 (
  git switch -c %BRANCH%
) else (
  echo   branch exists - switching to it.
  git switch %BRANCH%
)
if errorlevel 1 (
  echo   FAIL - could not switch branch. Commit or stash your changes first.
  exit /b 1
)
echo.

echo [4/6] Staging ...
git add .gitignore .env.example deploy docker-compose.yml compose.nginx.yml
git add backend/app/core/config.py backend/app/judgment backend/app/main.py
git add backend/app/seed_demo.py backend/requirements-encoder.txt backend/tests/conftest.py
git add scripts/eval
git add training docs dataset

git diff --cached --name-only > "%TEMP%\cj_staged.txt"
findstr /i "safetensors" "%TEMP%\cj_staged.txt" >nul
if not errorlevel 1 (
  echo   FAIL - a .safetensors file is staged. Aborting before push.
  exit /b 1
)
echo   staged files:
git diff --cached --name-only
echo.

echo [5/6] Committing ...
if not exist "%MSGFILE%" (
  echo   FAIL - %MSGFILE% not found.
  exit /b 1
)
git commit -F "%MSGFILE%"
if errorlevel 1 (
  echo   Nothing to commit, or commit failed. Check output above.
  exit /b 1
)
echo.

echo [6/6] Pushing ...
git push -u origin %BRANCH%
if errorlevel 1 (
  echo   FAIL - push rejected. Common causes:
  echo     - no remote write access  ^(check: git remote -v^)
  echo     - a file over 100MB slipped in
  exit /b 1
)

echo.
echo ==========================================================
echo  Done. Branch pushed: %BRANCH%
echo  Open a PR:  gh pr create --fill --base main
echo ==========================================================
endlocal
