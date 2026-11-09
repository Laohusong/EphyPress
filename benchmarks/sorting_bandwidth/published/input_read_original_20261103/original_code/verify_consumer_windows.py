"""Post-sweep ADC fidelity check using actual four-worker batch patterns."""
import argparse,json,os,subprocess,sys
from pathlib import Path
from experiment import ROOT,PYTHON,job_for,save,environment

def child(worker,batch):
    import numpy as np
    from chronosort.utils import recording
    job=json.loads(Path(os.environ['BANDWIDTH_JOB']).read_text())
    actual=recording.open_recording(job['archive'],shape=(54000000,384))
    reference=np.memmap(job['raw'],mode='r',dtype='<i2',shape=(54000000,384))
    count=(54000000+61999)//62000
    checked=0;windows=0
    for group in range(worker,(count+batch-1)//batch,4):
        for index in range(group*batch,min((group+1)*batch,count)):
            start=max(0,index*62000-1768);end=min(54000000,(index+1)*62000+1768)
            result=actual[start:end]
            if not np.array_equal(result,reference[start:end]):
                raise AssertionError(f'ADC mismatch batch={batch} worker={worker} window={index} samples={start}:{end}')
            checked+=(end-start)*384;windows+=1
    recording.close_recordings()
    save(ROOT/f'consumer_fidelity_batch{batch}_worker{worker}.json',dict(status='success',windows=windows,
        checked_ADC_values_including_overlaps=checked,worker=worker,batch_size=batch))

def main():
    from bandwidth_adapter import initialize
    reports=[]
    for batch in (1,2):
        job=job_for('validation','compressed',5000,f'consumer_fidelity_batch{batch}')
        request=ROOT/(job['name']+'.job.json');save(request,job);initialize(job)
        workers=[subprocess.Popen([str(PYTHON),'-u',str(Path(__file__).resolve()),'--worker',str(i),'--batch',str(batch)],
            env=environment(request),creationflags=subprocess.CREATE_NO_WINDOW) for i in range(4)]
        codes=[p.wait() for p in workers];assert codes==[0]*4,codes
        rows=[json.loads((ROOT/f'consumer_fidelity_batch{batch}_worker{i}.json').read_text()) for i in range(4)]
        assert sum(x['windows'] for x in rows)==(54000000+61999)//62000
        reports.append(dict(batch_size=batch,workers=rows,entire_30min_covered=True))
        print(f'Full consumer-window fidelity check passed: 4 workers, batch size {batch}',flush=True)
    save(ROOT/'consumer_window_fidelity.json',dict(status='success',exact_equal=True,patterns=reports,
        scope='Entire 30 minutes with 62000-sample segments and 1768-sample boundary padding; four strided workers; batch sizes 1 and 2.'))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--worker',type=int);parser.add_argument('--batch',type=int)
    args=parser.parse_args()
    if args.worker is not None:child(args.worker,args.batch)
    else:main()
