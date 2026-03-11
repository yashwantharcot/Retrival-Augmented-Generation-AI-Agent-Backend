import sys
import os

# Add the current directory to sys.path
sys.path.append(os.getcwd())

try:
    from app.api.routes import router
    print("SUCCESS: app.api.routes imported successfully")
except Exception as e:
    import traceback
    print("FAILURE: app.api.routes failed to import")
    traceback.print_exc()
