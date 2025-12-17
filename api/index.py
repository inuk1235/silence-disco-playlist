import sys
import os

# Add the api directory to Python path so 'app' module can be found
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app

# Vercel looks for a variable named 'app' or 'handler'
