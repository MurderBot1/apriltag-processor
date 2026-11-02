### category shadow: 7/10 detected

harsh cast shadow over a tag. Reference detector (pupil-apriltags tag36h11 after undistortion); a frame passes when every ground-truth-detectable tag is found and no false id is reported. The RTL chain is not run in CI (about 40 s per frame).

| image | detectable tags | found | false ids | corner err px | pose err mm | result |
|---|---|---|---|---|---|---|
| shadow_000 | 2 | 2 | 0 | 0.24 | 11.3 | pass |
| shadow_001 | 4 | 4 | 0 | 0.40 | 0.7 | pass |
| shadow_002 | 2 | 1 | 0 | 0.27 | 19.8 | FAIL (missed [311]) |
| shadow_003 | 6 | 6 | 0 | 0.29 | 0.2 | pass |
| shadow_004 | 2 | 2 | 0 | 0.28 | 10.5 | pass |
| shadow_005 | 9 | 9 | 0 | 0.32 | 0.3 | pass |
| shadow_006 | 6 | 5 | 0 | 0.29 | 0.6 | FAIL (missed [58]) |
| shadow_007 | 8 | 8 | 0 | 0.27 | 0.6 | pass |
| shadow_008 | 2 | 1 | 0 | 0.26 | 6.4 | FAIL (missed [250]) |
| shadow_009 | 1 | 1 | 0 | 0.30 | 6.5 | pass |
