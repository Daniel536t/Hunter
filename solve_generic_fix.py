import pathlib
f = pathlib.Path.home() / "hunter" / "solve.py"
code = f.read_text()

# Increase max_tokens for generic hunt
old = "temp=0.3, max_tokens=4096"
new = "temp=0.3, max_tokens=8192"
if old in code: code = code.replace(old, new); f.write_text(code); print("Increased max_tokens to 8192")
else: print("Not found")
