# S0 unconstrained AC baseline snapshot

The central baseline uses V0=1.00 p.u. V0=1.03 and V0=1.05 p.u. are sensitivity cases only.
The solved timestamp is `2011-02-05 18:00:00`, whose normalized Ausgrid load multiplier is 1.0.

The primary calculation is an independent nonlinear radial AC backward/forward sweep with constant-PQ IEEE 33-bus loads. PV, EV, and BESS are zero. No voltage band, branch-current bound, apparent-power rating, transformer rating, export policy, or loss cap is present in the solve. No SOCP model is used for the reported values.

## Raw results

| V0 | role | Vmin (bus) | Vmax (bus) | Psub (kW) | Qsub (kvar) | Ploss (kW) | Qloss (kvar) | iterations |
|---:|:---|:---|:---|---:|---:|---:|---:|---:|
| 1.00 | central baseline | 0.913090479 (18) | 1.000000000 (1) | 3917.677126 | 2435.140971 | 202.677126 | 135.140971 | 26 |
| 1.03 | sensitivity | 0.946034954 (18) | 1.030000000 (1) | 3904.339473 | 2426.230204 | 189.339473 | 126.230204 | 25 |
| 1.05 | sensitivity | 0.967881228 (18) | 1.050000000 (1) | 3896.199837 | 2420.793395 | 181.199837 | 120.793395 | 25 |

## Five lowest-voltage buses at V0=1.00

| bus | voltage (p.u.) |
|---:|---:|
| 18 | 0.913090479361 |
| 17 | 0.913697546157 |
| 16 | 0.915724760079 |
| 33 | 0.916589822134 |
| 32 | 0.916873465734 |

## Five highest-|S| branches at V0=1.00

| branch | from | to | P (kW) | Q (kvar) | |S| (kVA) | current (A) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 1 | 2 | 3917.677126 | 2435.140971 | 4612.819703 | 210.364352 |
| 2 | 2 | 3 | 3444.299179 | 2207.822423 | 4091.170576 | 187.130270 |
| 3 | 3 | 4 | 2362.895188 | 1684.200515 | 2901.690032 | 134.626504 |
| 4 | 4 | 5 | 2222.994711 | 1594.065409 | 2735.461573 | 127.887594 |
| 5 | 5 | 6 | 2144.295769 | 1554.541755 | 2648.509848 | 124.768607 |

## Numerical checks

- V0=1.00: status=CONVERGED; P balance residual=-6.983e-11 kW; Q balance residual=-4.715e-11 kvar; voltage-equation residual=3.307e-14 p.u.; KCL residual=2.776e-17 p.u.; differences from the previous peak snapshot: Vmin=2.936e-12 p.u., Psub=9.744e-08 kW, Qsub=8.582e-08 kvar.
- V0=1.03: status=CONVERGED; P balance residual=-1.340e-10 kW; Q balance residual=-9.167e-11 kvar; voltage-equation residual=6.725e-14 p.u.; KCL residual=2.776e-17 p.u.; differences from the previous peak snapshot: Vmin=1.771e-11 p.u., Psub=6.248e-07 kW, Qsub=5.347e-07 kvar.
- V0=1.05: status=CONVERGED; P balance residual=-1.066e-10 kW; Q balance residual=-7.223e-11 kvar; voltage-equation residual=5.400e-14 p.u.; KCL residual=1.388e-17 p.u.; differences from the previous peak snapshot: Vmin=7.034e-13 p.u., Psub=2.365e-08 kW, Qsub=2.129e-08 kvar.

Runtime: 1.595000 s. The existing 52,608-interval outputs were reused only to identify and cross-check the common-factor peak snapshot; the full period was not recalculated.
