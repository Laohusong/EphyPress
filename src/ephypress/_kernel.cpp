#include "_predictors.h"
// SPDX-License-Identifier: MIT
// Split residual planes. All prediction arithmetic is integer and block-local.
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>

// Decode independent entropy packets in C, then tile their channel-major
// storage into the time-major plane. The FSE function comes from the checked
// Python loader, so this kernel has no link-time libzstd dependency.
extern "C" int spc_decode_groups(const uint8_t *src, uint64_t bytes,
                                 uint64_t rows, uint32_t width, uint32_t group,
                                 uint8_t *output, void *decode_function) {
    if (!rows || !width || !group || !decode_function || rows>SIZE_MAX/width) return -1;
    using Decode = size_t (*)(void *,size_t,const void *,size_t);
    auto decode = reinterpret_cast<Decode>(decode_function);
    const uint32_t groups=(uint64_t(width)+group-1)/group;
    std::vector<uint64_t> offsets(groups),lengths(groups);
    uint64_t pos=0;
    for (uint32_t g=0;g<groups;++g) {
        if (pos>bytes || bytes-pos<4) return -1;
        uint32_t len=uint32_t(src[pos]) | (uint32_t(src[pos+1])<<8) |
                     (uint32_t(src[pos+2])<<16) | (uint32_t(src[pos+3])<<24);
        pos+=4;
        if (!len || len>bytes-pos) return -1;
        offsets[g]=pos;lengths[g]=len;pos+=len;
    }
    if (pos!=bytes) return -1;
    std::vector<uint8_t> planes(rows*width);
    std::vector<int> errors(groups,0);
    #pragma omp parallel for num_threads(2) if(rows*width>=262144)
    for (uint32_t g=0;g<groups;++g) {
        uint32_t c=g*group,cols=std::min(group,width-c);
        uint64_t count=rows*cols,len=lengths[g];
        const uint8_t *packet=src+offsets[g];
        uint8_t *dst=planes.data()+uint64_t(c)*rows;
        if (packet[0]==0 && len==count+1) std::memcpy(dst,packet+1,count);
        else if (packet[0]==2 && len==2) std::memset(dst,packet[1],count);
        else if (packet[0]==1 && len>=3) {
            if (decode(dst,count,packet+1,len-1)!=count) errors[g]=1;
        } else errors[g]=1;
    }
    for (int error:errors) if(error) return -1;
    // Bounded tiles keep cache lines from each channel hot until consumed.
    if(group==1) {
        #pragma omp parallel for num_threads(2) if(rows*width>=262144)
        for(uint64_t t0=0;t0<rows;t0+=64)
            for(uint32_t c0=0;c0<width;c0+=32)
                for(uint64_t t=t0;t<std::min(rows,t0+64);++t)
                    for(uint32_t c=c0;c<std::min(width,c0+32);++c)
                        output[t*width+c]=planes[uint64_t(c)*rows+t];
        return 0;
    }
    #pragma omp parallel for num_threads(2) if(rows*width>=262144)
    for (uint64_t t0=0;t0<rows;t0+=64) {
        for (uint32_t c0=0;c0<width;c0+=32) {
            for (uint64_t t=t0;t<std::min(rows,t0+64);++t) {
                for (uint32_t c=c0;c<std::min(width,c0+32);++c) {
                    uint32_t first=(c/group)*group,cols=std::min(group,width-first);
                    output[t*width+c]=planes[uint64_t(first)*rows+t*cols+(c-first)];
                }
            }
        }
    }
    return 0;
}

static inline int16_t wrap16(int v) {
    uint16_t u = static_cast<uint16_t>(v);
    int16_t s; std::memcpy(&s, &u, 2); return s;
}
static inline int floor_div(int x, int d) {
    int v = x / d; return v - (x < 0 && x % d != 0);
}
// A signed prediction is defined as floor(p*x/8), independent of compiler shifts.
static inline int pred(int x, int p) { return floor_div(x * p, 8); }
static inline bool learned(int p) { return p>=32 && p<32+SPC_MODEL_COUNT; }
static inline bool valid_pred(int p) { return (p>=0 && p<=8) || p==13 || p==14 || p==15 || learned(p); }
static inline int temporal_pred(int x,int p) {
    return learned(p) ? floor_div(x*SPC_TEMPORAL[p-32],16) : pred(x,p>=13 ? 5 : p);
}

