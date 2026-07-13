import Pkg
Pkg.activate(joinpath(@__DIR__, ".."); io=devnull)

include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC

data = build_case33_data()
result = solve_s1_pv_only(data)

println("CiroPVHC S1 PV-only SOCP hosting-capacity check")
println("termination_status: $(result.termination_status)")
println("objective_value: $(round(result.objective_value; digits=4))")
println("total_pv_capacity_kw: $(round(result.total_pv_capacity_kw; digits=4))")
println("voltage_min: $(round(result.voltage_min; digits=5))")
println("voltage_max: $(round(result.voltage_max; digits=5))")
println("max_line_loading: $(round(result.max_line_loading; digits=5))")
println("pv_capacity_by_unit:")
for (id, capacity_kw) in sort(collect(result.pv_capacity_by_unit); by=first)
    println("  PV$(id): $(round(capacity_kw; digits=4)) kW")
end
