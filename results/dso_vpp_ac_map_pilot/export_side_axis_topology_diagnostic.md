# AC-anchored topology-sensitivity diagnostic

This is a topology-only first-order diagnostic, not classical LinDistFlow and not a LinDistFlow validation. The code verified the radial parent structure, slack bus 1, root-to-leaf orientation, IEEE-33 bus numbering, 12.66-kV base, 10-MVA/10,000-kW power base, ohm-to-per-unit conversion, and positive branch resistance.

- Axis 13: limiting timestamp 2012-10-15 13:00:00, safe AC capacity 681.370544434 kW, safe/violating maximum-voltage sets `13`/`13`.
- Axis 30: limiting timestamp 2012-10-15 13:00:00, safe AC capacity 1739.59228516 kW, safe/violating maximum-voltage sets `30`/`30`.

The axes have different candidate binding buses, so the single-ratio formula is not applicable. Separate AC-anchored predictions use (1.05^2-v_i^AC(0))/c_i,k in consistent per-unit quantities. Discrepancy is diagnostic only and does not imply causality or rejection of the AC model.