template<int Model> static void inverse_learned(int16_t *output,uint64_t rows,uint32_t chans) {
    constexpr int order=SPC_ORDER[Model];
    #pragma omp parallel for num_threads(2) if(rows*chans>=262144)
    for(uint64_t t=0;t<rows;++t) {
        int previous[order]={};
        const uint64_t base=t*chans;
        for(uint32_t c=0;c<chans;++c) {
            int sum=0;
            for(int j=0;j<order;++j) sum+=SPC_WEIGHTS[Model][j]*previous[j];
            const int value=wrap16(int(output[base+c])+floor_div(sum,32));
            output[base+c]=value;
            for(int j=order-1;j>0;--j) previous[j]=previous[j-1];
            previous[0]=value;
        }
    }
    for(uint64_t t=1;t<rows;++t) {
        const uint64_t base=t*chans;
        for(uint32_t c=0;c<chans;++c)
            output[base+c]=wrap16(int(output[base+c])+floor_div(int(output[base+c-chans])*SPC_TEMPORAL[Model],16));
    }
}

template<int Model> static void forward_learned(const int16_t *quant,int16_t *residual,uint64_t rows,uint32_t chans) {
    constexpr int order=SPC_ORDER[Model];
    #pragma omp parallel for num_threads(2) if(rows*chans>=262144)
    for(uint64_t t=0;t<rows;++t) {
        const uint64_t base=t*chans;
        for(uint32_t c=0;c<chans;++c) {
            int previous=t ? floor_div(int(quant[base+c-chans])*SPC_TEMPORAL[Model],16) : 0;
            residual[base+c]=wrap16(int(quant[base+c])-previous);
        }
        for(int64_t c=int64_t(chans)-1;c>=0;--c) {
            int sum=0;
            for(int j=0;j<order;++j)
                if(j<c) sum+=SPC_WEIGHTS[Model][j]*int(residual[base+c-j-1]);
            residual[base+c]=wrap16(int(residual[base+c])-floor_div(sum,32));
        }
    }
}

template<int K> static void pack(const int16_t *r, uint64_t n,
                               uint8_t *low, uint8_t *high) {
    const uint64_t m = ((n + 7) / 8) * 8;
    #pragma omp parallel for num_threads(2) if(n>=262144)
    for (uint64_t i=0; i<m; i+=8) {
        uint64_t word=0;
        for (int j=0; j<8; ++j) {
            int v = i+j<n ? r[i+j] : 0;
            uint16_t z = static_cast<uint16_t>(v >= 0 ? 2*v : -2*v-1);
            word |= uint64_t(z & ((1u<<K)-1)) << (j*K);
            uint16_t h = z >> K;
            high[i+j] = static_cast<uint8_t>(h);
            high[m+i+j] = static_cast<uint8_t>(h>>8);
        }
        // Least significant byte first; no unaligned or out-of-bounds stores.
        for (int b=0; b<K; ++b) low[(i/8)*K+b] = word >> (8*b);
    }
}

template<int K> static void unpack(const uint8_t *low, const uint8_t *high,
                                  uint64_t n, int16_t *r) {
    const uint64_t m = ((n + 7) / 8) * 8;
    #pragma omp parallel for num_threads(2) if(n>=262144)
    for (uint64_t i=0; i<m; i+=8) {
        uint64_t word=0;
        for (int b=0; b<K; ++b) word |= uint64_t(low[(i/8)*K+b]) << (8*b);
        for (int j=0; j<8 && i+j<n; ++j) {
            uint16_t h = uint16_t(high[i+j]) | (uint16_t(high[m+i+j])<<8);
            uint16_t z = (uint16_t(h<<K)) | uint16_t((word>>(j*K)) & ((1u<<K)-1));
            r[i+j] = static_cast<int16_t>((z>>1) ^ -int(z&1));
        }
    }
}

