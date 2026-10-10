@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Doppelklick = Auswahldialog | PDFs oder Ordner auf diese Datei ziehen = direkt konvertieren
python pdf2md.py %*
echo.
pause
