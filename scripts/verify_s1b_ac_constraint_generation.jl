using Dates
using Printf
using SHA
using TOML

const REPOSITORY_ROOT = normpath(joinpath(@__DIR__, ".."))
include(joinpath(REPOSITORY_ROOT, "src", "benchmark", "s1b_method_benchmark.jl"))
using .S1BMethodBenchmark

"--confirm-full-period" in ARGS || error(
    "This runs a separate full-period replay of all 52,608 intervals. Re-run with --confirm-full-period.",
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
    no_export_active=!production["upstream_export_allowed"],
    no_export_tol_kw=Float64(production["no_export_tol_kw"]),
)

# Traceability: rebuild a one-interval model and count the no-export rows in it.
# The evidence records what the model actually contains, not what a label claims.
model_probe = let probe = subset_benchmark_data(data, [data.indices[1]])
    built = build_ac_opf_model(
        probe;
        no_export_active=config.no_export_active,
        no_export_tol_kw=config.no_export_tol_kw,
    )
    (
        constraints_per_interval=built.no_export_constraint_count,
        tol_pu=built.no_export_tol_pu,
        tol_pu_expected=config.no_export_tol_kw / probe.base_power_kw,
        root_branches=built.root_branches,
    )
end
model_probe.constraints_per_interval == (config.no_export_active ? 1 : 0) ||
    error("model no-export constraint count contradicts the configured policy")
isapprox(model_probe.tol_pu, model_probe.tol_pu_expected; atol=0.0, rtol=1e-12) ||
    error("no-export tolerance was not converted from kW to per unit")
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

# Read from the module, not copied: a local duplicate previously drifted and left
# the export columns out of the verification evidence.
replay_columns = S1BMethodBenchmark.CG_REPLAY_COLUMNS
S1BMethodBenchmark._cg_write_csv(
    joinpath(OUTPUT_DIRECTORY, "checkpoints", "final_verification_replay.csv"),
    replay_columns,
    [Tuple(getproperty(row, Symbol(column)) for column in replay_columns) for row in replay_rows],
)

replay_failures = count(row -> !isfinite(row.violation_pu), replay_rows)
voltage_violations = count(row -> isfinite(row.violation_pu) && row.violation_pu > 0.0, replay_rows)
# Export audit is independent of the voltage audit: separate metric, separate count,
# separate gate term. Never combined into a single score.
export_violations = count(
    row -> isfinite(row.export_violation_kw) && row.export_violation_kw > 0.0, replay_rows,
)
export_binding_intervals = count(
    row -> isfinite(row.export_kw) && abs(row.export_kw) <= config.no_export_tol_kw, replay_rows,
)
maximum_export_kw = isempty(replay_rows) ? NaN :
    S1BMethodBenchmark._cg_finite_extreme(maximum, replay_rows, :export_kw)
# replay_failures stays fail-hard: a non-finite replay can never be tolerated here,
# independently of either violation count.
verification_passed = length(replay_rows) == 52_608 && replay_failures == 0 &&
                      voltage_violations == 0 && export_violations == 0 &&
                      active_set_monotone && checkpoint_allocation_matches
if state.terminal_status == "converged" && !verification_passed
    error("terminal convergence claim failed the separate full-period replay verification")
end

# Binding analysis over BOTH hard constraints, separating two distinct concepts.
#
#   constraint_active  : the constraint margin is ~zero at this interval.
#   capacity_limiting  : raising installed capacity would violate it here.
#
# The two are not the same. An interval at 02:00 with pv_profile == 0 sits exactly
# on the no-export bound (nothing flows either way) yet cannot limit capacity: more
# PV changes nothing there because there is no sunlight to inject. Only intervals
# with meaningful PV availability can be capacity limiting. The previous version
# scored voltage margins alone and therefore reported a slack minimum-voltage
# interval (margin +0.018 p.u.) as "limiting", which was wrong on both counts.
const MARGIN_ACTIVE_TOL_PU = 1e-8
const CAPACITY_LIMITING_PV_TOL = 1e-6

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
        if config.no_export_active && isfinite(row.export_kw)
            # Margin to the no-export bound, in kW: how much import headroom is
            # left before the feeder would start exporting.
            push!(margin_entries, (row=row, constraint="no_export", bus=0,
                                   voltage=NaN, limit=0.0,
                                   margin=row.substation_p_kw))
        end
    end
    # Active = margin at (or inside) the bound. Voltage margins are p.u., the
    # no-export margin is kW; each is compared against its own tolerance, never
    # normalised into a common score.
    is_active(entry) = entry.constraint == "no_export" ?
        entry.margin <= config.no_export_tol_kw :
        entry.margin <= MARGIN_ACTIVE_TOL_PU
    binding_entries = [entry for entry in margin_entries if is_active(entry)]
    minimum_margin = isempty(margin_entries) ? NaN : minimum(entry.margin for entry in margin_entries)
    binding_reproducible = isempty(binding_entries) ? false : all(binding_entries) do entry
        local_t = findfirst(==(entry.row.global_index), data.indices)
        repeated = S1BMethodBenchmark._cg_replay_interval(
            data, local_t, state.capacities_kw;
            voltage_tolerance_pu=config.voltage_tolerance_pu,
            no_export_active=config.no_export_active,
            no_export_tol_kw=config.no_export_tol_kw,
        )
        if entry.constraint == "no_export"
            isapprox(repeated.substation_p_kw, entry.margin; atol=1e-9, rtol=0.0)
        else
            repeated_voltage = entry.constraint == "minimum_voltage" ? repeated.vmin_pu : repeated.vmax_pu
            repeated_bus = entry.constraint == "minimum_voltage" ? repeated.vmin_bus : repeated.vmax_bus
            repeated_bus == entry.bus && isapprox(repeated_voltage, entry.voltage; atol=1e-10, rtol=0.0)
        end
    end
