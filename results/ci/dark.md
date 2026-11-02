### category dark: 9/10 detected

under-exposed (light x0.03-x0.25). Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| dark_000 | 7 | 7 | 0 | 0.27 | 0.4 | pass |
| dark_001 | 6 | 6 | 0 | 0.28 | 0.2 | pass |
| dark_002 | 5 | 5 | 0 | 0.29 | 0.3 | pass |
| dark_003 | 6 | 6 | 0 | 0.33 | 0.5 | pass |
| dark_004 | 5 | 5 | 1 | 0.30 | 0.4 | FAIL |
| dark_005 | 3 | 3 | 0 | 0.29 | 0.8 | pass |
| dark_006 | 9 | 9 | 0 | 0.30 | 0.5 | pass |
| dark_007 | 2 | 2 | 0 | 0.22 | 2.6 | pass |
| dark_008 | 8 | 8 | 0 | 0.24 | 0.5 | pass |
| dark_009 | 8 | 8 | 0 | 0.24 | 0.4 | pass |
