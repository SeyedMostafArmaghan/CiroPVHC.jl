# Locked S1 decisions

1. **PV siting:** buses 13, 20, 24 and 30 are a screening shortlist, not optimal siting.
2. **Time resolution:** 48 half-hour intervals per day; `Δt = 0.5 h` everywhere.
3. **Baseline voltage:** nominal substation voltage `V0 = 1.03 p.u.`; sensitivity at 1.00 and 1.05; operating band 0.95–1.05 p.u.
4. **Temporal data:** normalized load and gross-PV shapes from the three-year Ausgrid Solar Home dataset; absolute loads from `case33bw`.
5. **S1 homogeneity:** a common aggregate profile is applied to all buses; spatial-profile heterogeneity is postponed.
6. **Critical periods:** rank all complete days by normalized PV-to-load stress; solve the network model on top 10/20/30 day sets and test HC convergence rather than assuming one day is sufficient.
7. **Line ratings:** current-based calibrated planning assumptions using `ell`; not represented as real IEEE 33-bus ratings.
8. **Transformer:** a separate apparent-power limit and independent sensitivity factor.
9. **S1-B electrical HC:** export allowed, zero curtailment, no no-export constraint, no 10% loss cap, nonbinding numerical site guards only, automatic binding-constraint extraction.
10. **S1-C policy:** no-export, curtailment 0/2/5/10%, export-limit and gamma-cap sensitivities; archived 2766.97 kW is policy-limited.
