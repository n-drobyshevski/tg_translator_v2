@echo off
setlocal

REM Change directory to the location of this batch file (repo root)
cd /d %~dp0

set PYTHONPATH=%CD%

REM ====== Prefer uv: installs the exact set in uv.lock, no resolution step ======
where uv >nul 2>nul
if %ERRORLEVEL% NEQ 0 goto :pip

REM --frozen = use uv.lock as-is and fail rather than silently re-resolving,
REM so a run here can never quietly disagree with what the server installs.
uv sync --frozen
if %ERRORLEVEL% NEQ 0 goto :failed
uv run --frozen pytest --maxfail=2 --disable-warnings --cov=translator
goto :done

:pip
REM ====== Fallback: requirements-test.txt is generated from uv.lock, so this
REM installs the same versions — just without the lock being enforced.
echo uv not found, falling back to pip. Install it for exact, faster installs:
echo     pip install uv
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements-test.txt
pytest --maxfail=2 --disable-warnings --cov=translator
goto :done

:failed
echo.
echo uv sync failed. If it complains the lockfile is out of date, run: uv lock

:done
echo Tests finished.
pause
