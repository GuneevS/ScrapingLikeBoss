#!/usr/bin/env python3
"""
NWK Image Management System - Setup Validation
Checks if the system is properly configured after GitHub clone
"""

import os
import sys
import importlib.util
from pathlib import Path

def check_file_exists(filepath, description):
    """Check if a file exists"""
    if os.path.exists(filepath):
        print(f"   ✅ {description}: {filepath}")
        return True
    else:
        print(f"   ❌ {description}: {filepath} - MISSING")
        return False

def check_directory_exists(dirpath, description):
    """Check if a directory exists"""
    if os.path.exists(dirpath) and os.path.isdir(dirpath):
        print(f"   ✅ {description}: {dirpath}")
        return True
    else:
        print(f"   ❌ {description}: {dirpath} - MISSING")
        return False

def check_python_module(module_name):
    """Check if a Python module can be imported"""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec is not None:
            print(f"   ✅ Python module: {module_name}")
            return True
        else:
            print(f"   ❌ Python module: {module_name} - NOT FOUND")
            return False
    except ImportError:
        print(f"   ❌ Python module: {module_name} - IMPORT ERROR")
        return False

def check_env_variable(var_name):
    """Check if environment variable is set"""
    value = os.getenv(var_name)
    if value and value != f"your_{var_name.lower()}_here":
        print(f"   ✅ Environment variable: {var_name} = {value[:10]}...")
        return True
    else:
        print(f"   ❌ Environment variable: {var_name} - NOT SET OR DEFAULT")
        return False

def main():
    """Main validation function"""
    print("============================================================")
    print("🔍 NWK IMAGE MANAGEMENT SYSTEM - SETUP VALIDATION")
    print("============================================================")
    print()
    
    all_good = True
    
    # Check core files
    print("📁 CHECKING CORE FILES:")
    core_files = [
        ("app.py", "Main Flask application"),
        ("database.py", "Database module"),
        ("image_processor.py", "Image processor"),
        ("requirements.txt", "Python dependencies"),
        ("config.yaml", "Configuration file"),
        ("START.sh", "Startup script"),
        ("SETUP.sh", "Setup script")
    ]
    
    for filepath, description in core_files:
        if not check_file_exists(filepath, description):
            all_good = False
    
    print()
    
    # Check directories
    print("📂 CHECKING DIRECTORY STRUCTURE:")
    directories = [
        ("data", "Database directory"),
        ("output", "Output images directory"),
        ("output/approved", "Approved images"),
        ("output/pending", "Pending images"),
        ("output/declined", "Declined images"),
        ("exports", "Export files"),
        ("logs", "Log files"),
        ("uploads", "Upload directory"),
        ("static", "Static assets"),
        ("templates", "HTML templates"),
        ("src", "Source modules")
    ]
    
    for dirpath, description in directories:
        if not check_directory_exists(dirpath, description):
            all_good = False
    
    print()
    
    # Check configuration
    print("⚙️  CHECKING CONFIGURATION:")
    if not check_file_exists(".env", "Environment configuration"):
        print("   💡 Run SETUP.sh to create .env file")
        all_good = False
    else:
        # Load .env file
        try:
            from dotenv import load_dotenv
            load_dotenv()
            if not check_env_variable("SERP_API_KEY"):
                print("   💡 Edit .env file and add your SerpAPI key")
                all_good = False
        except ImportError:
            print("   ⚠️  python-dotenv not installed - cannot check environment variables")
    
    print()
    
    # Check Python dependencies
    print("🐍 CHECKING PYTHON DEPENDENCIES:")
    required_modules = [
        "flask",
        "pandas", 
        "openpyxl",
        "yaml",
        "PIL",
        "aiohttp",
        "sqlite3"
    ]
    
    for module in required_modules:
        if not check_python_module(module):
            all_good = False
    
    print()
    
    # Check optional AI dependencies
    print("🤖 CHECKING AI DEPENDENCIES:")
    ai_modules = [
        ("torch", "PyTorch for CLIP"),
        ("clip", "OpenAI CLIP model"),
        ("easyocr", "OCR text extraction")
    ]
    
    ai_available = True
    for module, description in ai_modules:
        if not check_python_module(module):
            print(f"   ⚠️  {description}: {module} - will be installed on first run")
            ai_available = False
    
    if ai_available:
        print("   ✅ All AI dependencies available")
    
    print()
    
    # Check database
    print("💾 CHECKING DATABASE:")
    if os.path.exists("data/products.db"):
        try:
            import sqlite3
            conn = sqlite3.connect("data/products.db")
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM products")
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            print(f"   ✅ Database initialized with {count} products")
        except Exception as e:
            print(f"   ⚠️  Database exists but has issues: {e}")
    else:
        print("   ❌ Database not initialized")
        print("   💡 Run SETUP.sh to initialize database")
        all_good = False
    
    print()
    
    # Final summary
    print("============================================================")
    if all_good:
        print("🎉 VALIDATION PASSED - SYSTEM READY!")
        print()
        print("🚀 NEXT STEPS:")
        print("1. Start the application: ./START.sh")
        print("2. Open browser: http://localhost:8847")
        print("3. Import Excel file with product data")
        print()
    else:
        print("⚠️  VALIDATION FAILED - SETUP REQUIRED")
        print()
        print("🔧 RECOMMENDED ACTIONS:")
        print("1. Run setup script: ./SETUP.sh")
        print("2. Install dependencies: pip install -r requirements.txt")
        print("3. Edit .env file with your API key")
        print("4. Re-run validation: python3 validate_setup.py")
        print()
    
    print("📚 For help, see README_GITHUB.md")
    print("============================================================")
    
    return 0 if all_good else 1

if __name__ == "__main__":
    sys.exit(main())
