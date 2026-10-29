### category shadow: 7/10 detected

harsh cast shadow over a tag. Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| shadow_000 | 2 | 2 | 0 | 0.23 | 3.0 | pass |
| shadow_001 | 5 | 5 | 0 | 0.26 | 0.5 | pass |
| shadow_002 | 3 | 2 | 0 | 0.25 | 3.1 | FAIL (missed [311]) |
| shadow_003 | 7 | 7 | 0 | 0.22 | 0.2 | pass |
| shadow_004 | 3 | 3 | 0 | 0.31 | 4.8 | pass |
| shadow_005 | 10 | 10 | 0 | 0.26 | 0.4 | pass |
| shadow_006 | 6 | 5 | 0 | 0.25 | 0.6 | FAIL (missed [58]) |
| shadow_007 | 8 | 8 | 0 | 0.26 | 0.8 | pass |
| shadow_008 | 2 | 1 | 0 | 0.23 | 5.9 | FAIL (missed [250]) |
| shadow_009 | 1 | 1 | 0 | 0.22 | 4.5 | pass |
