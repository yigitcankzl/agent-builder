"""Load env.sh (export KEY=VALUE lines) into os.environ before freya is imported. Values are never printed."""
import os

def load(path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "env.sh")):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                k, v = line[7:].split("=", 1)
                os.environ.setdefault(k.strip(), v.split("#")[0].strip().strip('"').strip("'"))

load()
