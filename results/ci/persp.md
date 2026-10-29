### category persp: 7/10 detected

tag plane tilted 15-74 deg (yaw / pitch). Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| persp_000 | 9 | 9 | 0 | 0.26 | 0.9 | pass |
| persp_001 | 8 | 8 | 0 | 0.24 | 0.6 | pass |
| persp_002 | 6 | 6 | 0 | 0.22 | 0.3 | pass |
| persp_003 | 7 | 7 | 0 | 0.26 | 0.5 | pass |
| persp_004 | 8 | 8 | 0 | 0.26 | 0.5 | pass |
| persp_005 | 8 | 8 | 0 | 0.26 | 0.6 | pass |
| persp_006 | 8 | 6 | 0 | 0.24 | 0.4 | FAIL (missed [58, 202]) |
| persp_007 | 3 | 3 | 0 | 0.33 | 4.6 | pass |
| persp_008 | 8 | 6 | 0 | 0.28 | 0.8 | FAIL (missed [17, 101]) |
| persp_009 | 7 | 5 | 0 | 0.36 | 1.7 | FAIL (missed [77, 101]) |
