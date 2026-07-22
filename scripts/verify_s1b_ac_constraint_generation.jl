using Dates
using Printf
using SHA
using TOML

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(REPOSITORY_ROOT, "src", "benchmark", "s1b_method_benchmark.jl"))
using .S1BMethodBenchmark

"--confirm-full-period" in ARGS || error(
    "This independently replays all 52,608 intervals. Re-run with --confirm-full-period.",
)

const OUTPUT_DIRECTORY = joinpath(REPOSITORY_ROOT, "results", "s1b_ac_constraint_generation")
const PROFILE_PATH = joinpath(
    REPOSITORY_ROOT, "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv",
)
const CONFIGURATION_PATH = joinpath(
    REPOSITORY_ROOT, "config", "s1b_ac_constraint_generation_production.toml",
)

function read_key_values(path)
    values = Dict{String,String}()
    for line in eachline(path)
        parts = split(line, '='; limit=2)
        length(parts) == 2 && (values[parts[1]] = parts[2])
    end
    return values
end

function parse_csv(path)
    lines = readlines(path)
    isempty(lines) && return NamedTuple[]
    header = Symbol.(S1BMethodBenchmark._cg_parse_csv_line(lines[1]))
    return [NamedTuple{Tuple(header)}(Tuple(S1BMethodBenchmark._cg_parse_csv_line(line)))
            for line in lines[2:end]]
end

production = TOML.parsefile(CONFIGURATION_PATH)
data = load_full_benchmark_data(REPOSITORY_ROOT)
length(data.indices) == 52_608 || error("independent verification requires 52,608 intervals")
config = ACConstraintGenerationConfig(
    OUTPUT_DIRECTORY;
    batch_size=production["batch_size"],
    max_iterations=production["max_iterations"],
    voltage_tolerance_pu=production["voltage_tolerance_pu"],
    maximum_replay_failures=production["maximum_replay_failures"],
    resume=production["resume"],
    seed=production["multistart_seed"],
)
signature = S1BMethodBenchmark._cg_signature(data, config)
state = S1BMethodBenchmark._cg_read_state(config, signature)
state === nothing && error("production checkpoint is absent")
isempty(state.terminal_status) && error("production checkpoint is not terminal")
history = S1BMethodBenchmark._cg_read_history(config)
length(history) == state.completed_iteration || error("history/checkpoint iteration mismatch")

active_set_monotone = all(row.active_after >= row.active_before for row in history) &&
    all(history[index].active_before == history[index - 1].active_after
        for index in 2:length(history)) &&
    history[end].active_after == length(state.active_indices)
checkpoint_allocation_matches = all(
    isapprox(state.capacities_kw[bus], getproperty(history[end], Symbol("c$(bus)_kw")); atol=1e-8, rtol=0.0)
    for bus in CANDIDATE_BUSES
)

finite_allocation = all(isfinite, values(state.capacities_kw))
verification_started = now(UTC)
replay_started = time()
replay_rows = finite_allocation ? [
    S1BMethodBenchmark._cg_replay_interval(
        data, local_t, state.capacities_kw;
        voltage_tolerance_pu=config.voltage_tolerance_pu,
    ) for local_t in eachindex(data.indices)
] : NamedTuple[]
verification_replay_seconds = time() - replay_started
verification_finished = now(UTC)

replay_columns = (
    "global_index", "timestamp", "converged", "phasor_recoverable",
    "maximum_equation_residual", "maximum_scaled_residual",
    "vmin_pu", "vmin_bus", "vmax_pu", "vmax_bus", "violation_pu",
    "violation_type", "violation_bus", "load_multiplier", "pv_factor",
    "substation_p_kw", "substation_q_kvar", "upstream_apparent_kva",
    "replay_passed", "failure_reason",
)
S1BMethodBenchmark._cg_write_csv(
    joinpath(OUTPUT_DIRECTORY, "checkpoints", "final_verification_replay.csv"),
    replay_columns,
    [Tuple(getproperty(row, Symbol(column)) for column in replay_columns) for row in replay_rows],
)

replay_failures = count(row -> !isfinite(row.violation_pu), replay_rows)
voltage_violations = count(row -> isfinite(row.violation_pu) && row.violation_pu > 0.0, replay_rows)
verification_passed = length(replay_rows) == 52_608 && replay_failures == 0 &&
                      voltage_violations == 0 && active_set_monotone &&
                      checkpoint_allocation_matches
if state.terminal_status == "converged" && !verification_passed
    error("terminal convergence claim failed clean-process independent verification")
