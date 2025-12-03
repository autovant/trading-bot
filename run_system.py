import subprocess
import sys
import time
import os
import signal
from pathlib import Path

# Global process list for cleanup
processes = []

def signal_handler(sig, frame):
    print("\nShutting down services...")
    for p in processes:
        p.terminate()
    sys.exit(0)

def run_system():
    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    root_dir = Path(__file__).parent.absolute()
    
    print("🚀 Starting Trading Bot System...")
    
    # 1. Start Backend (FastAPI)
    print("📈 Starting Backend (FastAPI)...")
    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.presentation.api:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
        cwd=root_dir,
        env=os.environ.copy()
    )
    processes.append(backend)
    
    # 2. Start Frontend (Next.js)
    print("💻 Starting Frontend (Next.js)...")
    frontend_dir = root_dir / "frontend"
    
    # Use npm.cmd on Windows, npm on Unix
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    
    frontend = subprocess.Popen(
        [npm_cmd, "run", "dev"],
        cwd=frontend_dir,
        env=os.environ.copy()
    )
    processes.append(frontend)
    
    print("\n✅ System Running!")
    print("   Backend: http://localhost:8000")
    print("   Frontend: http://localhost:3000")
    print("\nPress Ctrl+C to stop all services.")
    
    # Keep main process alive
    try:
        while True:
            time.sleep(1)
            # Check if processes are still alive
            if backend.poll() is not None:
                print("Backend process ended unexpectedly.")
                break
            if frontend.poll() is not None:
                print("Frontend process ended unexpectedly.")
                break
    except KeyboardInterrupt:
        signal_handler(None, None)

if __name__ == "__main__":
    run_system()
