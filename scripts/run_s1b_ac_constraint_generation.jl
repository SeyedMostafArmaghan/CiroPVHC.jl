using Dates
using SHA
using TOML

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(REPOSITORY_ROOT, "src", "benchmark", "s1b_method_benchmark.jl"))
using .S1BMethodBenchmark

"--confirm-full-period" in ARGS || error(
    "This is the 52,608-interval production run. Re-run with --confirm-full-period after reviewing the configuration.",
)

const OUTPUT_DIRECTORY = joinpath(REPOSITORY_ROOT, "results", "s1b_ac_constraint_generation")
const PROFILE_PATH = joinpath(
    REPOSITORY_ROOT, "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv",
)
const CONFIGURATION_PATH = joinpath(
    REPOSITORY_ROOT, "config", "s1b_ac_constraint_generation_production.toml",
)
mkpath(OUTPUT_DIRECTORY)

data = load_full_benchmark_data(REPOSITORY_ROOT)
production = TOML.parsefile(CONFIGURATION_PATH)
config = ACConstraintGenerationConfig(
    OUTPUT_DIRECTORY;
    batch_size=production["batch_size"],
    max_iterations=production["max_iterations"],
    voltage_tolerance_pu=production["voltage_tolerance_pu"],
    maximum_replay_failures=production["maximum_replay_failures"],
    resume=production["resume"],
    seed=production["multistart_seed"],
)

timestamps = data.profile.timestamps[data.indices]
dates = Date.(timestamps)
day_counts = Dict(date => count(==(date), dates) for date in unique(dates))
length(data.indices) == production["validation_intervals"] == 52_608 ||
    error("production profile must contain exactly 52,608 intervals")
length(day_counts) == 1_096 && all(==(48), values(day_counts)) ||
    error("production profile must contain exactly 1,096 complete days")
all(diff(timestamps) .== Minute(30)) || error("production profile is not contiguous half-hour data")
CANDIDATE_BUSES == (13, 20, 24, 30) || error("unexpected production PV bus set")
S1BMethodBenchmark.VMIN_PU == 0.90 && S1BMethodBenchmark.VMAX_PU == 1.05 ||
    error("unexpected production voltage bounds")
config.voltage_tolerance_pu == AC_VOLTAGE_TOL || error("production voltage tolerance mismatch")
config.maximum_replay_failures == 0 || error("production replay failures must be zero")
config.resume || error("production checkpoint resume must be enabled")
config.seed == MULTISTART_SEED || error("production deterministic seed mismatch")
production["curtailment"] == false || error("production curtailment must be disabled")
production["upstream_export_allowed"] == true || error("upstream exchange must be unconstrained")
production["site_cap_active"] == false || error("production site cap must be disabled")
production["thermal_constraints_active"] == false || error("production thermal limits must be disabled")
production["transformer_constraint_active"] == false || error("production transformer limit must be disabled")
production["global_optimum_claimed"] == false || error("production cannot claim global optimality")

if "--preflight-only" in ARGS
    println("production_entry_point_preflight=passed")
    println("interval_count=$(length(data.indices))")
    println("complete_day_count=$(length(day_counts))")
    exit(0)
end

started_at_utc = now(UTC)
profile_sha256 = bytes2hex(open(sha256, PROFILE_PATH))

open(joinpath(OUTPUT_DIRECTORY, "production_configuration.txt"), "w") do io
    println(io, "study=S1-B full-period exact-AC constraint generation")
    println(io, "classification=nonconvex branch-flow AC model for a balanced radial feeder")
    println(io, "result_label=voltage-only hosting capacity with unconstrained upstream exchange")
    println(io, "global_optimum_claimed=false")
    println(io, "thermal_hosting_capacity_claimed=false")
    println(io, "production_command=julia --project=. scripts/run_s1b_ac_constraint_generation.jl --confirm-full-period")
    println(io, "explicit_confirmation_flag=--confirm-full-period")
    println(io, "started_at_utc=$(started_at_utc)")
    println(io, "input_profile_path=$(relpath(PROFILE_PATH, REPOSITORY_ROOT))")
    println(io, "input_profile_sha256=$(profile_sha256)")
    println(io, "interval_count=$(length(data.indices))")
    println(io, "complete_day_count=$(length(day_counts))")
    println(io, "interval_hours=0.5")
    println(io, "candidate_buses=$(join(CANDIDATE_BUSES, ';'))")
    println(io, "voltage_min_pu=$(S1BMethodBenchmark.VMIN_PU)")
    println(io, "voltage_max_pu=$(S1BMethodBenchmark.VMAX_PU)")
    println(io, "curtailment=false")
    println(io, "shared_installed_capacities=true")
    println(io, "initial_active_indices=$(join(deterministic_seed_indices(data), ';'))")
    println(io, "batch_size=$(config.batch_size)")
    println(io, "max_iterations=$(config.max_iterations)")
    println(io, "voltage_tolerance_pu=$(config.voltage_tolerance_pu)")
    println(io, "maximum_replay_failures=$(config.maximum_replay_failures)")
    println(io, "resume=$(config.resume)")
    println(io, "multistart_seed=$(config.seed)")
end

result = run_ac_constraint_generation(data, config)
open(joinpath(OUTPUT_DIRECTORY, "production_configuration.txt"), "a") do io
    println(io, "finished_at_utc=$(now(UTC))")
    println(io, "terminal_status=$(result.status)")
    println(io, "completed_iterations=$(result.completed_iterations)")
    println(io, "final_active_interval_count=$(length(result.active_indices))")
end
println("status=$(result.status)")
println("completed_iterations=$(result.completed_iterations)")
println("active_interval_count=$(length(result.active_indices))")
