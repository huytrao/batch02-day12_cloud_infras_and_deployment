#!/usr/bin/env python3
"""
Start the full RAG Personal Diary Chatbot Stack
1. FastAPI RAG Backend on port 8001
2. Streamlit UI on port 8000 (Exposed to public)
"""
import subprocess
import sys
import os
import time
from pathlib import Path

def check_requirements():
    """Check if required packages are installed."""
    required_packages = ['fastapi', 'uvicorn', 'streamlit']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ Missing packages: {', '.join(missing_packages)}")
        print(f"Install with: pip install {' '.join(missing_packages)}")
        return False
    
    return True

def setup_environment():
    """Setup environment and directories."""
    # Find project root (one folder up from app/)
    app_dir = Path(__file__).parent.absolute()
    project_root = app_dir.parent.absolute()
    
    # Ensure VectorDB directory exists at project root
    vector_db_dir = project_root / "VectorDB"
    vector_db_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Vector DB directory: {vector_db_dir}")
    
    # Ensure logs folder exists
    logs_dir = app_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # Ensure Streamlit databases directories exist
    db_dir = app_dir / "src" / "streamlit_app" / "backend"
    db_dir.mkdir(parents=True, exist_ok=True)
    
    auth_db_dir = app_dir / "src" / "streamlit_app" / "user_database"
    auth_db_dir.mkdir(parents=True, exist_ok=True)
    
    # Check for .env file
    env_file = project_root / ".env"
    if not env_file.exists():
        env_file = app_dir / ".env.local"
        
    if env_file.exists():
        print(f"✅ Environment file found: {env_file}")
    else:
        print("⚠️ Environment file not found. Make sure environment variables are set.")

def start_stack():
    """Start the full stack: backend + frontend."""
    if not check_requirements():
        sys.exit(1)
        
    setup_environment()
    
    app_dir = Path(__file__).parent.absolute()
    project_root = app_dir.parent.absolute()
    
    # Set PYTHONPATH to project root so imports like 'app.main' work
    os.environ["PYTHONPATH"] = str(project_root)
    
    print("🚀 Starting RAG FastAPI Backend on port 8001...")
    
    # Run FastAPI service in the background
    fastapi_process = subprocess.Popen([
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", "8001"
    ], cwd=str(project_root))
    
    print(f"🔄 RAG Service running in background (PID: {fastapi_process.pid})")
    
    # Wait for backend to start up
    time.sleep(3)
    
    print("🚀 Starting Streamlit UI on port 8000...")
    
    # Run Streamlit in the foreground (blocking)
    streamlit_path = app_dir / "src" / "streamlit_app" / "interface.py"
    
    try:
        streamlit_process = subprocess.Popen([
            sys.executable, "-m", "streamlit", "run",
            str(streamlit_path),
            "--server.port", "8000",
            "--server.address", "0.0.0.0",
            "--server.headless", "true"
        ], cwd=str(project_root))
        
        print(f"🔄 Streamlit UI running (PID: {streamlit_process.pid})")
        print("-" * 50)
        print("📍 Access Streamlit UI at: http://localhost:8000")
        print("📖 Access API Docs at: http://localhost:8001/docs")
        print("Press Ctrl+C to stop both services")
        print("-" * 50)
        
        # Keep running and monitor processes
        while True:
            # Check if either process exited
            if fastapi_process.poll() is not None:
                print("❌ FastAPI backend stopped unexpectedly!")
                streamlit_process.terminate()
                break
                
            if streamlit_process.poll() is not None:
                print("❌ Streamlit UI stopped unexpectedly!")
                fastapi_process.terminate()
                break
                
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nStopping services...")
        fastapi_process.terminate()
        streamlit_process.terminate()
        print("Both services stopped.")
        
    except Exception as e:
        print(f"❌ Error starting stack: {e}")
        fastapi_process.terminate()
        sys.exit(1)

if __name__ == "__main__":
    start_stack()