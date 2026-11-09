"""External logical file-I/O budgets, shared across Windows processes.

Mapped intermediate arrays use explicit, charged copies on access. Both
conditions use these same hooks; only the non-input read/write rates change.
This measures application data access, not physical disk transactions.
"""
import builtins, ctypes, hashlib, io, json, mmap, os, shutil, struct, threading, time
from ctypes import wintypes
from pathlib import Path
import numpy as np
from numpy.lib.mixins import NDArrayOperatorsMixin

OPEN=builtins.open
IOOPEN=io.open
STATE=struct.Struct('<dd'+'QQ'*6) # read/write deadlines; bytes/calls per category
CATEGORIES=('input_read','stream_read','mapped_read','stream_write','mapped_write','copy_reserved')
K=ctypes.WinDLL('kernel32',use_last_error=True)
K.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];K.CreateMutexW.restype=wintypes.HANDLE
K.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
K.ReleaseMutex.argtypes=[wintypes.HANDLE]
K.GetFinalPathNameByHandleW.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
_state=None
_job=None
_installed=False

def initialize(job):
    Path(job['io_state']).write_bytes(bytes(STATE.size))

def canonical(path):
    try:return os.path.normcase(os.path.abspath(os.fsdecode(path)))
    except (TypeError,ValueError):return ''

def fd_path(fd):
    import msvcrt
    try:
        buffer=ctypes.create_unicode_buffer(32768)
        n=K.GetFinalPathNameByHandleW(msvcrt.get_osfhandle(fd),buffer,len(buffer),0)
        if n and n<len(buffer):return buffer.value.removeprefix('\\\\?\\')
    except (OSError,ValueError):pass
    return ''

def scoped(path):
    path=canonical(path)
    if not path:return False
    # Exact source input is already charged by the input adapter.
    if path in (canonical(_job['raw']),canonical(_job['archive'])):return False
    roots=[Path(_job['folder'])/'run',Path(_job['folder'])/'results',Path(_job['folder'])/'temp',
           Path(_job['probe']).parent,Path(_job['source_root']).parent/'resources']
    # The input fixture directory also contains old results and limiter files;
    # only the explicitly requested probe/KS probe are included there.
    for root in roots:
        if root==Path(_job['probe']).parent:
            if path in (canonical(_job['probe']),canonical(root/'ks4_probe.json')):return True
        elif path==canonical(root) or path.startswith(canonical(root)+os.sep):return True
    return False

def get_state():
    global _state
    if _state is None:
        f=OPEN(_job['io_state'],'r+b',buffering=0)
        mm=mmap.mmap(f.fileno(),STATE.size)
        mutex=K.CreateMutexW(None,False,'Local\\ChronoAllIO_'+hashlib.sha256(_job['io_state'].encode()).hexdigest()[:24])
        if not mutex:raise ctypes.WinError(ctypes.get_last_error())
        _state=(f,mm,mutex)
    return _state

def reserve(size,category,requested=None):
    if size<=0:return 0.
    _,state,mutex=get_state()
    rc=K.WaitForSingleObject(mutex,0xffffffff)
    if rc not in (0,0x80):raise RuntimeError('I/O mutex failed')
    try:
        values=list(STATE.unpack_from(state));index=CATEGORIES.index(category)
        direction=0 if index<=2 else 1
        limited=category=='input_read' or _job['io_condition']=='all_read_write'
        now=time.perf_counter() if requested is None else requested
        deadline=max(now,values[direction])+size/(_job['rate']*1e6) if limited else now
        if limited:values[direction]=deadline
        values[2+2*index]+=int(size);values[3+2*index]+=1
        STATE.pack_into(state,0,*values)
        return deadline
    finally:K.ReleaseMutex(mutex)

def deliver(deadline):
    delay=deadline-time.perf_counter()
    if delay>0:time.sleep(delay)

def charge(size,category,requested=None):deliver(reserve(size,category,requested))

def metrics(job):
    with OPEN(job['io_state'],'rb') as f:values=STATE.unpack(f.read())
    out={key:dict(bytes=values[2+2*i],calls=values[3+2*i]) for i,key in enumerate(CATEGORIES)}
    out['total_read_bytes']=sum(out[k]['bytes'] for k in CATEGORIES[:3])
    out['total_write_bytes']=sum(out[k]['bytes'] for k in CATEGORIES[3:])
    return out

