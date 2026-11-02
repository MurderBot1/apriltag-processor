### category blur: 9/10 detected

defocus / motion blur (extra sigma 1-3 px). Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| blur_000 | 8 | 8 | 0 | 0.33 | 0.6 | pass |
| blur_001 | 2 | 2 | 0 | 0.19 | 0.9 | pass |
| blur_002 | 7 | 7 | 0 | 0.37 | 0.4 | pass |
| blur_003 | 5 | 5 | 0 | 0.28 | 0.7 | pass |
| blur_004 | 8 | 8 | 0 | 0.36 | 1.1 | pass |
| blur_005 | 3 | 3 | 0 | 0.55 | 7.9 | pass |
| blur_006 | 2 | 2 | 0 | 0.19 | 1.9 | pass |
| blur_007 | 2 | 2 | 0 | 0.24 | 2.2 | pass |
| blur_008 | 7 | 7 | 0 | 0.32 | 0.7 | pass |
| blur_009 | 8 | 5 | 0 | 0.47 | 3.3 | FAIL (missed [3, 77, 101]) |
