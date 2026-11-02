### category clutter: 8/10 detected

busy background + 3-22 occluding objects. Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| clutter_000 | 4 | 4 | 1 | 0.28 | 0.6 | FAIL |
| clutter_001 | 2 | 2 | 0 | 0.22 | 8.7 | pass |
| clutter_002 | 5 | 5 | 0 | 0.32 | 0.4 | pass |
| clutter_003 | 6 | 6 | 0 | 0.27 | 0.4 | pass |
| clutter_004 | 2 | 2 | 0 | 0.37 | 5.2 | pass |
| clutter_005 | 6 | 6 | 0 | 0.29 | 0.5 | pass |
| clutter_006 | 9 | 9 | 0 | 0.29 | 0.7 | pass |
| clutter_007 | 5 | 5 | 1 | 0.30 | 0.1 | FAIL |
| clutter_008 | 7 | 7 | 0 | 0.29 | 0.4 | pass |
| clutter_009 | 5 | 5 | 0 | 0.26 | 0.4 | pass |
