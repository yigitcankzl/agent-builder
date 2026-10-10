"""Run tools/run_cases.py with env.sh loaded:  python3 tests/run_cases_env.py <agent_id> [run_cases args]"""
import os, runpy, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests._env  # noqa: F401
sys.argv = [os.path.join(ROOT, "tools", "run_cases.py")] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