end

binding_entries = NamedTuple[]
minimum_margin = NaN
binding_reproducible = false
if !isempty(replay_rows)
    margin_entries = NamedTuple[]
    for row in replay_rows
        push!(margin_entries, (row=row, constraint="minimum_voltage", bus=row.vmin_bus,
                               voltage=row.vmin_pu, limit=S1BMethodBenchmark.VMIN_PU,
                               margin=row.vmin_pu - S1BMethodBenchmark.VMIN_PU))
        push!(margin_entries, (row=row, constraint="maximum_voltage", bus=row.vmax_bus,
                               voltage=row.vmax_pu, limit=S1BMethodBenchmark.VMAX_PU,
                               margin=S1BMethodBenchmark.VMAX_PU - row.vmax_pu))
    end
    minimum_margin = minimum(entry.margin for entry in margin_entries)
    binding_entries = [entry for entry in margin_entries
                       if entry.margin <= minimum_margin + 1e-8]
    binding_reproducible = all(binding_entries) do entry
        local_t = findfirst(==(entry.row.global_index), data.indices)
        repeated = S1BMethodBenchmark._cg_replay_interval(
            data, local_t, state.capacities_kw;
            voltage_tolerance_pu=config.voltage_tolerance_pu,
        )
        repeated_voltage = entry.constraint == "minimum_voltage" ? repeated.vmin_pu : repeated.vmax_pu
        repeated_bus = entry.constraint == "minimum_voltage" ? repeated.vmin_bus : repeated.vmax_bus
        repeated_bus == entry.bus && isapprox(repeated_voltage, entry.voltage; atol=1e-10, rtol=0.0)
    end
end

binding_columns = (
    "global_index", "timestamp", "constraint", "bus", "voltage_pu", "limit_pu",
    "margin_pu", "load_multiplier", "pv_factor", "substation_p_kw",
    "substation_q_kvar", "upstream_apparent_kva", "reproduced",
)
binding_rows = [(
    entry.row.global_index, entry.row.timestamp, entry.constraint, entry.bus,
    entry.voltage, entry.limit, entry.margin, entry.row.load_multiplier,
    entry.row.pv_factor, entry.row.substation_p_kw, entry.row.substation_q_kvar,
    entry.row.upstream_apparent_kva, binding_reproducible,
) for entry in binding_entries]
S1BMethodBenchmark._cg_write_csv(
    joinpath(OUTPUT_DIRECTORY, "final_binding_interval_summary.csv"),
    binding_columns, binding_rows,
)

allocation_status = verification_passed ? "independently_replay_feasible_local_solution" :
                    "not_accepted_as_hosting_capacity"
allocation_rows = [
    (string(bus), state.capacities_kw[bus], state.capacities_kw[bus] / 1000.0, allocation_status)
    for bus in CANDIDATE_BUSES
]
push!(allocation_rows, (
    "total", sum(values(state.capacities_kw)), sum(values(state.capacities_kw)) / 1000.0,
    allocation_status,
))
S1BMethodBenchmark._cg_write_csv(
    joinpath(OUTPUT_DIRECTORY, "final_pv_capacity_allocation.csv"),
    ("bus", "capacity_kw", "capacity_mw", "status"), allocation_rows,
)

# Reported extrema describe the network, so they must come from intervals that
# actually produced trustworthy finite values. violation_pu is the trustworthiness
# indicator: _cg_replay_interval sets it to Inf for every untrustworthy interval.
# Failures stay accounted for separately by replay_failures/voltage_violations.
trustworthy_rows = [row for row in replay_rows if isfinite(row.violation_pu) &&
                    isfinite(row.vmin_pu) && isfinite(row.vmax_pu)]
minimum_row = isempty(trustworthy_rows) ? nothing : argmin(row -> row.vmin_pu, trustworthy_rows)
maximum_row = isempty(trustworthy_rows) ? nothing : argmax(row -> row.vmax_pu, trustworthy_rows)
maximum_s_row = isempty(trustworthy_rows) ? nothing :
                argmax(row -> row.upstream_apparent_kva, trustworthy_rows)
minimum_p = S1BMethodBenchmark._cg_finite_extreme(minimum, trustworthy_rows, :substation_p_kw)
maximum_p = S1BMethodBenchmark._cg_finite_extreme(maximum, trustworthy_rows, :substation_p_kw)
minimum_q = S1BMethodBenchmark._cg_finite_extreme(minimum, trustworthy_rows, :substation_q_kvar)
maximum_q = S1BMethodBenchmark._cg_finite_extreme(maximum, trustworthy_rows, :substation_q_kvar)
maximum_absolute_residual = S1BMethodBenchmark._cg_finite_extreme(
    maximum, trustworthy_rows, :maximum_equation_residual,
)
maximum_scaled_residual = S1BMethodBenchmark._cg_finite_extreme(
    maximum, trustworthy_rows, :maximum_scaled_residual,
)

