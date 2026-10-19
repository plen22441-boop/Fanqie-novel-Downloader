@echo off
chcp 65001 >nul
title Novel Downloader
pip install -q requests beautifulsoup4 lxml
echo.
set /p URL=Paste chapter 1 link here and press Enter: 
python download_chain.py "%URL%" --delay 1
echo.
echo Done. Open the "downloads" folder to find your .txt file.
pause