class Stream:
    def __init__(self,file):self.file=file
    def __getattr__(self,name):return getattr(self.file,name)
    def fileno(self):
        # Pillow otherwise gives a native encoder the descriptor and bypasses
        # Python write(). Force its documented file-object fallback for images.
        if Path(str(getattr(self.file,'name',''))).suffix.lower() in ('.png','.jpg','.jpeg','.gif','.tif','.tiff','.webp'):
            raise io.UnsupportedOperation('Instrumented image output uses write()')
        return self.file.fileno()
    def __enter__(self):return self
    def __exit__(self,*args):return self.file.__exit__(*args)
    def __iter__(self):return self
    def __next__(self):
        line=self.readline()
        if not line:raise StopIteration
        return line
    def _bytes(self,data):
        return len(data.encode(self.file.encoding or 'utf-8',errors=self.file.errors or 'strict')) if isinstance(data,str) else len(data)
    def read(self,*args):
        start=time.perf_counter();data=self.file.read(*args);charge(self._bytes(data),'stream_read',start);return data
    def read1(self,*args):
        start=time.perf_counter();data=self.file.read1(*args);charge(self._bytes(data),'stream_read',start);return data
    def readinto(self,b):
        start=time.perf_counter();n=self.file.readinto(b);charge(n or 0,'stream_read',start);return n
    def readinto1(self,b):
        start=time.perf_counter();n=self.file.readinto1(b);charge(n or 0,'stream_read',start);return n
    def readline(self,*args):
        start=time.perf_counter();data=self.file.readline(*args);charge(self._bytes(data),'stream_read',start);return data
    def readlines(self,hint=-1):
        values=[];size=0
        for value in self:
            values.append(value);size+=self._bytes(value)
            if hint>0 and size>=hint:break
        return values
    def write(self,data):
        size=self._bytes(data) if isinstance(data,(str,bytes,bytearray)) else memoryview(data).nbytes
        deadline=reserve(size,'stream_write');n=self.file.write(data);deliver(deadline);return n
    def writelines(self,lines):
        for line in lines:self.write(line)

def wrap(file,path):return Stream(file) if scoped(path) and not isinstance(file,Stream) else file

def convert(value):
    if isinstance(value,MappedArray):return value.__array__()
    if isinstance(value,tuple):return tuple(convert(v) for v in value)
    if isinstance(value,list):return [convert(v) for v in value]
    if isinstance(value,dict):return {k:convert(v) for k,v in value.items()}
    return value

