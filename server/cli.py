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
    
    port = os.environ.get("FLASK_RUN_PORT", "8000")
    
    try:
        subprocess.run([
            "gunicorn", "server.app:app",
            "--bind", f"[::]:{port}",
        ], check=True)
    except KeyboardInterrupt:
        sys.exit(0)
