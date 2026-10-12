"""Linux page-remapped reads: independent frames, arbitrary NumPy windows."""
import ctypes
import mmap
import os
import threading
import weakref
import numpy as np
from ._container import CompressedRecording
from ._mapping import PAGE,_LIBC,_memory_fd,_SHARED_AVAILABLE


def _alias(owner, target_offset, size, fd, file_offset):
    if (target_offset<0 or size<=0 or target_offset+size>len(owner)
            or target_offset%PAGE or size%PAGE or file_offset<0 or file_offset%PAGE):
        raise ValueError('Invalid owned mapping range')
    base=ctypes.addressof(ctypes.c_char.from_buffer(owner))
    target=base+target_offset
    pointer=_LIBC.mmap(target,size,mmap.PROT_READ|mmap.PROT_WRITE,mmap.MAP_SHARED|0x10,fd,file_offset)
    if pointer!=target:
        error=ctypes.get_errno()
        raise OSError(error,os.strerror(error))


class _Pool:
    def __init__(self,capacity,limit):
        self.capacity,self.limit=capacity,limit
        self.free=[];self.lock=threading.Lock();self.closed=False
        self.allocations=self.reuses=0

    def take(self):
        with self.lock:
            if self.free:
                self.reuses+=1
                return self.free.pop()
            self.allocations+=1
        fd=_memory_fd()
        try:
            os.ftruncate(fd,self.capacity)
            return fd,mmap.mmap(fd,self.capacity)
        except BaseException:os.close(fd);raise

    def recycle(self,fd,mapping):
        with self.lock:
            if not self.closed and len(self.free)<self.limit:
                self.free.append((fd,mapping));return
        os.close(fd)

    def close(self):
        with self.lock:
            self.closed=True;items=self.free;self.free=[]
        for fd,mapping in items:os.close(fd)

    def __del__(self):self.close()


class _ViewOwner:
    def __init__(self,shape,pointer,frames,mapping=None):
        self.frames=tuple(frames)
        self.mapping=mapping
        self.__array_interface__={'shape':tuple(shape),'typestr':'<i2','version':3,'data':(pointer,True)}


class _Frame:
    def __init__(self,a,b,channels,pool):
        self.fd=-1
        self.a,self.b=a,b
        self.leading=(a*channels*2)%PAGE
        self.file_base=a*channels*2-self.leading
        size=self.leading+(b-a)*channels*2
        self.pool=weakref.ref(pool)
        try:
            self.fd,self.mapping=pool.take()
            if size>len(self.mapping):raise ValueError('Frame exceeds backing capacity')
            self.data=np.ndarray((b-a,channels),dtype='<i2',buffer=self.mapping,offset=self.leading)
        except BaseException:
            if self.fd!=-1:os.close(self.fd);self.fd=-1
            raise

    def __del__(self):
        if self.fd!=-1:
            pool=self.pool()
            if pool is not None:pool.recycle(self.fd,self.mapping)
            else:os.close(self.fd)
            self.fd=-1

    @property
    def nbytes(self):return self.data.nbytes


class MappedRecording(CompressedRecording):
    """Frame cache plus continuous virtual views, with no full-window copy.

Frames have individual RAM-only memfd backing. Mapped returned arrays retain
their pages after eviction/close. Partial pages at unaligned storage borders
are copied into private boundary pages, never overwritten in source frames.
Use the ordinary reader on platforms without Linux memfd/mmap support.
"""
    def __init__(self,path,*,pool_frames=4,**kwargs):
        if not _SHARED_AVAILABLE:raise ValueError('Page-remapped reader requires Linux memfd')
        if not isinstance(pool_frames,int) or pool_frames<0:raise ValueError('pool_frames must be nonnegative integer')
        super().__init__(path,**kwargs)
        frame_bytes=(self._batch+2*self._halo)*self.shape[1]*2+PAGE-1
        self._pool=_Pool(((frame_bytes+PAGE-1)//PAGE)*PAGE,pool_frames)
        self._stats.update(mapped_requests=0,mapped_page_bytes=0,boundary_copy_bytes=0,single_frame_requests=0)

    def _decode(self,block,*,out=None):
        if out is not None:raise ValueError('Mapped frame owns its decode destination')
        a,b=self._entries[block][2:4]
        frame=_Frame(a,b,self.shape[1],self._pool)
        super()._decode(block,out=frame.data)
        return frame

    def _read(self,start,stop):
        if start>=stop:return np.empty((0,self.shape[1]),dtype=self.dtype)
        block=min((start+self._halo)//self._batch,len(self._entries)-1)
        a,b=self._entries[block][2:4]
        if start>=a and stop<=b:
            frame=self._block(block);self._prefetch(block)
            self._stats['single_frame_requests']+=1
            return np.asarray(_ViewOwner((stop-start,self.shape[1]),frame.data.ctypes.data+(start-a)*self.shape[1]*2,[frame]))
        width=self.shape[1]*2
        leading=(start*width)%PAGE
        size=leading+(stop-start)*width
        owner=mmap.mmap(-1,((size+PAGE-1)//PAGE)*PAGE)
        output_base=start*width-leading
        address=ctypes.addressof(ctypes.c_char.from_buffer(owner))
        segments=[];pos=start
        while pos<stop:
            index=min((pos+self._halo)//self._batch,len(self._entries)-1)
            end=min(stop,(index+1)*self._batch)
            segments.append((index,pos,end));pos=end
        mapped=copied=0;frames=[]
        for i,(index,lo,hi) in enumerate(segments):
            self._prime_blocks([s[0] for s in segments[i:i+self._prefetch_blocks]])
            frame=self._block(index)
            frames.append(frame)
            first,last=lo*width,hi*width
            map_lo=(first//PAGE)*PAGE if i==0 else ((first+PAGE-1)//PAGE)*PAGE
            map_hi=((last+PAGE-1)//PAGE)*PAGE if i==len(segments)-1 else (last//PAGE)*PAGE
            if map_hi>map_lo:
                _alias(owner,map_lo-output_base,map_hi-map_lo,frame.fd,map_lo-frame.file_base)
                mapped+=map_hi-map_lo
                pieces=[(first,min(last,map_lo)),(max(first,map_hi),last)]
            else:pieces=[(first,last)]
            for left,right in pieces:
                if right>left:
                    ctypes.memmove(address+left-output_base,frame.data.ctypes.data+left-frame.a*width,right-left)
                    copied+=right-left
        self._prefetch(segments[-1][0],contiguous=True)
        result=np.asarray(_ViewOwner((stop-start,self.shape[1]),address+leading,frames,owner))
        self._stats['cross_block_requests']+=1
        self._stats['mapped_requests']+=1
        self._stats['mapped_page_bytes']+=mapped
        self._stats['boundary_copy_bytes']+=copied
        return result

    def iter_cores(self):
        for i in range(len(self._entries)):
            frame=self._block(i);start=i*self._batch;stop=min(self.shape[0],start+self._batch)
            self._prefetch(i)
            yield np.asarray(_ViewOwner((stop-start,self.shape[1]),frame.data.ctypes.data+(start-frame.a)*self.shape[1]*2,[frame]))

    def statistics(self):
        return dict(super().statistics(),reader_mode='page_remapped',ram_only_backing=True,
                    client_held_views_outside_internal_budget=True,pool_frames=self._pool.limit,
                    backing_allocations=self._pool.allocations,backing_reuses=self._pool.reuses,
                    idle_pool_bytes=len(self._pool.free)*self._pool.capacity)

    def close(self):
        super().close()
        self._pool.close()
