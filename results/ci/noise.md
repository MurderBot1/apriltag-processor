### category noise: 10/10 detected

sensor noise x2-x4.5. Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| noise_000 | 5 | 5 | 0 | 0.25 | 0.4 | pass |
| noise_001 | 8 | 8 | 0 | 0.25 | 0.5 | pass |
| noise_002 | 2 | 2 | 0 | 0.24 | 4.8 | pass |
| noise_003 | 8 | 8 | 0 | 0.27 | 0.7 | pass |
| noise_004 | 8 | 8 | 0 | 0.27 | 0.8 | pass |
| noise_005 | 4 | 4 | 0 | 0.25 | 0.8 | pass |
| noise_006 | 7 | 7 | 0 | 0.31 | 0.9 | pass |
| noise_007 | 3 | 3 | 0 | 0.31 | 1.8 | pass |
| noise_008 | 6 | 6 | 0 | 0.32 | 0.5 | pass |
| noise_009 | 6 | 6 | 0 | 0.32 | 0.6 | pass |
