"""Candidate selection sweep (golden models + TPU ISS): shape prefilter, ordering and cap when the CCL does not reject overflowing frames.
Assumes run capacity >= 192/row and label recycling (see results/noise_sweep.md)."""
import sys; sys.path.insert(0,'tests'); sys.path.insert(0,'tools')
import sweep_noise as S, golden, tpu_harness, cv2, numpy as np
from multiprocessing import Pool
from tpu_harness import Machine, PROG, CODES, parse_results
def run(a):
    n,v=a
    img=cv2.imread(f'test_images/sensor/{n}.png',0); m=S.pipeline(img,v)
    keep,lab,_=golden.components(m,min_area=v.get('min_area',100),min_dim=10)
    def ok(c):
        bw,bh=c['x1']-c['x0']+1,c['y1']-c['y0']+1
        fill=c['area']/(bw*bh); asp=max(bw,bh)/min(bw,bh)
        return v.get('fmin',0)<=fill<=v.get('fmax',1) and asp<=v.get('asp',99)
    k2=[c for c in keep if ok(c)]
    ncand=len(k2)
    so=v.get('sort')
    if so=='area': k2=sorted(k2,key=lambda c:-c['area'])
    if so=='bbox': k2=sorted(k2,key=lambda c:-max(c['x1']-c['x0'],c['y1']-c['y0']))
    k2=k2[:v.get('cap',64)]
    words=golden.pack_records(k2,lab); cand=words+[0]*(1024-len(words)); h,w=m.shape
    pix=lambda x,y:int(m[y,x]) if 0<=x<w and 0<=y<h else 0
    mc=Machine(PROG,CODES,pix,cand,dict(frame_id=1,maxham=2,cand_count=len(k2),minside=8)); mc.run()
    ids={t['id'] for t in parse_results(mc.res)}
    vis={int(t) for t,x in S.GT[n]['tags'].items() if x.get('detectable',x['visible'])}
    known={int(k) for k in S.GT[n]['tags']}
    return len(vis&ids),len(vis),len(ids-known),ncand,mc.cycles
if __name__=='__main__':
    names=sorted(S.GT)
    for nm,v in [('label order',{}),('area desc cap64',dict(sort='area')),('area desc cap32',dict(sort='area',cap=32)),('area desc cap128',dict(sort='area',cap=128)),('area desc cap256',dict(sort='area',cap=256)),('label cap128',dict(cap=128)),('bbox desc cap64',dict(sort='bbox')),('area desc cap64 minarea150',dict(sort='area',min_area=150))]:
        with Pool(20) as p: r=p.map(run,[(n,v) for n in names])
        f=sum(x[0] for x in r);t=sum(x[1] for x in r)
        print(f'{nm:30s} found {f}/{t} ({f/t:.1%}) false {sum(x[2] for x in r)}  frames cand>64: {sum(x[3]>64 for x in r)}  max cycles {max(x[4] for x in r)}',flush=True)