class MappedArray(NDArrayOperatorsMixin):
    """Charge selected mapped bytes; return owned arrays so views cannot bypass it."""
    __array_priority__=1000
    def __init__(self,array):self._array=array
    @property
    def shape(self):return self._array.shape
    @property
    def dtype(self):return self._array.dtype
    @property
    def ndim(self):return self._array.ndim
    @property
    def size(self):return self._array.size
    @property
    def nbytes(self):return self._array.nbytes
    def __len__(self):return len(self._array)
    def __iter__(self):
        if self.ndim==1:
            # Preserve native memmap scalar iteration and consumer ordering.
            # Charge bounded64KiB read-ahead chunks rather than taking an IPC
            # mutex for each spike. Consumer CPU time can satisfy the budget.
            rows=max(1,65536//self.dtype.itemsize)
            for first in range(0,len(self),rows):
                start=time.perf_counter();block=self._array[first:first+rows]
                deadline=reserve(block.nbytes,'mapped_read',start)
                try:yield from block
                finally:deliver(deadline)
        else:
            # Rows may escape the iterator: copy bounded chunks into RAM.
            width=int(np.prod(self.shape[1:]))*self.dtype.itemsize
            rows=max(1,1048576//max(1,width))
            for first in range(0,len(self),rows):yield from self[first:first+rows]
    def __array__(self,dtype=None):
        start=time.perf_counter()
        value=np.array(self._array,copy=True,dtype=dtype)
        charge(self.nbytes,'mapped_read',start);return value
    def __getitem__(self,key):
        start=time.perf_counter()
        selected=self._array[convert(key)]
        value=np.array(selected,copy=True) if isinstance(selected,np.ndarray) else selected.copy()
        charge(np.asarray(selected).nbytes,'mapped_read',start);return value
    def __setitem__(self,key,value):
        key=convert(key);value=convert(value)
        size=np.asarray(self._array[key]).nbytes
        deadline=reserve(size,'mapped_write');self._array[key]=value;deliver(deadline)
    def __array_ufunc__(self,ufunc,method,*inputs,**kwargs):
        if kwargs.get('out') is not None:raise RuntimeError('Uninstrumented mapped in-place ufunc')
        return getattr(ufunc,method)(*convert(inputs),**convert(kwargs))
    def __array_function__(self,func,types,args,kwargs):
        if func is np.copyto and isinstance(args[0],MappedArray):
            target=args[0];deadline=reserve(target.nbytes,'mapped_write')
            result=np.copyto(target._array,convert(args[1]),**convert(kwargs));deliver(deadline);return result
        if kwargs.get('out') is not None:raise RuntimeError('Uninstrumented mapped output operation')
        return func(*convert(args),**convert(kwargs))
    def __getattr__(self,name):
        if name in ('filename','offset','mode','flags'):return getattr(self._array,name)
        # Deliberately hide pointer interfaces; consumers must pass __array__.
        if name.startswith('__array_') or name in ('data','ctypes','base','_mmap'):raise AttributeError(name)
        if name in ('sort','put','itemset','resize','partition','setfield'):raise RuntimeError('Uninstrumented mapped mutation: '+name)
        return getattr(self.__array__(),name)
    def flush(self):return self._array.flush()
    def fill(self,value):
        deadline=reserve(self.nbytes,'mapped_write');self._array.fill(value);deliver(deadline)

def install():
    global _job,_installed
    if _installed:return
    _job=json.loads(Path(os.environ['ALL_IO_JOB']).read_text(encoding='utf-8'));_installed=True
    old_open=builtins.open;old_ioopen=io.open;old_fdopen=os.fdopen
    def opened(file,*args,**kwargs):return wrap(old_open(file,*args,**kwargs),fd_path(file) if isinstance(file,int) else file)
    def ioopened(file,*args,**kwargs):return wrap(old_ioopen(file,*args,**kwargs),fd_path(file) if isinstance(file,int) else file)
    def fdopened(fd,*args,**kwargs):return wrap(old_fdopen(fd,*args,**kwargs),fd_path(fd))
    builtins.open=opened;io.open=ioopened;os.fdopen=fdopened
    # Route native Torch ZIP I/O through the instrumented Python file object.
    import torch
    old_save,old_load=torch.save,torch.load
    def saved(obj,f,*args,**kwargs):
        if isinstance(f,(str,bytes,os.PathLike)) and scoped(f):
            with opened(f,'wb') as stream:return old_save(obj,stream,*args,**kwargs)
        return old_save(obj,f,*args,**kwargs)
    def loaded(f,*args,**kwargs):
        if isinstance(f,(str,bytes,os.PathLike)) and scoped(f):
            if kwargs.get('mmap'):raise RuntimeError('Torch mmap loading needs explicit instrumentation')
            with opened(f,'rb') as stream:return old_load(stream,*args,**kwargs)
        return old_load(f,*args,**kwargs)
    torch.save=saved;torch.load=loaded
    for name in ('tensor','as_tensor','from_numpy','asarray'):
        if hasattr(torch,name):
            original=getattr(torch,name)
            def tensor(value,*args,_original=original,**kwargs):return _original(convert(value),*args,**kwargs)
            setattr(torch,name,tensor)
    old_map=np.lib.format.open_memmap
    def open_memmap(filename,*args,**kwargs):
        value=old_map(filename,*args,**kwargs)
        return MappedArray(value) if scoped(filename) else value
    np.lib.format.open_memmap=open_memmap
    old_copy=shutil.copyfile
    def copyfile(src,dst,*,follow_symlinks=True):
        if not (scoped(src) or scoped(dst)):return old_copy(src,dst,follow_symlinks=follow_symlinks)
        if os.path.samefile(src,dst) if os.path.exists(dst) else False:raise shutil.SameFileError(src,dst)
        if not follow_symlinks and os.path.islink(src):return old_copy(src,dst,follow_symlinks=False)
        with opened(src,'rb') as source,opened(dst,'wb') as target:
            shutil.copyfileobj(source,target,1024*1024)
        return dst
    shutil.copyfile=copyfile
    # Exact source input reads use the SAME read budget as intermediates.
    import bandwidth_adapter
    original_reserve=bandwidth_adapter.reserve
    def input_reserve(size):
        original_reserve(size) # retain the separate original-input counters
        return reserve(size,'input_read')
    bandwidth_adapter.reserve=input_reserve
    from chronosort.run_sorting import StageRunner
    original_run=StageRunner.run
    def stage_run(self,stage_id,parameters,operation):
        before=metrics(_job);start=time.perf_counter()
        result=original_run(self,stage_id,parameters,operation)
        after=metrics(_job)
        for key in CATEGORIES:
            for field in ('bytes','calls'):after[key][field]-=before[key][field]
        for key in ('total_read_bytes','total_write_bytes'):after[key]-=before[key]
        with OPEN(Path(_job['folder'])/'stage_io.jsonl','a',encoding='utf-8') as f:
            f.write(json.dumps(dict(stage=stage_id,seconds=time.perf_counter()-start,metrics=after))+'\n')
        return result
    StageRunner.run=stage_run
