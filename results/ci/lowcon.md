### category lowcon: 9/10 detected

low contrast (24-42 % of nominal). Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| lowcon_000 | 7 | 7 | 0 | 0.34 | 0.6 | pass |
| lowcon_001 | 1 | 1 | 0 | 0.24 | 8.7 | pass |
| lowcon_002 | 8 | 8 | 0 | 0.31 | 0.4 | pass |
| lowcon_003 | 2 | 2 | 1 | 0.30 | 2.1 | FAIL |
| lowcon_004 | 8 | 8 | 0 | 0.32 | 0.4 | pass |
| lowcon_005 | 4 | 4 | 0 | 0.26 | 0.6 | pass |
| lowcon_006 | 6 | 6 | 0 | 0.28 | 0.7 | pass |
| lowcon_007 | 6 | 6 | 0 | 0.35 | 2.3 | pass |
| lowcon_008 | 5 | 5 | 0 | 0.41 | 0.8 | pass |
| lowcon_009 | 7 | 7 | 0 | 0.36 | 1.2 | pass |
