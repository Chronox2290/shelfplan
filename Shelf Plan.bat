@echo off
rem Double-click entry point. Opens the Shelf Plan window.
rem -WindowStyle Hidden keeps the console from flashing up behind it, and
rem -ExecutionPolicy Bypass avoids the "scripts are disabled" refusal on a
rem default Windows install without changing any machine-wide setting.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0launcher\ShelfPlan.ps1"
