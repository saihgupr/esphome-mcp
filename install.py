#!/usr/bin/env python3
"""
ESPHome MCP Onboarding & Auto-Installer
Automatically sets up virtual environment, installs dependencies,
verifies ESPHome connection, and registers the server into your MCP client config.
"""

import sys
import os
import json
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
VENV_DIR = PROJECT_DIR / ".venv"
SERVER_PY = PROJECT_DIR / "server.py"
REQUIREMENTS_TXT = PROJECT_DIR / "requirements.txt"

CLIENT_CONFIG_PATHS = {
    "Antigravity IDE": Path.home() / ".gemini" / "config" / "mcp_config.json",
    "Claude Desktop": Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    "Cursor": Path.home() / ".cursor" / "mcp.json",
}

def print_step(msg):
    print(f"\n\033[1;34m==>\033[0m \033[1m{msg}\033[0m")

def print_success(msg):
    print(f"\033[1;32m[✓]\033[0m {msg}")

def print_warn(msg):
    print(f"\033[1;33m[!]\033[0m {msg}")

def print_error(msg):
    print(f"\033[1;31m[✗]\033[0m {msg}")

def setup_venv():
    print_step("Setting up Python Virtual Environment...")
    python_bin = sys.executable

    if not VENV_DIR.exists():
        print(f"Creating virtual environment in {VENV_DIR}...")
        subprocess.run([python_bin, "-m", "venv", str(VENV_DIR)], check=True)
        print_success("Virtual environment created.")
    else:
        print_success("Virtual environment already exists.")

    if sys.platform == "win32":
        venv_python = VENV_DIR / "Scripts" / "python.exe"
    else:
        venv_python = VENV_DIR / "bin" / "python"

    print("Installing dependencies from requirements.txt...")
    subprocess.run([str(venv_python), "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS_TXT)], check=True)
    print_success("Dependencies installed successfully.")

    return venv_python

def check_esphome_connection(host, port):
    print_step(f"Verifying ESPHome connection (http://{host}:{port}/devices)...")
    url = f"http://{host}:{port}/devices"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ESPHome-MCP-Installer"})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                print_success("Connected to ESPHome Dashboard successfully!")
                return True
    except Exception as e:
        print_warn(f"Could not connect to ESPHome at http://{host}:{port}/devices ({e})")
        print("    Don't worry! You can still complete installation. Just make sure ESPHome is running when using MCP.")
        return False

def update_mcp_config(config_path, client_name, venv_python, host, port):
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config_data = {"mcpServers": {}}
    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                config_data = json.load(f)
                if "mcpServers" not in config_data:
                    config_data["mcpServers"] = {}
        except Exception as e:
            print_warn(f"Failed to parse existing config at {config_path}: {e}")

    esphome_entry = {
        "command": str(venv_python),
        "args": [str(SERVER_PY)],
        "env": {
            "ESPHOME_HOST": host,
            "ESPHOME_PORT": str(port)
        },
        "disabled": False
    }

    config_data["mcpServers"]["esphome"] = esphome_entry

    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)

    print_success(f"Registered ESPHome MCP in {client_name} ({config_path})")

def main():
    print("\n" + "=" * 55)
    print("      🔧 ESPHome MCP Server - Automatic Setup 🔧")
    print("=" * 55)

    # 1. Interactive Inputs
    default_host = os.environ.get("ESPHOME_HOST", "192.168.1.4")
    default_port = os.environ.get("ESPHOME_PORT", "6052")

    if sys.stdin.isatty():
        host = input(f"\nEnter ESPHome IP address / hostname [{default_host}]: ").strip() or default_host
        port = input(f"Enter ESPHome Dashboard port [{default_port}]: ").strip() or default_port
    else:
        host = default_host
        port = default_port

    try:
        port = int(port)
    except ValueError:
        print_error("Invalid port number.")
        sys.exit(1)

    # 2. Connection Check
    check_esphome_connection(host, port)

    # 3. Setup Virtual Environment
    venv_python = setup_venv()

    # 4. Find & Register with Config Files
    print_step("Registering with MCP clients...")
    registered_any = False

    for client_name, config_path in CLIENT_CONFIG_PATHS.items():
        # Register if config file exists or parent directory exists
        if config_path.parent.exists():
            update_mcp_config(config_path, client_name, venv_python, host, str(port))
            registered_any = True

    if not registered_any:
        # Fallback: create default Antigravity IDE config
        fallback_path = CLIENT_CONFIG_PATHS["Antigravity IDE"]
        update_mcp_config(fallback_path, "Antigravity IDE", venv_python, host, str(port))

    print("\n" + "=" * 55)
    print(" 🎉 Setup Complete!")
    print(" Please fully RESTART your IDE or AI Client application")
    print(" (e.g. Quit & Relaunch Antigravity IDE / Claude Desktop)")
    print(" to begin using ESPHome MCP tools.")
    print("=" * 55 + "\n")

if __name__ == "__main__":
    main()
