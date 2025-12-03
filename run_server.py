import uvicorn
import os

if __name__ == "__main__":
    # Ensure we're running from project root
    if not os.path.exists("config/strategy.yaml"):
        print("Warning: config/strategy.yaml not found in current directory")
    
    uvicorn.run("src.api_server:app", host="0.0.0.0", port=8000, reload=True)