extern "C" int spc_encode(const int16_t *input, uint64_t rows, uint32_t chans,
                         int q, int p, int k, uint8_t *low, uint8_t *high) {
    if (!rows || !chans || q<1 || q>32768 || !valid_pred(p) || k<1 || k>8) return -1;
    const uint64_t n=rows*chans;
    const uint32_t width=chans+(p==14);
    const uint64_t nr=rows*width;
    std::vector<int16_t> quant_storage, residual(nr);
    const int16_t *quant=input;
    if(q!=1) {
        quant_storage.resize(n);
        #pragma omp parallel for num_threads(2) if(n>=262144)
        for(uint64_t i=0;i<n;++i) quant_storage[i]=wrap16(floor_div(int(input[i])+q/2,q));
        quant=quant_storage.data();
    }
    if(learned(p)) {
        switch(p-32) {
#define MODEL_ENCODE(M) case M: forward_learned<M>(quant,residual.data(),rows,chans); break;
            SPC_FOR_EACH_MODEL(MODEL_ENCODE)
#undef MODEL_ENCODE
        }
    } else {
    for (uint64_t t=0;t<rows;++t) {
        const uint64_t base=t*chans;
        const uint64_t rb=t*width;
        int64_t sum=0;
        for (uint32_t c=0;c<chans;++c) {
            const int pr=t ? temporal_pred(quant[base+c-chans],p) : 0;
            residual[rb+c]=wrap16(int(quant[base+c])-pr);
            sum+=residual[rb+c];
        }
        if (p==14) {
            int center=int(sum/chans)-(sum<0 && sum%chans!=0);
            residual[rb+chans]=wrap16(center);
            for (uint32_t c=0;c<chans;++c) residual[rb+c]=wrap16(int(residual[rb+c])-center);
        } else if (p==13 || p==15) {
            for (int64_t c=int64_t(chans)-1;c>=0;--c) {
                int spatial=0;
                if (p==13 && c>=2) spatial=floor_div(int(residual[rb+c-2]),2);
                if (p==15) spatial=floor_div((c>=1 ? 2*int(residual[rb+c-1]) : 0)+(c>=2 ? 3*int(residual[rb+c-2]) : 0),8);
                residual[rb+c]=wrap16(int(residual[rb+c])-spatial);
            }
        }
    }
    }
    switch(k) {
#define ENC(K) case K: pack<K>(residual.data(),nr,low,high); break;
        ENC(1) ENC(2) ENC(3) ENC(4) ENC(5) ENC(6) ENC(7) ENC(8)
#undef ENC
    }
    return 0;
}

extern "C" int spc_decode(const uint8_t *low, const uint8_t *high,
                         uint64_t rows, uint32_t chans, int q, int p, int k,
                         int16_t *output) {
    if (!rows || !chans || q<1 || q>32768 || !valid_pred(p) || k<1 || k>8) return -1;
    const uint64_t n=rows*chans;
    const uint32_t width=chans+(p==14);
    const uint64_t nr=rows*width;
    std::vector<int16_t> common;
    if (p==14) common.resize(nr);
    int16_t *residual=p==14 ? common.data() : output;
    switch(k) {
#define DEC(K) case K: unpack<K>(low,high,nr,residual); break;
        DEC(1) DEC(2) DEC(3) DEC(4) DEC(5) DEC(6) DEC(7) DEC(8)
#undef DEC
    }
    if (p==14) {
        for (uint64_t t=0;t<rows;++t) {
            uint64_t base=t*chans,rb=t*width;
            int center=residual[rb+chans];
            for (uint32_t c=0;c<chans;++c) {
                int temporal=wrap16(int(residual[rb+c])+center);
                output[base+c]=wrap16(temporal+(t ? pred(output[base+c-chans],5) : 0));
            }
        }
    } else if(learned(p)) {
        switch(p-32) {
#define MODEL_DECODE(M) case M: inverse_learned<M>(output,rows,chans); break;
            SPC_FOR_EACH_MODEL(MODEL_DECODE)
#undef MODEL_DECODE
        }
    } else if (p==13 || p==15) {
        // Spatial inversion is independent across rows. Temporal inversion is
        // kept in a separate, ordered pass; all operations remain integers.
        #pragma omp parallel for num_threads(2)
        for (uint64_t t=0;t<rows;++t) {
            uint64_t base=t*chans;
            for (uint32_t c=0;c<chans;++c) {
                int spatial=0;
                if (p==13 && c>=2) spatial=floor_div(int(output[base+c-2]),2);
                if (p==15) spatial=floor_div((c>=1 ? 2*int(output[base+c-1]) : 0)+(c>=2 ? 3*int(output[base+c-2]) : 0),8);
                output[base+c]=wrap16(int(output[base+c])+spatial);
            }
        }
        for(uint64_t t=1;t<rows;++t) {
            const uint64_t base=t*chans;
            for(uint32_t c=0;c<chans;++c) output[base+c]=wrap16(int(output[base+c])+temporal_pred(output[base+c-chans],p));
        }
    } else if (p) {
        for (uint64_t t=1;t<rows;++t) {
            const uint64_t base=t*chans;
            // Channels in a row are independent and vectorize naturally.
            for (uint32_t c=0;c<chans;++c)
                output[base+c]=wrap16(int(output[base+c])+pred(output[base+c-chans],p));
        }
    }
    if (q!=1) for (uint64_t i=0;i<n;++i)
        output[i]=static_cast<int16_t>(std::clamp(int(output[i])*q,-32768,32767));
    return 0;
}