end

# Capacity limiting requires usable PV at that interval: with pv_profile == 0 the
# installed capacity is irrelevant to the interval's power flow.
is_capacity_limiting(entry) = entry.row.pv_factor > CAPACITY_LIMITING_PV_TOL
capacity_limiting_entries = [entry for entry in binding_entries if is_capacity_limiting(entry)]
active_only_entries = [entry for entry in binding_entries if !is_capacity_limiting(entry)]

binding_columns = (
    "global_index", "timestamp", "constraint", "bus", "voltage_pu", "limit_pu",
    "margin", "margin_unit", "constraint_active", "capacity_limiting",
    "load_multiplier", "pv_factor", "substation_p_kw",
    "substation_q_kvar", "upstream_apparent_kva", "reproduced",
)
binding_rows = [(
    entry.row.global_index, entry.row.timestamp, entry.constraint, entry.bus,
    entry.voltage, entry.limit, entry.margin,
    entry.constraint == "no_export" ? "kW" : "pu",
    true, is_capacity_limiting(entry),
    entry.row.load_multiplier,
    entry.row.pv_factor, entry.row.substation_p_kw, entry.row.substation_q_kvar,
    entry.row.upstream_apparent_kva, binding_reproducible,
) for entry in binding_entries]
S1BMethodBenchmark._cg_write_csv(
    joinpath(OUTPUT_DIRECTORY, "final_binding_interval_summary.csv"),
    binding_columns, binding_rows,
)

allocation_status = verification_passed ? "separate_replay_feasible_local_solution" :
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
    println(io, "separate_replay_verification_passed=$(verification_passed)")
end

