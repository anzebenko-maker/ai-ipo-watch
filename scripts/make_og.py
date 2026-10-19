#!/usr/bin/env python3
"""Render the default Open Graph image (1200x630) from the site name with headless Chrome.
Output: src/assets/og-default.png (copied to public/ by build.py)."""
import json, pathlib, subprocess, tempfile, shutil, html
ROOT = pathlib.Path(__file__).resolve().parent.parent
cfg = json.loads((ROOT / "site.config.json").read_text())
page = f"""<html><body style="margin:0;width:1200px;height:630px;background:linear-gradient(135deg,#0b1020 0%,#1e1b4b 60%,#312e81 100%);font-family:system-ui,Segoe UI,Roboto,Arial;color:#fff;display:flex;flex-direction:column;justify-content:center;padding:0 90px;box-sizing:border-box">
<div style="display:flex;align-items:center;gap:18px;font-size:34px;font-weight:800"><span style="width:26px;height:26px;border-radius:50%;background:linear-gradient(135deg,#06b6d4,#4f46e5);box-shadow:0 0 30px #06b6d4"></span>{html.escape(cfg['site_name'])}</div>
<div style="font-size:72px;font-weight:800;line-height:1.05;letter-spacing:-2px;margin-top:28px">AI IPOs, lock-ups &amp;<br>pre-IPO funds</div>
<div style="font-size:26px;color:#c7d2fe;margin-top:26px">Anthropic · OpenAI · DXYZ · VCX · RVI · ARKVX &mdash; with a Canadian angle 🇨🇦</div></body></html>"""
tmp = pathlib.Path(tempfile.mkdtemp()); (tmp / "og.html").write_text(page)
out = ROOT / "src" / "assets" / "og-default.png"
chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars", f"--screenshot={out}", "--window-size=1200,630", f"file://{tmp/'og.html'}"], check=True, capture_output=True)
print("wrote", out)
