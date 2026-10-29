import sys,numpy as np,cv2
sys.path.insert(0,'tests'); sys.path.insert(0,'tools')
import rtlutil, golden, ccl_check
vvp=rtlutil.build('tb_ccl',['rtl/run_ccl.v','tb/tb_ccl.v'])
m=np.fromfile('sim/synth1.mask',np.uint8).reshape(800,1280).astype(bool)
keep,lab,allc=golden.components(m)
print('golden comps',len(allc),'kept',len(keep))
out=rtlutil.run(vvp,['mask=sim/synth1.mask','out=sim/synth1.cand']); print(out[:300])
recs=ccl_check.parse_dump('sim/synth1.cand')
errs=ccl_check.compare(recs,keep,lab); print('errors',len(errs),errs[:5])
