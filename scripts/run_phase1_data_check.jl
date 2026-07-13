include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC

data = build_case33_data()
scenarios = build_core_scenarios()

check_data_consistency(data)
check_radial_network(data.buses, data.branches)

println("CiroPVHC Phase 1 data check")
println("status: OK")
println("buses: $(length(data.buses))")
println("branches: $(length(data.branches))")
println("pv_units: $(length(data.pv_units))")
println("evcs_units: $(length(data.evcs_units))")
println("bess_units: $(length(data.bess_units))")
println("time_steps: $(data.timeseries.T)")
println("dt_hours: $(data.timeseries.dt_hours)")
println("doe_enabled: $(data.doe !== nothing)")
println("scenarios: $(join(string.(getfield.(scenarios, :name)), ", "))")
