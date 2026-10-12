@echo off
REM Run pixsort on your Downloads folder on Windows.
REM
REM 1. Install:   py -m pip install pixsort
REM 2. Schedule:  Task Scheduler -> Create Basic Task -> Daily ->
REM               Start a program -> pick this file.
REM
REM Tip: edit SOURCE below if your Downloads folder lives elsewhere.

setlocal

set "SOURCE=%USERPROFILE%\Downloads"
set "ARGS=--yes --quiet --min-gain 5"

echo -- pixsort: %SOURCE% --
pixsort "%SOURCE%" %ARGS%

endlocal
