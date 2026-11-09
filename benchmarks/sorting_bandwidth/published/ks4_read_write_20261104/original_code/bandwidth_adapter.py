"""Experiment-only input bandwidth model. No product source changes.

One serialized byte budget shared across all threads and subprocesses.
OS cache does not bypass the budget; decoded SPC cache hits do not read bytes.
"""
import ctypes
from ctypes import wintypes
import json
import mmap
import os
from pathlib import Path
import struct
import threading
import time
import numpy as np

STATE=struct.Struct('<dQQdd')  # next delivery, bytes, calls, first request, last deadline
_kernel=ctypes.WinDLL('kernel32',use_last_error=True)
_kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
_kernel.CreateMutexW.restype=wintypes.HANDLE
_kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
_kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
_handles={}

def initialize(job):
    path=Path(job['limiter_state'])
    path.write_bytes(bytes(STATE.size))

def _state():
    key=(os.getpid(),os.environ['BANDWIDTH_JOB'])
    if key not in _handles:
        job=json.loads(Path(key[1]).read_text(encoding='utf-8'))
        f=open(job['limiter_state'],'r+b',buffering=0)
        import hashlib
        name='Local\\ChronoBandwidth_'+hashlib.sha256(job['limiter_state'].encode()).hexdigest()[:24]
        mutex=_kernel.CreateMutexW(None,False,name)
        if not mutex: raise ctypes.WinError(ctypes.get_last_error())
        _handles[key]=(job,f,mmap.mmap(f.fileno(),STATE.size),mutex)
    return _handles[key]

def reserve(size):
    job,_,state,mutex=_state()
    result=_kernel.WaitForSingleObject(mutex,0xffffffff)
    if result not in (0,0x80): raise RuntimeError('Limiter mutex acquisition failed')
    try:
        next_time,total,calls,first,last=STATE.unpack_from(state)
        now=time.perf_counter()
        deadline=max(now,next_time)+size/(job['bandwidth_MB_s']*1e6)
        STATE.pack_into(state,0,deadline,total+size,calls+1,first or now,deadline)
        return deadline
    finally:
        _kernel.ReleaseMutex(mutex)

def deliver(deadline):
    delay=deadline-time.perf_counter()
    if delay>0:time.sleep(delay)

def metrics(job):
    next_time,total,calls,first,last=STATE.unpack(Path(job['limiter_state']).read_bytes())
    return dict(charged_file_bytes=total,read_calls=calls,first_request=first,last_delivery_deadline=last,
                aggregate_bytes_per_active_span_MB_s=total/max(last-first,1e-12)/1e6)