final_starts_path = joinpath(
    OUTPUT_DIRECTORY, "checkpoints",
    "iteration_$(lpad(state.completed_iteration, 3, '0'))_starts.csv",
)
final_starts = isfile(final_starts_path) ? parse_csv(final_starts_path) : NamedTuple[]
accepted_objectives = [parse(Float64, row.objective_kw) for row in final_starts
                       if row.accepted == "true" && isfinite(parse(Float64, row.objective_kw))]
start_minimum = isempty(accepted_objectives) ? NaN : minimum(accepted_objectives)
start_maximum = isempty(accepted_objectives) ? NaN : maximum(accepted_objectives)
start_dispersion = start_maximum - start_minimum
recorded_solve_seconds = sum(row.solve_time_seconds for row in history)
recorded_replay_seconds = sum(row.replay_time_seconds for row in history)

profile_sha256 = bytes2hex(open(sha256, PROFILE_PATH))
source_commit = readchomp(`git -C $REPOSITORY_ROOT rev-parse HEAD`)
working_tree_clean = isempty(readchomp(`git -C $REPOSITORY_ROOT status --porcelain`))
production_metadata = read_key_values(joinpath(OUTPUT_DIRECTORY, "production_configuration.txt"))
open(joinpath(OUTPUT_DIRECTORY, "run_manifest.txt"), "w") do io
    println(io, "study=S1-B full-period exact-AC constraint generation")
    println(io, "source_commit=$(source_commit)")
    println(io, "source_working_tree_clean=$(working_tree_clean)")
    println(io, "branch=$(readchomp(`git -C $REPOSITORY_ROOT branch --show-current`))")
    println(io, "production_command=julia --project=. scripts/run_s1b_ac_constraint_generation.jl --confirm-full-period")
    println(io, "verification_command=julia --project=. scripts/verify_s1b_ac_constraint_generation.jl --confirm-full-period")
    println(io, "configuration_path=$(relpath(CONFIGURATION_PATH, REPOSITORY_ROOT))")
    println(io, "input_profile_path=$(relpath(PROFILE_PATH, REPOSITORY_ROOT))")
    println(io, "input_profile_sha256=$(profile_sha256)")
    println(io, "interval_count=$(length(data.indices))")
    println(io, "production_started_at_utc=$(get(production_metadata, "started_at_utc", "unknown"))")
    println(io, "production_finished_at_utc=$(get(production_metadata, "finished_at_utc", "unknown"))")
    println(io, "verification_started_at_utc=$(verification_started)")
    println(io, "verification_finished_at_utc=$(verification_finished)")
    println(io, "terminal_status=$(state.terminal_status)")
    println(io, "independent_verification_passed=$(verification_passed)")
end

