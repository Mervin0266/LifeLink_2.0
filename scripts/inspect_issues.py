import re
from pathlib import Path

out_lines = []

# 1. Inspect index.html
html = Path("frontend/index.html").read_text(encoding="utf-8")
out_lines.append("=== index.html ===")
for i, line in enumerate(html.splitlines()):
    if any(k in line.lower() for k in ["icon", "nav-item", "btn", "tab-btn"]):
        out_lines.append(f"{i+1}: {line.strip()}")

# 2. Inspect app.js
app_js = Path("frontend/js/app.js").read_text(encoding="utf-8")
out_lines.append("\n=== app.js icon usage ===")
for i, line in enumerate(app_js.splitlines()):
    if "icon" in line.lower() or "<svg" in line or "emoji" in line.lower():
        out_lines.append(f"{i+1}: {line.strip()[:120]}")

# 3. Inspect style.css
css = Path("frontend/css/style.css").read_text(encoding="utf-8")
out_lines.append("\n=== style.css icon rules ===")
for i, line in enumerate(css.splitlines()):
    if "icon" in line.lower():
        out_lines.append(f"{i+1}: {line.strip()}")

Path("scripts/inspect_icons.txt").write_text("\n".join(out_lines), encoding="utf-8")
print(f"Wrote {len(out_lines)} lines to scripts/inspect_icons.txt")
