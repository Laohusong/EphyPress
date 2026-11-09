"""Experiment-only scheduling policies; product sources remain unchanged."""
import collections,json,os,threading,time
from pathlib import Path
from ephypress._container import CompressedRecording
from chronosort.utils.recording import WindowPrefetch

ACTIVE=None
READERS=[]
STRATEGY=os.environ.get('PREFETCH_STRATEGY','baseline')
OWNERS={}

def canonical(path):return os.path.normcase(os.path.abspath(path))

class PolicyReader(WindowPrefetch,CompressedRecording):
    def __init__(self,*a,**kw):
        self.shared=None
        if STRATEGY=='shared' and ACTIVE is not None:
            from shared_cache import SharedCache
            self.shared=SharedCache(ACTIVE['scope'],ACTIVE['slots'])
            kw['cache_blocks']=1
        self.decode_counts=collections.Counter();self.requested_blocks=set();self.instrument_lock=threading.Lock()
        self.windows=0;self.context_windows=0;self.batch2_windows=0
        super().__init__(*a,**kw);READERS.append(self)
    def _decode(self,block,**kw):
        if self.shared is not None:
            first,last=self._entries[block][2:4]
            return self.shared.get(block,(last-first,self.shape[1]),lambda:self._actual_decode(block,**kw))
        return self._actual_decode(block,**kw)
    def _actual_decode(self,block,**kw):
        with self.instrument_lock:self.decode_counts[block]+=1
        return super()._decode(block,**kw)
    def _read(self,start,stop):
        self.windows+=1
        if ACTIVE is not None:
            self.context_windows+=1;self.batch2_windows+=int(ACTIVE['batch']==2)
        if stop>start:self.requested_blocks.update(range(start//self._batch,(stop-1)//self._batch+1))
        return super()._read(start,stop)
    def _future(self):
        if STRATEGY not in ('scheduled','shared','grouped') or ACTIVE is None:return super()._future()
        result=[]
        for path,lo,hi in ACTIVE['future']:
            if canonical(path)!=canonical(self.path):continue
            result.extend(range(lo//self._batch,(hi-1)//self._batch+1))
            result=list(dict.fromkeys(result))
            if len(result)>=self._prefetch_blocks:break
        return result[:self._prefetch_blocks]
    def _disabled(self):return STRATEGY=='batch2_off' and ACTIVE is not None and ACTIVE['batch']==2
    def _prime_blocks(self,needed):
        if not self._disabled():return super()._prime_blocks(needed)
    def _prefetch(self,block,**kw):
        if not self._disabled():return super()._prefetch(block,**kw)
    def close(self):
        if self._closed:return
        super().close()
        shared_stats=dict(scope=self.shared.name,hits=self.shared.hits,misses=self.shared.misses,copied_bytes=self.shared.copied_bytes,slots=self.shared.slots) if self.shared else None
        if self.shared:self.shared.close();self.shared=None
        if os.environ.get('POLICY_STATS_DIR'):
            folder=Path(os.environ['POLICY_STATS_DIR']);folder.mkdir(parents=True,exist_ok=True)
            row=dict(pid=os.getpid(),path=str(self.path),strategy=STRATEGY,windows=self.windows,
                context_windows=self.context_windows,batch2_windows=self.batch2_windows,
                shared_stats=shared_stats,counts=dict(self.decode_counts),requested_blocks=sorted(self.requested_blocks),
                unused_decode_calls=sum(n for b,n in self.decode_counts.items() if b not in self.requested_blocks),
                repeat_decode_calls=sum(max(0,n-1) for n in self.decode_counts.values()),statistics=self.statistics())
            with (folder/f'{os.getpid()}.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row)+'\n')

def descriptor(dataset,index):
    # Resolve both torch Subset and the project's SubsetDataset, without changing indices.
    while not hasattr(dataset,'index_map'):
        if hasattr(dataset,'original_dataset'):
            index=int(dataset.indices[index]);dataset=dataset.original_dataset
        elif hasattr(dataset,'dataset') and hasattr(dataset,'indices'):
            index=int(dataset.indices[index]);dataset=dataset.dataset
        else:return None
    if not hasattr(dataset,'file_paths_list'):return None
    day,segment,start,end=dataset.index_map[index]
    nextsegment=dataset.index_map[index+1][1] if index+1<len(dataset.index_map) else None
    last=nextsegment is None or nextsegment!=segment+1
    lo=int(start) if segment==0 else int(start-dataset.padding_left*dataset.downsample_rate)
    hi=int(end if last and segment!=0 else end+dataset.padding_right*dataset.downsample_rate)
    return (str(dataset.file_paths_list[day]),max(0,lo),min(dataset.shapes[day][0],hi))

class ScheduledDataset:
    __getitems__=None  # Do not bypass per-item context when torch probes batched fetch.
    def __init__(self,dataset,schedules,batch_sizes,scope=None,slots=28):
        self.dataset=dataset;self.schedules=schedules;self.batch_sizes=batch_sizes;self.position=0;self.scope=scope;self.slots=slots
    def __len__(self):return len(self.dataset)
    def __getitem__(self,index):
        global ACTIVE
        from torch.utils.data import get_worker_info
        info=get_worker_info();worker=info.id if info else 0
        seq=self.schedules[worker];pos=self.position
        expected,desc,batch=seq[pos]
        if int(index)!=expected:raise AssertionError(('Unexpected DataLoader dispatch',worker,pos,index,expected))
        self.position+=1
        previous=ACTIVE;ACTIVE=dict(batch=batch,future=[v[1] for v in seq[pos+1:pos+5]],scope=self.scope,slots=self.slots)
        try:return self.dataset[index]
        finally:ACTIVE=previous

class GroupedResult:
    def __init__(self,batches):self.batches=batches
    def pin_memory(self):
        from torch.utils.data._utils.pin_memory import pin_memory
        self.batches=[pin_memory(batch) for batch in self.batches]
        return self

class GroupedCollate:
    def __init__(self,collate,sizes):self.collate=collate;self.sizes=sizes
    def __call__(self,items):
        # Every grouped task contains two original batches, except the final one.
        size=self.sizes
        return GroupedResult([self.collate(items[i:i+size]) for i in range(0,len(items),size)])

def install():
    import bandwidth_adapter
    bandwidth_adapter.install()
    import chronosort.utils.recording as recording
    old_process=recording._process_reader;readers={}
    job=json.loads(Path(os.environ['BANDWIDTH_JOB']).read_text(encoding='utf-8'))
    def process_reader(path):
        if canonical(path)!=canonical(job['archive']):return old_process(path)
        key=(os.getpid(),str(path),ACTIVE['scope'] if STRATEGY=='shared' and ACTIVE else None)
        if key not in readers:
            from multiprocessing.util import Finalize
            reader=PolicyReader(path,cache_blocks=8,prefetch_blocks=4)
            readers[key]=reader;Finalize(None,reader.close,exitpriority=10)
        return readers[key]
    recording._process_reader=process_reader
    old_close=recording.close_recordings
    def close():
        old_close()
        for key in list(readers):
            if key[0]==os.getpid():readers.pop(key).close()
    recording.close_recordings=close
    # Same wrapper/dispatch checks for all 3 policies, so instrumentation overhead is shared.
    import torch.utils.data as td
    original_init=td.DataLoader.__init__
    def loader_init(self,dataset,*args,**kwargs):
        original_init(self,dataset,*args,**kwargs)
        from torch.utils.data import SequentialSampler,BatchSampler
        sampler=self.batch_sampler
        if not (isinstance(sampler,list) or isinstance(sampler,BatchSampler) and isinstance(sampler.sampler,SequentialSampler)):
            return
        batches=list(sampler)
        if not batches:return
        if descriptor(dataset,int(batches[0][0])) is None:return
        count=max(1,self.num_workers);schedules=[[] for _ in range(count)]
        nominal=max(map(len,batches))
        tasks=batches
        if STRATEGY=='grouped':
            # Group consecutive original batches; re-expand after ordered delivery.
            # prefetch_factor=1 retains the original budget of two original batches/worker.
            tasks=[sum((list(b) for b in batches[i:i+2]),[]) for i in range(0,len(batches),2)]
            object.__setattr__(self,'batch_sampler',tasks)
            object.__setattr__(self,'collate_fn',GroupedCollate(self.collate_fn,nominal))
            if self.num_workers:object.__setattr__(self,'prefetch_factor',1)
        scope=None;slots=count*7
        if STRATEGY=='shared':
            import uuid
            from shared_cache import SharedCache
            scope=uuid.uuid4().hex;OWNERS[scope]=SharedCache(scope,slots,owner=True)
        for batchid,indices in enumerate(tasks):
            for index in indices:
                desc=descriptor(dataset,int(index))
                if desc is None:raise RuntimeError('Unsupported mixed dataset')
                schedules[batchid%count].append((int(index),desc,nominal))
        object.__setattr__(self,'dataset',ScheduledDataset(dataset,schedules,nominal,scope,slots))
        if os.environ.get('POLICY_STATS_DIR'):
            p=Path(os.environ['POLICY_STATS_DIR']);p.mkdir(parents=True,exist_ok=True)
            with (p/'loaders.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps(dict(batch_size=nominal,workers=self.num_workers,batches=len(batches),tasks=len(tasks),items=sum(map(len,batches)),scope=scope,shared_slots=slots if scope else 0))+'\n')
    td.DataLoader.__init__=loader_init
    original_iter=td.DataLoader.__iter__
    def loader_iter(self):
        scope=getattr(self.dataset,'scope',None);iterator=original_iter(self)
        try:
            for result in iterator:
                if isinstance(result,GroupedResult):yield from result.batches
                else:yield result
        finally:
            if scope:
                if hasattr(iterator,'_shutdown_workers'):iterator._shutdown_workers()
                OWNERS.pop(scope).close()
    td.DataLoader.__iter__=loader_iter
