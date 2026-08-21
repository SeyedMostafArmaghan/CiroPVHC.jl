# VMIN h_design retreat diagnostic

This is an interpretation of committed artifacts only. It performs no AC calculation.

## Locked limits

- Original voltage band: `0.90000 <= V <= 1.05000` p.u.
- Symmetric design band: `0.90015 <= V <= 1.04985` p.u.
- Locked safety headroom: `h_design = 0.00015` p.u.

## VMIN-bound blockers

| timestamp | edge_id | blocking phase | initial d (kW) | initial VMIN (p.u.) | original-limit margin (p.u.) | design margin (p.u.) | maximum tested d (kW) | VMIN at maximum d (p.u.) |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| 2010-07-02 17:30:00 | E0044 | ANCHOR_SEARCH | 0 | 0.900007215994425 | 7.21599442499166e-06 | -0.000142784005574992 | 4096 | 0.843795917250167 |
| 2010-07-02 18:00:00 | E0044 | VERIFY_ESCALATE | 4.75 | 0.899996208231859 | -3.791768141026e-06 | -0.000153791768141009 | 68.75 | 0.899931224392152 |
| 2011-05-16 07:30:00 | E0045 | ANCHOR_SEARCH | 0 | 0.90000168656595 | 1.68656595000982e-06 | -0.000148313434049974 | 2048 | 0.875583615456429 |
| 2012-10-15 13:00:00 | E0046 | ANCHOR_SEARCH | 0 | 0.900000084652109 | 8.46521089892249e-08 | -0.000149915347890994 | 4096 | 0.841263737219851 |

## Interpretation

Three of the four VMIN-bound blocking trajectories are anchor searches observed from `d=0`; each starts above the original 0.90 p.u. limit but below the 0.90015 p.u. design limit. Their initial need for retreat is therefore attributable to the locked safety-headroom requirement.

The 2010-07-02 18:00 E0044 trajectory is a verify-escalation search first observed at the already-selected common retreat `d=4.75` kW, where VMIN is 0.899996208231859 p.u. The calibration attempts contain no `d=0` observation for that blocking membership. Its initial safety-headroom-only contribution therefore cannot be isolated from these artifacts; at the first available observation it already fails the original VMIN limit.

For every VMIN-bound blocker, increasing the registered positive scalar retreat lowers VMIN monotonically over the observed sequence while VMAX margin improves. For the three `d=0` anchor cases, the need for a retreat is caused by `h_design`; the inability of the observed positive parallel retreat to supply that headroom is a geometric/operator-direction difficulty. These are separate statements.

The artifacts do not prove behavior at every untested retreat or under any alternative direction. They do show that the tested registered direction moves the binding VMIN channel away from the design band.
