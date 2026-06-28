@echo off
setlocal

REM Change directory to the location of this batch file (repo root)
cd /d %~dp0

set PYTHONPATH=%CD%
REM ====== Create venv if it doesn't exist ======
if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

REM ====== Activate venv ======
call .venv\Scripts\activate

REM ====== Install test dependencies ======
pip install -r requirements-test.txt

REM ====== Run tests with coverage ======
pytest --maxfail=2 --disable-warnings --cov=translator

REM ====== End ======
echo Tests finished.
pause