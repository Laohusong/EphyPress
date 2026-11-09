"""Reproduce KS4's strided initialization reads at the failed bandwidth."""
import json,os,subprocess,sys,time
from pathlib import Path
from experiment import ROOT,PYTHON,job_for,save,environment
if not os.environ.get('BANDWIDTH_JOB'):
    from bandwidth_adapter import initialize
    job=job_for('validation','compressed',100,'crc_strided_100MBps')
    request=ROOT/(job['name']+'.job.json');save(request,job);initialize(job)
    subprocess.run([str(PYTHON),'-u',str(Path(__file__).resolve())],env=environment(request),check=True)
else:
    import numpy as np
    import ephypress as ep
    from bandwidth_adapter import metrics
    job=json.loads(Path(os.environ['BANDWIDTH_JOB']).read_text())
    reference=np.memmap(job['raw'],mode='r',dtype='<i2',shape=(54000000,384))
    start=time.perf_counter()
    for repeat in range(3):
        with ep.open_recording(job['archive']) as reader:
            for j in range(0,900,25):
                a=max(0,j*60000-61);b=min(54000000,(j+1)*60000+61)
                assert np.array_equal(reader[a:b],reference[a:b])
                time.sleep(.03)
        print(f'Strided CRC/value pass {repeat+1}/3 complete',flush=True)
    save(ROOT/'crc_strided_100MBps.json',dict(status='success',repeats=3,windows_per_repeat=36,
        exact_equal=True,seconds=time.perf_counter()-start,input_metrics=metrics(job)))
