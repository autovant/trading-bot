import os
import sys
from streamlit.web import cli as stcli

def main():
    """Run the Streamlit dashboard."""
    dirname = os.path.dirname(__file__)
    app_path = os.path.join(dirname, "dashboard", "app.py")
    
    sys.argv = ["streamlit", "run", app_path]
    sys.exit(stcli.main())

if __name__ == "__main__":
    main()
