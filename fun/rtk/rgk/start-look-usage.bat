@echo off
chcp 65001 >nul
powershell -ExecutionPolicy Bypass -File "%~dp0rtk_gain_report.ps1"
pause