"""Extra correctness check prompted by different KS4 clustering outputs.

Run only between sorting jobs. Check the actual60122-sample padded windows,
including the first/last and the stride25 used to learn universal templates.
"""
import hashlib
import numpy as np
import ephypress as ep
import experiment as ex

def main():
    raw=np.memmap(ex.OLD/'first30min.dat',mode='r',dtype='<i2',shape=(54000000,384))
    indices=sorted(set([0,1,2,24,25,26,49,50,51,100,200,449,450,451,600,700,874,875,876,897,898,899]))
    windows=[]
    with ep.open_recording(ex.OLD/'first30min.ep') as reader:
        for batch in indices:
            lo=0 if batch==0 else batch*60000-61
            hi=min(54000000,(batch+1)*60000+61)
            actual=reader[lo:hi];expected=raw[lo:hi]
            assert actual.shape==expected.shape and np.array_equal(actual,expected), (batch,lo,hi)
            windows.append(dict(batch=batch,start=lo,end=hi,sha256=hashlib.sha256(expected.tobytes()).hexdigest()))
    ex.save(ex.ROOT/'ks4_padded_window_verification.json',dict(status='passed',exact_ADC=True,core_samples=60000,context_samples_per_side=61,
        windows=windows,scope='Representative true KS4 padded ranges including template-learning stride25; all900 complete aligned codec blocks also verified earlier.',
        output_note='Different clustering output sizes do not establish an input mismatch; preserve hashes and report one-run variability.'))
    print('KS4 PADDED INPUT WINDOWS EXACT',len(windows),flush=True)

if __name__=='__main__':main()
