### category noise: 10/10 detected

sensor noise x2-x4.5. Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| noise_000 | 4 | 4 | 0 | 0.27 | 0.6 | pass |
| noise_001 | 8 | 8 | 0 | 0.28 | 0.3 | pass |
| noise_002 | 2 | 2 | 0 | 0.28 | 4.0 | pass |
| noise_003 | 8 | 8 | 0 | 0.29 | 1.2 | pass |
| noise_004 | 8 | 8 | 0 | 0.33 | 1.0 | pass |
| noise_005 | 3 | 3 | 0 | 0.30 | 3.4 | pass |
| noise_006 | 5 | 5 | 0 | 0.27 | 1.3 | pass |
| noise_007 | 2 | 2 | 0 | 0.25 | 2.5 | pass |
| noise_008 | 5 | 5 | 0 | 0.39 | 1.1 | pass |
| noise_009 | 5 | 5 | 0 | 0.31 | 0.5 | pass |
