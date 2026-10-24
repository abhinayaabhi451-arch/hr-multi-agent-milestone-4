Step1 : Open Folder in VS code and Open terminal
Step2 : python -m venv venv
Step3 : .\venv\Scripts\Activate.ps1
Step4 : Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
Step5 : pip install -r requirements-dev.txt
Step6 : Update .env file with your gemini key
step6.1:uvicorn api.app:app_factory --factory --reload
Step6 : python -m pytest -q tests
step 7: run this project use this command (python main.py)
