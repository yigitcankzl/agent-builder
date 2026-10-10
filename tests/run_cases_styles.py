"""tools/run_cases.py with extra customer styles, without editing the kit file: the styles of a JSON file
(name -> paragraph) are added to run_cases.STYLES, then run_cases' own main runs. Same arguments as run_cases.
    python3 tests/run_cases_styles.py <styles.json> <agent_id> --cases <cases with a "style" key per case> --out ...
"""
import json, os, runpy, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tools")]
import tests._env  # noqa: F401
import run_cases

run_cases.STYLES.update(json.load(open(sys.argv.pop(1))))
sys.argv[0] = os.path.join(ROOT, "tools", "run_cases.py")
run_cases.main()
