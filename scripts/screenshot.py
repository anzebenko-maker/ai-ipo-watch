#!/usr/bin/env python3
"""Full-page screenshot of the locally served site. Usage: python3 scripts/screenshot.py [url] [out.png] [width]"""
import sys, shutil
from playwright.sync_api import sync_playwright
url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080/"
out = sys.argv[2] if len(sys.argv) > 2 else "screenshot-home.png"
width = int(sys.argv[3]) if len(sys.argv) > 3 else 1280
exe = shutil.which("google-chrome") or shutil.which("chromium")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": width, "height": 900}, device_scale_factor=1)
    pg.goto(url, wait_until="networkidle")
    pg.screenshot(path=out, full_page=True)
    b.close()
print("saved", out)
