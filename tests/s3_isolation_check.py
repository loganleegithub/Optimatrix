"""Real local sandbox check using fake data only; zero model/service calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from researcher_cli import permission_overrides, clean_environment
from backtest import save_json


from researcher_cli import check_isolation

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    result = check_isolation(shutil.which('codex'))
    save_json(root/'local/s3-validation/isolation.json', result)
    print(json.dumps(result))
    raise SystemExit(0 if result['passed'] else 1)
