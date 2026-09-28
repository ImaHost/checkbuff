@echo off
cd /d "%~dp0"
py -3 -m pip install -q -r requirements.txt
start "" pyw -3 main.py
