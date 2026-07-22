using Dates

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(REPOSITORY_ROOT, "src", "benchmark", "s1b_method_benchmark.jl"))
using .S1BMethodBenchmark

"--confirm-full-period" in ARGS || error(
    "This is the 52,608-interval production run. Re-run with --confirm-full-period after reviewing the configuration.",
)

const OUTPUT_DIRECTORY = joinpath(REPOSITORY_ROOT, "results", "s1b_ac_constraint_generation")
mkpath(OUTPUT_DIRECTORY)

data = load_full_benchmark_data(REPOSITORY_ROOT)
config = ACConstraintGenerationConfig(
    OUTPUT_DIRECTORY;
    batch_size=3,
    max_iterations=20,
    voltage_tolerance_pu=AC_VOLTAGE_TOL,
    maximum_replay_failures=0,
    resume=true,
    seed=MULTISTART_SEED,
)

open(joinpath(OUTPUT_DIRECTORY, "production_configuration.txt"), "w") do io
    println(io, "study=S1-B full-period exact-AC constraint generation")
    println(io, "classification=nonconvex branch-flow AC model for a balanced radial feeder")
    println(io, "result_label=voltage-only hosting capacity with unconstrained upstream exchange")
    println(io, "global_optimum_claimed=false")
    println(io, "thermal_hosting_capacity_claimed=false")
    println(io, "interval_count=$(length(data.indices))")
    println(io, "initial_active_indices=$(join(deterministic_seed_indices(data), ';'))")
    println(io, "batch_size=$(config.batch_size)")
    println(io, "max_iterations=$(config.max_iterations)")
    println(io, "voltage_tolerance_pu=$(config.voltage_tolerance_pu)")
    println(io, "maximum_replay_failures=$(config.maximum_replay_failures)")
    println(io, "resume=$(config.resume)")
    println(io, "multistart_seed=$(config.seed)")
end

result = run_ac_constraint_generation(data, config)
println("status=$(result.status)")
println("completed_iterations=$(result.completed_iterations)")
println("active_interval_count=$(length(result.active_indices))")
