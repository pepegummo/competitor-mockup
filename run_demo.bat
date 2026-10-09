@echo off
rem Open the app with the demo dataset (MC vs AP, KCE, Food Passion).
rem Works offline: results, sample questions and SET numbers are stored in demo/app.db
cd /d "%~dp0"
set CC_DATA_DIR=%~dp0demo
set CC_DEMO=1
set LLM_REPLAY=1
".venv\Scripts\python.exe" -m streamlit run app.py