class RawArray:
    def __init__(self,path,shape=None):
        self.path=str(Path(path).resolve()); self.dtype=np.dtype('<i2')
        self.shape=tuple(shape) if shape else (Path(path).stat().st_size//768,384)
        self.ndim=len(self.shape);self.size=int(np.prod(self.shape))
    def __len__(self):return self.shape[0]
    def __getitem__(self,key):
        row,cols=key if isinstance(key,tuple) else (key,slice(None))
        scalar=isinstance(row,(int,np.integer))
        if scalar:
            lo=int(row);lo=lo if lo>=0 else lo+len(self);hi=lo+1;step=1
            if lo<0 or hi>len(self):raise IndexError(row)
        elif isinstance(row,slice):
            lo,hi,step=row.indices(len(self))
            if step<=0:raise ValueError('Only positive input strides supported')
        else:raise TypeError(f'Unsupported raw row index {type(row)}')
        hi=max(lo,hi);width=self.shape[1];size=(hi-lo)*width*2
        deadline=reserve(size)
        with open(self.path,'rb',buffering=0) as f:
            f.seek(lo*width*2);data=f.read(size)
        if len(data)!=size:raise IOError('Short raw input read')
        deliver(deadline)
        array=np.frombuffer(data,dtype=self.dtype).reshape(hi-lo,width)[::step]
        return array[0,cols] if scalar else array[:,cols]

_installed=False
def install():
    global _installed
    if _installed:return
    _installed=True
    import ephypress as ep
    from ephypress._io import PositionedFile
    original=PositionedFile.read_at
    job=json.loads(Path(os.environ['BANDWIDTH_JOB']).read_text(encoding='utf-8'))
    archive=os.path.normcase(os.path.abspath(job['archive']))
    def limited_read(self,length,offset):
        if os.path.normcase(os.path.abspath(self.path))!=archive:return original(self,length,offset)
        deadline=reserve(length)
        result=original(self,length,offset)
        deliver(deadline)
        return result
    PositionedFile.read_at=limited_read
    # Failure-only observer: preserve bad payloads without retrying or masking
    # CRC failures. Successful decode behavior is unchanged.
    from ephypress._container import CompressedRecording as EPRecording
    old_decode=EPRecording._decode
    def observed_decode(self,block,*,out=None):
        try:return old_decode(self,block,out=out)
        except ValueError as exc:
            if 'checksum mismatch or truncation' in str(exc):
                import zlib,hashlib
                tb=exc.__traceback__;payload=None
                while tb is not None:
                    if 'payload' in tb.tb_frame.f_locals:payload=tb.tb_frame.f_locals['payload']
                    tb=tb.tb_next
                position,size,first,last,expected=self._entries[block]
                record=dict(block=block,position=position,requested_bytes=size,expected_crc=expected,
                    path=str(self.path),pid=os.getpid(),error=str(exc))
                if isinstance(payload,bytes):
                    record.update(returned_bytes=len(payload),returned_crc=zlib.crc32(payload),
                        returned_sha256=hashlib.sha256(payload).hexdigest())
                    base=Path(job['limiter_state']).with_suffix(f'.bad_read_{os.getpid()}_{block}')
                    base.with_suffix(base.suffix+'.bin').write_bytes(payload)
                    with open(self.path,'rb',buffering=0) as f:
                        f.seek(position);fresh=f.read(size)
                    record.update(fresh_bytes=len(fresh),fresh_crc=zlib.crc32(fresh),
                        fresh_sha256=hashlib.sha256(fresh).hexdigest())
                    base.with_suffix(base.suffix+'.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
            raise
    EPRecording._decode=observed_decode
    import chronosort.utils.recording as recording
    old_format,old_metadata,old_open=recording.storage_format,recording.recording_metadata,recording.open_recording
    raw=os.path.normcase(os.path.abspath(job['raw']))
    def is_path(path,target):return os.path.normcase(os.path.abspath(path))==target
    def storage_format(path):return 'spc' if is_path(path,archive) else old_format(path)
    def metadata(path):
        if not is_path(path,archive):return old_metadata(path)
        m=ep.info(path)
        return {**m,'dtype':'<i2','fs':m['sampling_frequency']}
    readers={}
    def open_recording(path,dtype='int16',mode='r',shape=None):
        if is_path(path,raw):
            assert mode=='r' and np.dtype(dtype)==np.dtype('<i2')
            return RawArray(path,shape)
        if is_path(path,archive):
            return recording.SPCArray(path)
        return old_open(path,dtype,mode,shape)
    old_process=recording._process_reader
    def process_reader(path):
        if not is_path(path,archive):return old_process(path)
        key=(os.getpid(),str(path))
        if key not in readers:
            from multiprocessing.util import Finalize
            from ephypress._container import CompressedRecording
            # Preserve current ChronoSort consumer-window prediction, including
            # strided DataLoader workers, while replacing only the codec.
            cls=type('EphyPressWindowRecording',(recording.WindowPrefetch,CompressedRecording),{})
            reader=cls(path,cache_blocks=8,prefetch_blocks=4)
            readers[key]=reader
            Finalize(None,reader.close,exitpriority=10)
        return readers[key]
    recording.storage_format=storage_format
    recording.recording_metadata=metadata
    recording.open_recording=open_recording
    recording._process_reader=process_reader
    old_close=recording.close_recordings
    def close_recordings():
        old_close()
        for key in list(readers):
            if key[0]==os.getpid():readers.pop(key).close()
    recording.close_recordings=close_recordings
