function build_core_scenarios()
    return [
        ScenarioConfig(:S1, "PV only", true, false, false, false, false, false, :none),
        ScenarioConfig(:S2, "PV + unmanaged EV", true, true, false, false, false, false, :none),
        ScenarioConfig(:S3, "PV + smart EV via TVPP", true, false, true, false, false, false, :none),
        ScenarioConfig(:S4, "PV + smart EV + BESS", true, false, true, true, false, false, :none),
        ScenarioConfig(:S5, "PV + smart EV + BESS + DOE", true, false, true, true, true, false, :none),
        ScenarioConfig(:R1, "Robust S5 with low uncertainty", true, false, true, true, true, true, :low),
        ScenarioConfig(:R2, "Robust S5 with medium uncertainty", true, false, true, true, true, true, :medium),
        ScenarioConfig(:R3, "Robust S5 with high uncertainty", true, false, true, true, true, true, :high),
    ]
end
