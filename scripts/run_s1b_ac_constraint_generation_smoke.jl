using Dates

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(REPOSITORY_ROOT, "src", "benchmark", "s1b_method_benchmark.jl"))
using .S1BMethodBenchmark

const OUTPUT_DIRECTORY = joinpath(REPOSITORY_ROOT, "results", "s1b_ac_constraint_generation_smoke")
mkpath(OUTPUT_DIRECTORY)

full_data = load_full_benchmark_data(REPOSITORY_ROOT)
selected_indices = smoke_validation_indices(full_data)
data = subset_benchmark_data(full_data, selected_indices)
config = ACConstraintGenerationConfig(
    OUTPUT_DIRECTORY;
    batch_size=3,
    max_iterations=3,
    voltage_tolerance_pu=AC_VOLTAGE_TOL,
    maximum_replay_failures=0,
    resume="--resume" in ARGS,
    seed=MULTISTART_SEED,
)
result = run_ac_constraint_generation(data, config)

dates = unique(Date.(data.profile.timestamps[data.indices]))
seeds = deterministic_seed_indices(data)
seed_text = join(("$(index)=$(data.profile.timestamps[index])" for index in seeds), ", ")
open(joinpath(OUTPUT_DIRECTORY, "smoke_report.md"), "w") do io
    println(io, "# S1-B AC constraint-generation smoke report")
    println(io)
    println(io, "- Classification: nonconvex branch-flow AC model for a balanced radial feeder.")
    println(io, "- Result label: **voltage-only hosting capacity with unconstrained upstream exchange.**")
    println(io, "- Global optimum claimed: no.")
    println(io, "- Transformer or thermal hosting capacity claimed: no; no defensible substation rating is available.")
    println(io, "- Validation scope: $(length(data.indices)) half-hour intervals on $(join(dates, ", ")).")
    println(io, "- High-load day: 2011-02-05; low-load/high-PV day: 2012-10-15.")
    println(io, "- Deterministic seed intervals: $(seed_text).")
    println(io, "- Full 52,608-interval validation performed: no.")
    println(io, "- Terminal status: `$(result.status)`.")
    println(io, "- Completed iterations: $(result.completed_iterations).")
    println(io, "- Final active interval count: $(length(result.active_indices)).")
    println(io, "- Resumed from the persisted checkpoint: $(result.resumed ? "yes" : "no").")
    println(io)
    println(io, "All start statuses, acceptance flags, and objectives are retained in `iteration_summary.csv`; detailed per-start and per-interval evidence is retained in the ignored `checkpoints/` directory.")
end

println("status=$(result.status)")
println("completed_iterations=$(result.completed_iterations)")
println("validation_intervals=$(length(data.indices))")
