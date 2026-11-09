import json,os,subprocess,sys
from pathlib import Path
from experiment import ROOT,PYTHON,job_for,save,environment
if not os.environ.get('BANDWIDTH_JOB'):
    from bandwidth_adapter import initialize
    job=job_for('validation','compressed',5000,'window_prefetch_validation')
    request=ROOT/(job['name']+'.job.json');save(request,job);initialize(job)
    subprocess.run([str(PYTHON),str(Path(__file__).resolve())],env=environment(request),check=True)
else:
    import numpy as np
    from chronosort.utils import recording
    job=json.loads(Path(os.environ['BANDWIDTH_JOB']).read_text())
    array=recording.open_recording(job['archive'],shape=(54000000,384))
    reference=np.memmap(job['raw'],mode='r',dtype='<i2',shape=(54000000,384))
    for start in [0,248000,496000,744000,992000,1240000,1488000,1736000]:
        end=start+65536
        assert np.array_equal(array[start:end],reference[start:end])
    reader=recording._process_reader(str(Path(job['archive']).resolve()))
    assert reader.statistics()['consumer_window_prefetch'] is True
    recording.close_recordings()
    save(ROOT/'window_prefetch_validation.json',dict(status='success',value_equality=True,
        windows=8,consumer_stride_samples=248000,window_samples=65536,
        native_consumer_window_policy=True))
    print('Window-prefetch adapter value checks passed.',flush=True)
