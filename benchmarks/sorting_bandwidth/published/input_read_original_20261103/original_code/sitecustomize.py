import os
if os.environ.get('BANDWIDTH_JOB'):
    from bandwidth_adapter import install
    install()