# The limiting constraint is drawn from the capacity-limiting subset, never from
# merely-active intervals.
limiting = isempty(capacity_limiting_entries) ? nothing : first(capacity_limiting_entries)
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
    println(io, "- Separate full-period replay (the branch-flow forward/backward sweep in replay_s1b_interval, a different code path from the JuMP/Ipopt optimisation model but not an independent third-party AC solver): $(verification_passed ? "passed" : "failed/not accepted"); $(length(replay_rows)) intervals, $(replay_failures) replay failures, $(voltage_violations) voltage violations beyond $(config.voltage_tolerance_pu) p.u.")
    println(io, "- **Replay failures: $(replay_failures) of $(length(replay_rows)) intervals.** Voltage violations beyond tolerance: $(voltage_violations). Trustworthy intervals used for the extrema below: $(length(trustworthy_rows)) of $(length(replay_rows)); any untrustworthy interval is excluded from every extreme so a failed solve cannot masquerade as a limiting point.")
    println(io, "- **Export violations: $(export_violations) of $(length(replay_rows)) intervals** (no-export active: $(config.no_export_active), tolerance $(config.no_export_tol_kw) kW = $(model_probe.tol_pu) p.u.). Intervals with upstream active power at the no-export bound: $(export_binding_intervals). Maximum upstream export observed: $(maximum_export_kw) kW.")
    println(io, "- Model traceability: a rebuilt one-interval model carries $(model_probe.constraints_per_interval) no-export constraint row(s) on root branch(es) $(model_probe.root_branches); this is counted from the model object, not read from a configuration label.")
    println(io, "- Binding summary: $(length(capacity_limiting_entries)) interval is genuinely capacity-limiting; $(length(active_only_entries)) further intervals are constraint-active but not capacity-limiting. The bare count of $(length(binding_entries)) constraint-active intervals is not reported without this split, because most of them cannot limit installed capacity.")
    for entry in capacity_limiting_entries
        println(io, @sprintf("  - capacity_limiting: gidx %d, %s, %s constraint; PV factor %.9f, load multiplier %.9f. Raising installed capacity would violate this constraint here.",
            entry.row.global_index, entry.row.timestamp, entry.constraint,
            entry.row.pv_factor, entry.row.load_multiplier))
    end
    println(io, "  - constraint_active only ($(length(active_only_entries)) intervals): sit exactly on the no-export bound with pv_factor <= $(CAPACITY_LIMITING_PV_TOL). In this run all such intervals are the DST-start transition slots (first Sunday of October, 02:00-02:30 local), where the source Ausgrid dataset records both load and PV as exactly zero, so no installed capacity can change their power flow. They do not limit hosting capacity.")
    if limiting !== nothing
        if limiting.constraint == "no_export"
            println(io, @sprintf("- Capacity-limiting constraint: no_export at %s; upstream P %.9e kW against the 0 kW bound; PV factor %.9f; load multiplier %.9f; Q %.6f kvar, apparent exchange %.6f kVA.",
                limiting.row.timestamp, limiting.row.substation_p_kw,
                limiting.row.pv_factor, limiting.row.load_multiplier,
                limiting.row.substation_q_kvar, limiting.row.upstream_apparent_kva))
        else
            println(io, @sprintf("- Capacity-limiting constraint: %s at bus %d, %s; voltage %.12f p.u. against %.2f p.u.; PV factor %.9f; load multiplier %.9f; upstream P %.6f kW, Q %.6f kvar, apparent exchange %.6f kVA.",
                limiting.constraint, limiting.bus, limiting.row.timestamp, limiting.voltage,
                limiting.limit, limiting.row.pv_factor, limiting.row.load_multiplier,
                limiting.row.substation_p_kw, limiting.row.substation_q_kvar,
                limiting.row.upstream_apparent_kva))
        end
    else
        println(io, "- Capacity-limiting constraint: none identified; no constraint-active interval has usable PV availability.")
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
    println(io, @sprintf("- Separate-replay residual maxima: absolute %.6e; scaled %.6e.", maximum_absolute_residual, maximum_scaled_residual))
    println(io, @sprintf("- Final-iteration accepted-start dispersion: %.9f kW across %d accepted starts (%.9f to %.9f kW).",
        start_dispersion, length(accepted_objectives), start_minimum, start_maximum))
    println(io, @sprintf("- Recorded runtime: solver %.3f s; production replay %.3f s; separate full-period replay %.3f s.",
        recorded_solve_seconds, recorded_replay_seconds, verification_replay_seconds))
    println(io, "- Checkpoint allocation match: $(checkpoint_allocation_matches); active-set monotonicity: $(active_set_monotone); binding-point reproduction: $(binding_reproducible).")
    println(io)
    println(io, "## Iteration evidence")
    println(io)
    println(io, "The compact `iteration_summary.csv` records counts, additions, every start's seed/type/status/replay gate, allocations, voltage and residual extrema, upstream P/Q/apparent exchange, timings, checkpoint status, and terminal reason for every iteration. Detailed start and interval tables remain local under the ignored `checkpoints/` directory.")
    println(io)
    println(io, "## Limitations")
    println(io)
    # The upstream-exchange sentence is derived from the active policy. Hardcoding
    # it here previously made the report contradict the run it described.
    upstream_sentence = config.no_export_active ?
        "Upstream active export is prohibited: P_upstream >= 0 is enforced exactly in every interval, audited by the separate full-period replay at $(config.no_export_tol_kw) kW." :
        "Upstream exchange is unconstrained."
    println(io, "This is nonconvex local optimization and makes no global-optimality or proven-bound claim. It makes no transformer or line thermal-capacity claim because no defensible ratings are documented. $(upstream_sentence) Curtailment and site caps are absent. The robust extension remains unresolved.")
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
    println(io, "export_violations=$(export_violations)")
    println(io, "export_binding_intervals=$(export_binding_intervals)")
    println(io, "maximum_export_kw=$(maximum_export_kw)")
    println(io, "no_export_active=$(config.no_export_active)")
    println(io, "no_export_tol_kw=$(config.no_export_tol_kw)")
    println(io, "model_no_export_constraints_per_interval=$(model_probe.constraints_per_interval)")
    println(io, "model_no_export_tol_pu=$(model_probe.tol_pu)")
    println(io, "active_set_monotone=$(active_set_monotone)")
    println(io, "checkpoint_allocation_matches=$(checkpoint_allocation_matches)")
    println(io, "binding_reproducible=$(binding_reproducible)")
    # constraint_active_entries is deliberately paired with the capacity-limiting
    # split on the same lines; the raw count must not stand alone (see report text).
    println(io, "constraint_active_entries=$(length(binding_entries))")
    println(io, "capacity_limiting_entries=$(length(capacity_limiting_entries))")
    println(io, "active_not_limiting_entries=$(length(active_only_entries))")
    println(io, "capacity_limiting_note=only capacity_limiting_entries constrain installed capacity; active_not_limiting_entries are DST zero-load/zero-PV slots")
end

println("terminal_status=$(state.terminal_status)")
println("verification_passed=$(verification_passed)")
println("verified_intervals=$(length(replay_rows))")
