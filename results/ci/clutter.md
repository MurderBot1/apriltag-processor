### category clutter: 10/10 detected

busy background + 3-22 occluding objects. Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| clutter_000 | 5 | 5 | 0 | 0.24 | 0.5 | pass |
| clutter_001 | 3 | 3 | 0 | 0.24 | 2.5 | pass |
| clutter_002 | 5 | 5 | 0 | 0.26 | 0.4 | pass |
| clutter_003 | 6 | 6 | 0 | 0.25 | 0.4 | pass |
| clutter_004 | 2 | 2 | 0 | 0.34 | 2.9 | pass |
| clutter_005 | 7 | 7 | 0 | 0.26 | 0.8 | pass |
| clutter_006 | 10 | 10 | 0 | 0.25 | 0.8 | pass |
| clutter_007 | 8 | 8 | 0 | 0.24 | 0.2 | pass |
| clutter_008 | 7 | 7 | 0 | 0.24 | 0.7 | pass |
| clutter_009 | 6 | 6 | 0 | 0.22 | 0.2 | pass |
