### category persp: 7/10 detected

tag plane tilted 15-74 deg (yaw / pitch). Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| persp_000 | 8 | 8 | 1 | 0.31 | 0.7 | FAIL |
| persp_001 | 8 | 8 | 0 | 0.28 | 0.7 | pass |
| persp_002 | 6 | 6 | 0 | 0.26 | 0.7 | pass |
| persp_003 | 5 | 5 | 0 | 0.49 | 0.7 | pass |
| persp_004 | 6 | 6 | 0 | 0.31 | 0.4 | pass |
| persp_005 | 8 | 8 | 0 | 0.30 | 0.6 | pass |
| persp_006 | 7 | 7 | 0 | 0.32 | 1.4 | pass |
| persp_007 | 3 | 3 | 0 | 0.38 | 3.7 | pass |
| persp_008 | 8 | 6 | 0 | 0.32 | 0.8 | FAIL (missed [17, 101]) |
| persp_009 | 7 | 5 | 0 | 0.33 | 1.6 | FAIL (missed [77, 101]) |
