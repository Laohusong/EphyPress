"""Windows pagefile-backed bounded cache; per-loader scope, single flight per block.

Ready blocks are copied under the metadata mutex into private reader buffers.
This deliberate copy makes eviction safe without holding a lease in consumer code.
Loading slots cannot be evicted. Failed loads clear their reservation and propagate.
"""
import ctypes,hashlib,mmap,os,time
import numpy as np
from bandwidth_adapter import _kernel

class Mutex:
    def __init__(self,name):
        self.handle=_kernel.CreateMutexW(None,False,'Local\\EPShared_'+name)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
    def __enter__(self):
        result=_kernel.WaitForSingleObject(self.handle,120000)
        if result not in (0,0x80):raise RuntimeError(('Shared cache mutex timeout/failure',result))
        if result==0x80:
            _kernel.ReleaseMutex(self.handle)
            raise RuntimeError('Shared cache owner died; refusing potentially incomplete data')
        return self
    def __exit__(self,*a):_kernel.ReleaseMutex(self.handle)
    def close(self):
        if self.handle:
            _kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            _kernel.CloseHandle(self.handle);self.handle=None

class SharedCache:
    def __init__(self,name,slots=28,owner=False):
        self.name=name;self.slots=slots;self.block_bytes=60000*384*2
        self.meta_map=mmap.mmap(-1,(slots+1)*4*8,tagname='Local\\EPSharedMeta_'+name)
        self.meta=np.ndarray((slots+1,4),dtype='<i8',buffer=self.meta_map)
        self.data=mmap.mmap(-1,slots*self.block_bytes,tagname='Local\\EPSharedData_'+name)
        import threading
        self.thread_lock=threading.Lock()
        self.lock=Mutex(name+'_meta');self.block_locks={};self.hits=0;self.misses=0;self.copied_bytes=0
        if owner:
            self.meta[:]=0;self.meta[1:,0]=-1
    def get(self,block,shape,decode):
        import threading
        # dict.setdefault may construct redundant handles but would leak them; guard creation.
        if not hasattr(self,'thread_lock'):self.thread_lock=threading.Lock()
        with self.thread_lock:
            if block not in self.block_locks:self.block_locks[block]=Mutex(self.name+'_block_'+str(block))
            flight=self.block_locks[block]
        with flight:
            with self.lock:
                rows=self.meta[1:];matches=np.flatnonzero((rows[:,0]==block)&(rows[:,1]==2))
                if len(matches):
                    slot=int(matches[0]);self.meta[0,0]+=1;rows[slot,2]=self.meta[0,0]
                    result=np.ndarray(shape,dtype='<i2',buffer=self.data,offset=slot*self.block_bytes).copy()
                    result.flags.writeable=False;self.hits+=1;self.copied_bytes+=result.nbytes
                    return result
                available=np.flatnonzero(rows[:,1]!=1)
                if not len(available):raise RuntimeError('All shared cache slots loading; capacity invariant broken')
                slot=int(min(available,key=lambda s: rows[s,2] if rows[s,1]==2 else -1))
                rows[slot]=[block,1,0,os.getpid()]
            try:
                result=decode()
                target=np.ndarray(shape,dtype='<i2',buffer=self.data,offset=slot*self.block_bytes)
                target[:]=result;del target
                with self.lock:
                    self.meta[0,0]+=1;rows[slot]=[block,2,self.meta[0,0],0]
                self.misses+=1
                return result
            except BaseException:
                with self.lock:rows[slot]=[-1,0,0,0]
                raise
    def close(self):
        for lock in self.block_locks.values():lock.close()
        self.lock.close();del self.meta;self.meta_map.close();self.data.close()
