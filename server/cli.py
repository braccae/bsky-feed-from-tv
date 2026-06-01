import os
import subprocess
import sys
from dotenv import load_dotenv

def run_dev():
    try:
        subprocess.run(["flask", "run"], check=True)
    except KeyboardInterrupt:
        sys.exit(0)

def run_prod():
    load_dotenv(dotenv_path=".flaskenv")
    load_dotenv()
    
    host = os.environ.get("FLASK_RUN_HOST", "0.0.0.0")
    port = os.environ.get("FLASK_RUN_PORT", "8000")
    bind_address = f"{host}:{port}"
    
    try:
        subprocess.run(["gunicorn", "server.app:app", "--bind", bind_address], check=True)
    except KeyboardInterrupt:
        sys.exit(0)