limiting = isempty(binding_entries) ? nothing : first(binding_entries)
total_kw = sum(values(state.capacities_kw))
open(joinpath(OUTPUT_DIRECTORY, "final_production_report.md"), "w") do io
    println(io, "# S1-B full-period AC constraint-generation production report")
    println(io)
    println(io, "## Outcome")
    println(io)
    println(io, "- Terminal status: `$(state.terminal_status)`; reason: `$(history[end].stop_reason)`.")
    println(io, "- Constraint-generation iterations: $(state.completed_iteration); final active-set size: $(length(state.active_indices)).")
    println(io, @sprintf("- Installed PV: %.9f MW total (bus 13 %.9f, bus 20 %.9f, bus 24 %.9f, bus 30 %.9f MW).",
        total_kw / 1000, state.capacities_kw[13] / 1000, state.capacities_kw[20] / 1000,
        state.capacities_kw[24] / 1000, state.capacities_kw[30] / 1000))
    println(io, "- Clean-process full-period replay: $(verification_passed ? "passed" : "failed/not accepted"); $(length(replay_rows)) intervals, $(replay_failures) replay failures, $(voltage_violations) voltage violations beyond $(config.voltage_tolerance_pu) p.u.")
    println(io, "- **Replay failures: $(replay_failures) of $(length(replay_rows)) intervals.** Voltage violations beyond tolerance: $(voltage_violations). Trustworthy intervals used for the extrema below: $(length(trustworthy_rows)) of $(length(replay_rows)); any untrustworthy interval is excluded from every extreme so a failed solve cannot masquerade as a limiting point.")
    if limiting !== nothing
        println(io, @sprintf("- Limiting electrical constraint: %s at bus %d, %s; voltage %.12f p.u. against %.2f p.u.; PV factor %.9f; load multiplier %.9f; upstream P %.6f kW, Q %.6f kvar, apparent exchange %.6f kVA.",
            limiting.constraint, limiting.bus, limiting.row.timestamp, limiting.voltage,
            limiting.limit, limiting.row.pv_factor, limiting.row.load_multiplier,
            limiting.row.substation_p_kw, limiting.row.substation_q_kvar,
            limiting.row.upstream_apparent_kva))
    end
    if minimum_row === nothing || maximum_row === nothing
        println(io, "- Voltage extrema: not reportable; no interval produced a trustworthy finite solution.")
    else
        println(io, @sprintf("- Voltage extrema: minimum %.12f p.u. at bus %d on %s; maximum %.12f p.u. at bus %d on %s.",
            minimum_row.vmin_pu, minimum_row.vmin_bus, minimum_row.timestamp,
            maximum_row.vmax_pu, maximum_row.vmax_bus, maximum_row.timestamp))
    end
    println(io, @sprintf("- Upstream active exchange: maximum export %.6f kW; maximum import %.6f kW. Reactive extrema: %.6f to %.6f kvar.",
        max(-minimum_p, 0.0), max(maximum_p, 0.0), minimum_q, maximum_q))
    if maximum_s_row === nothing
        println(io, "- Maximum bidirectional upstream apparent-power exchange: not reportable; no trustworthy interval.")
    else
        println(io, @sprintf("- Maximum bidirectional upstream apparent-power exchange: %.6f kVA at %s (P %.6f kW, Q %.6f kvar).",
            maximum_s_row.upstream_apparent_kva, maximum_s_row.timestamp,
            maximum_s_row.substation_p_kw, maximum_s_row.substation_q_kvar))
    end
    println(io, @sprintf("- Independent residual maxima: absolute %.6e; scaled %.6e.", maximum_absolute_residual, maximum_scaled_residual))
    println(io, @sprintf("- Final-iteration accepted-start dispersion: %.9f kW across %d accepted starts (%.9f to %.9f kW).",
        start_dispersion, length(accepted_objectives), start_minimum, start_maximum))
    println(io, @sprintf("- Recorded runtime: solver %.3f s; production replay %.3f s; clean verification replay %.3f s.",
        recorded_solve_seconds, recorded_replay_seconds, verification_replay_seconds))
    println(io, "- Checkpoint allocation match: $(checkpoint_allocation_matches); active-set monotonicity: $(active_set_monotone); binding-point reproduction: $(binding_reproducible).")
    println(io)
    println(io, "## Iteration evidence")
    println(io)
    println(io, "The compact `iteration_summary.csv` records counts, additions, every start's seed/type/status/replay gate, allocations, voltage and residual extrema, upstream P/Q/apparent exchange, timings, checkpoint status, and terminal reason for every iteration. Detailed start and interval tables remain local under the ignored `checkpoints/` directory.")
    println(io)
    println(io, "## Limitations")
    println(io)
    println(io, "This is nonconvex local optimization and makes no global-optimality or proven-bound claim. It makes no transformer or line thermal-capacity claim because no defensible ratings are documented. Upstream exchange is unconstrained. Curtailment and site caps are absent. The robust extension remains unresolved.")
    println(io)
    println(io, "## Verification")
    println(io)
    println(io, "Focused and complete test-suite counts, committed files, and audit-readiness status are recorded after the post-production repository verification.")
end

open(joinpath(OUTPUT_DIRECTORY, "checkpoints", "final_verification_status.txt"), "w") do io
    println(io, "terminal_status=$(state.terminal_status)")
    println(io, "verification_passed=$(verification_passed)")
    println(io, "interval_count=$(length(replay_rows))")
    println(io, "replay_failures=$(replay_failures)")
    println(io, "voltage_violations=$(voltage_violations)")
    println(io, "active_set_monotone=$(active_set_monotone)")
    println(io, "checkpoint_allocation_matches=$(checkpoint_allocation_matches)")
    println(io, "binding_reproducible=$(binding_reproducible)")
end

println("terminal_status=$(state.terminal_status)")
println("verification_passed=$(verification_passed)")
println("verified_intervals=$(length(replay_rows))")
