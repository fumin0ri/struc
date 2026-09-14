"""Run meaningful tests and save the actual result plus test-source hashes."""
import sys
from pathlib import Path
from time import perf_counter
from datetime import datetime, timezone
import hashlib
import io
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.pipeline import write_json

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    log = io.StringIO()
    start = perf_counter()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    elapsed = perf_counter() - start
    write_json(ROOT / 'results/test_run.json', {
        'run_utc': datetime.now(timezone.utc).isoformat(), 'tests_run': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'success': result.wasSuccessful(), 'elapsed_seconds': elapsed,
        'independent_matcher_oracle_pairs': 100,
        'test_source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted((ROOT / 'tests').glob('*.py'))},
    })
    (ROOT / 'results/test_output.txt').write_text(log.getvalue(), encoding='utf-8')
    print(log.getvalue())
    raise SystemExit(0 if result.wasSuccessful() else 1)
