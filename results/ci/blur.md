### category blur: 9/10 detected

defocus / motion blur (extra sigma 1-3 px). Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| blur_000 | 8 | 8 | 0 | 0.27 | 0.7 | pass |
| blur_001 | 3 | 3 | 0 | 0.25 | 1.3 | pass |
| blur_002 | 8 | 8 | 0 | 0.28 | 0.4 | pass |
| blur_003 | 6 | 6 | 0 | 0.31 | 0.5 | pass |
| blur_004 | 8 | 8 | 0 | 0.32 | 1.2 | pass |
| blur_005 | 6 | 6 | 0 | 0.31 | 0.8 | pass |
| blur_006 | 2 | 2 | 0 | 0.28 | 2.8 | pass |
| blur_007 | 2 | 2 | 0 | 0.35 | 4.2 | pass |
| blur_008 | 8 | 8 | 0 | 0.49 | 0.7 | pass |
| blur_009 | 8 | 0 | 0 | - | - | FAIL (missed [3, 17, 42, 58, 77, 101, 133, 202]) |
