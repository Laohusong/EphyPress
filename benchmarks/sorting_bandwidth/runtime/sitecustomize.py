"""Install explicit benchmark hooks in spawned Windows workers; fail closed."""
import json
import os
import traceback
from pathlib import Path

if os.environ.get('BANDWIDTH_JOB'):
    try:
        job = json.loads(Path(os.environ['BANDWIDTH_JOB']).read_text(encoding='utf-8'))
        if job['sorter'] == 'chronosort':
            import policy
            policy.install()
        else:
            import bandwidth_adapter
            bandwidth_adapter.install()
        import io_budget
        io_budget.install()
    except Exception:
        traceback.print_exc()
        os._exit(86)
