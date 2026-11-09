import os
if os.environ.get('BANDWIDTH_JOB'):
    import policy
    policy.install()
