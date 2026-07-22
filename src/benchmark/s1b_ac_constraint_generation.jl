struct ACConstraintGenerationConfig
    output_directory::String
    batch_size::Int
    max_iterations::Int
    voltage_tolerance_pu::Float64
    maximum_replay_failures::Int
    resume::Bool
    seed::Int
end

function ACConstraintGenerationConfig(
    output_directory::AbstractString;
    batch_size::Int=3,
    max_iterations::Int=20,
    voltage_tolerance_pu::Float64=AC_VOLTAGE_TOL,
    maximum_replay_failures::Int=0,
    resume::Bool=true,
    seed::Int=MULTISTART_SEED,
)
    batch_size > 0 || throw(ArgumentError("batch_size must be positive"))
    max_iterations > 0 || throw(ArgumentError("max_iterations must be positive"))
    voltage_tolerance_pu >= 0.0 || throw(ArgumentError("voltage tolerance must be nonnegative"))
    maximum_replay_failures >= 0 ||
        throw(ArgumentError("maximum_replay_failures must be nonnegative"))
    return ACConstraintGenerationConfig(
        String(output_directory), batch_size, max_iterations, voltage_tolerance_pu,
        maximum_replay_failures, resume, seed,
    )
end

function deterministic_seed_indices(data::BenchmarkData)
    indices = data.indices
    binding_timestamp = DateTime(2010, 12, 21, 12)
    binding = findfirst(index -> data.profile.timestamps[index] == binding_timestamp, indices)
    binding_index = binding === nothing ? indices[argmax(data.profile.pv_profile[indices])] : indices[binding]
    peak_index = indices[argmax(data.profile.load_multiplier[indices])]
    stress(index) = data.profile.pv_profile[index] / max(data.profile.load_multiplier[index], 0.05)
    stress_index = indices[argmax(stress.(indices))]
    seeds = unique([binding_index, peak_index, stress_index])
    if length(seeds) < min(3, length(indices))
        for index in sort(indices; by=index -> (-stress(index), index))
            index in seeds || push!(seeds, index)
            length(seeds) == min(3, length(indices)) && break
        end
    end
    return seeds
end

function smoke_validation_indices(data::BenchmarkData)
    peak_index = data.indices[argmax(data.profile.load_multiplier[data.indices])]
    stress(index) = data.profile.pv_profile[index] / max(data.profile.load_multiplier[index], 0.05)
    stress_index = data.indices[argmax(stress.(data.indices))]
    dates = unique([BENCHMARK_DATE, Date(data.profile.timestamps[peak_index]),
                    Date(data.profile.timestamps[stress_index])])
    if length(dates) < 3
        ordered = sort(unique(Date.(data.profile.timestamps[data.indices])))
        for date in ordered
            date in dates || push!(dates, date)
            length(dates) == 3 && break
        end
    end
    selected = [index for index in data.indices if Date(data.profile.timestamps[index]) in dates]
    return selected
end

function _cg_signature(data::BenchmarkData, config::ACConstraintGenerationConfig)
    profile_fingerprint = bytes2hex(sha256(join((
        "$(index):$(data.profile.timestamps[index]):$(data.profile.load_multiplier[index]):$(data.profile.pv_profile[index])"
        for index in data.indices
    ), ';')))
    material = join((
        "s1b-ac-constraint-generation-v1",
        join(data.indices, ';'),
        profile_fingerprint,
        string(config.batch_size),
        string(config.voltage_tolerance_pu),
        string(config.maximum_replay_failures),
        string(config.seed),
    ), '|')
    return bytes2hex(sha256(material))
end

_cg_csv_value(value) = value isa AbstractString ?
    "\"" * replace(value, '"' => "\"\"") * "\"" : string(value)

function _cg_write_csv(path::AbstractString, columns, rows)
    open(path, "w") do io
        println(io, join(columns, ','))
        for row in rows
            println(io, join((_cg_csv_value(value) for value in row), ','))
        end
    end
end

function _cg_state_path(config)
    return joinpath(config.output_directory, "checkpoints", "state.txt")
end

function _cg_history_path(config)
    return joinpath(config.output_directory, "iteration_summary.csv")
end

function _cg_write_state(config, signature, completed_iteration, active_indices, capacities, terminal_status)
    checkpoint_directory = dirname(_cg_state_path(config))
    mkpath(checkpoint_directory)
    temporary = joinpath(checkpoint_directory, "state.tmp")
    open(temporary, "w") do io
        println(io, "signature=$(signature)")
        println(io, "completed_iteration=$(completed_iteration)")
        println(io, "active_indices=$(join(active_indices, ';'))")
        println(io, "capacities_kw=$(join((get(capacities, bus, NaN) for bus in CANDIDATE_BUSES), ';'))")
        println(io, "terminal_status=$(terminal_status)")
    end
    mv(temporary, _cg_state_path(config); force=true)
end

function _cg_read_state(config, signature)
    path = _cg_state_path(config)
    isfile(path) || return nothing
    values = Dict{String,String}()
    for line in eachline(path)
        parts = split(line, '='; limit=2)
        length(parts) == 2 && (values[parts[1]] = parts[2])
    end
    get(values, "signature", "") == signature || throw(ArgumentError(
        "checkpoint signature does not match the validation set or production-safe controls",
    ))
    active = isempty(get(values, "active_indices", "")) ? Int[] :
             parse.(Int, split(values["active_indices"], ';'))
    capacity_values = parse.(Float64, split(values["capacities_kw"], ';'))
    capacities = Dict(bus => capacity_values[i] for (i, bus) in enumerate(CANDIDATE_BUSES))
    return (
        completed_iteration=parse(Int, values["completed_iteration"]),
        active_indices=active,
        capacities_kw=capacities,
        terminal_status=get(values, "terminal_status", ""),
    )
end

const _CG_HISTORY_COLUMNS = (
    "iteration", "active_before", "active_after", "accepted_start_count",
    "best_start_name", "objective_kw", "c13_kw", "c20_kw", "c24_kw", "c30_kw",
    "replay_count", "replay_failure_count", "violating_count", "max_violation_pu",
    "minimum_voltage_pu", "minimum_voltage_bus", "minimum_voltage_timestamp",
    "maximum_voltage_pu", "maximum_voltage_bus", "maximum_voltage_timestamp",
    "worst_violation_type", "worst_violation_bus", "worst_violation_timestamp",
    "maximum_equation_residual", "maximum_scaled_residual",
    "minimum_substation_p_kw", "maximum_substation_p_kw",
    "minimum_substation_q_kvar", "maximum_substation_q_kvar",
    "maximum_upstream_apparent_kva", "solve_time_seconds", "replay_time_seconds",
    "added_indices", "added_timestamps", "checkpoint_path", "checkpoint_status",
    "stop_reason", "start_summary",
)

function _cg_write_history(config, history)
    rows = [Tuple(getfield(row, Symbol(column)) for column in _CG_HISTORY_COLUMNS) for row in history]
    _cg_write_csv(_cg_history_path(config), _CG_HISTORY_COLUMNS, rows)
end

function _cg_parse_csv_line(line)
    fields = String[]
    buffer = IOBuffer()
    quoted = false
    chars = collect(line)
    index = 1
    while index <= length(chars)
        char = chars[index]
        if char == '"'
            if quoted && index < length(chars) && chars[index + 1] == '"'
                write(buffer, '"')
                index += 1
            else
                quoted = !quoted
            end
        elseif char == ',' && !quoted
            push!(fields, String(take!(buffer)))
        else
            write(buffer, char)
        end
        index += 1
    end
    push!(fields, String(take!(buffer)))
    return fields
end

function _cg_read_history(config)
    path = _cg_history_path(config)
    isfile(path) || return NamedTuple[]
    lines = readlines(path)
    length(lines) <= 1 && return NamedTuple[]
    rows = NamedTuple[]
    for line in lines[2:end]
        values = _cg_parse_csv_line(line)
        length(values) == length(_CG_HISTORY_COLUMNS) || throw(ArgumentError(
            "iteration summary schema does not match the production evidence schema",
        ))
        typed = Any[]
        integer_columns = Set((
            "iteration", "active_before", "active_after", "accepted_start_count",
            "replay_count", "replay_failure_count", "violating_count",
            "minimum_voltage_bus", "maximum_voltage_bus", "worst_violation_bus",
        ))
        float_columns = Set((
            "objective_kw", "c13_kw", "c20_kw", "c24_kw", "c30_kw",
            "max_violation_pu", "minimum_voltage_pu", "maximum_voltage_pu",
            "maximum_equation_residual", "maximum_scaled_residual",
            "minimum_substation_p_kw", "maximum_substation_p_kw",
            "minimum_substation_q_kvar", "maximum_substation_q_kvar",
            "maximum_upstream_apparent_kva", "solve_time_seconds", "replay_time_seconds",
        ))
        for (column, value) in zip(_CG_HISTORY_COLUMNS, values)
            push!(typed, column in integer_columns ? parse(Int, value) :
                         column in float_columns ? parse(Float64, value) : value)
        end
        push!(rows, NamedTuple{Symbol.(_CG_HISTORY_COLUMNS)}(Tuple(typed)))
    end
    return rows
end

function _cg_previous_spec(capacities, seed)
    values = [capacities[bus] for bus in CANDIDATE_BUSES]
    return (
        name="previous_active_set_best", kind="warm_start_only", seed=seed,
        capacities_kw=values, direction_limit_kw=NaN, scale_fraction=NaN,
    )
end

_cg_property(row, name::Symbol, default) = hasproperty(row, name) ? getproperty(row, name) : default

function _cg_sum_property(rows, name::Symbol)
    values = Float64[_cg_property(row, name, 0.0) for row in rows]
    return any(!isfinite, values) ? NaN : sum(values)
end

function _cg_finite_extreme(reducer, rows, name::Symbol)
    values = Float64[getproperty(row, name) for row in rows]
    finite = filter(isfinite, values)
    return isempty(finite) ? NaN : reducer(finite)
end

function _cg_start_summary(starts)
    return join((
        join((
            _cg_property(row, :start_name, ""),
            _cg_property(row, :start_kind, ""),
            _cg_property(row, :seed, 0),
            _cg_property(row, :termination_status, ""),
            _cg_property(row, :independent_replay_passed, false),
            _cg_property(row, :accepted, false),
            _cg_property(row, :objective_kw, NaN),
            _cg_property(row, :solve_time_seconds, NaN),
        ), '|') for row in starts
    ), ';')
end

function _cg_replay_interval(
    data::BenchmarkData,
    local_t::Int,
    capacities;
    voltage_tolerance_pu::Float64=AC_VOLTAGE_TOL,
)
    state = exact_ac_state(data, local_t, capacities)
    finite_voltage = !isempty(state.voltage_pu) && all(isfinite, state.voltage_pu)
    vmin = finite_voltage ? minimum(state.voltage_pu) : NaN
    vmax = finite_voltage ? maximum(state.voltage_pu) : NaN
    trustworthy = state.converged && state.phasor_recoverable &&
                  state.maximum_equation_residual <= AC_RESIDUAL_TOL && finite_voltage
    violation = trustworthy ? max(
        VMIN_PU - vmin - voltage_tolerance_pu,
        vmax - VMAX_PU - voltage_tolerance_pu,
        0.0,
    ) : Inf
    failure_reason = !state.converged ? "nonconverged" :
                     !state.phasor_recoverable ? "phasor_not_recoverable" :
                     state.maximum_equation_residual > AC_RESIDUAL_TOL ? "residual_exceeded" :
                     !finite_voltage ? "nonfinite_voltage" : ""
    lower_excess = trustworthy ? VMIN_PU - vmin - voltage_tolerance_pu : Inf
    upper_excess = trustworthy ? vmax - VMAX_PU - voltage_tolerance_pu : Inf
    violation_type = !trustworthy ? failure_reason :
                     lower_excess > upper_excess && lower_excess > 0.0 ? "minimum_voltage" :
                     upper_excess > 0.0 ? "maximum_voltage" : ""
    violation_bus = violation_type == "minimum_voltage" ? state.minimum_voltage_bus :
                    violation_type == "maximum_voltage" ? state.maximum_voltage_bus : 0
    global_index = data.indices[local_t]
    return (
        global_index=global_index,
        timestamp=Dates.format(data.profile.timestamps[global_index], dateformat"yyyy-mm-dd HH:MM:SS"),
        converged=state.converged,
        phasor_recoverable=state.phasor_recoverable,
        maximum_equation_residual=state.maximum_equation_residual,
        maximum_scaled_residual=state.maximum_scaled_residual,
        vmin_pu=vmin,
        vmin_bus=state.minimum_voltage_bus,
        vmax_pu=vmax,
        vmax_bus=state.maximum_voltage_bus,
        violation_pu=violation,
        violation_type=violation_type,
        violation_bus=violation_bus,
        load_multiplier=data.profile.load_multiplier[global_index],
        pv_factor=data.profile.pv_profile[global_index],
        substation_p_kw=state.substation_p_kw,
        substation_q_kvar=state.substation_q_kvar,
        upstream_apparent_kva=hypot(state.substation_p_kw, state.substation_q_kvar),
        replay_passed=trustworthy && violation <= 0.0,
        failure_reason=failure_reason,
    )
end

function rank_replay_violations(replay_rows, active_indices)
    active = Set(active_indices)
    candidates = [row for row in replay_rows if !(row.global_index in active) &&
                  (!row.replay_passed || row.violation_pu > 0.0)]
    sort!(candidates; by=row -> (
        isfinite(row.violation_pu) ? 1 : 0,
        isfinite(row.violation_pu) ? -row.violation_pu : 0.0,
        row.global_index,
    ))
    return candidates
end

function _cg_write_iteration_details(config, iteration, starts, replay_rows)
    directory = joinpath(config.output_directory, "checkpoints")
    mkpath(directory)
    start_columns = (
        "start_id", "start_name", "start_kind", "seed", "termination_status", "primal_status",
        "objective_kw", "c13_kw", "c20_kw", "c24_kw", "c30_kw",
        "maximum_constraint_violation", "independent_replay_max_absolute_residual",
        "independent_replay_max_scaled_residual", "independent_replay_passed",
        "accepted", "iterations", "solve_time_seconds", "wall_time_seconds", "error_message",
    )
    start_rows = [Tuple(
        hasproperty(row, Symbol(column)) ? getfield(row, Symbol(column)) : ""
        for column in start_columns
    ) for row in starts]
    _cg_write_csv(joinpath(directory, "iteration_$(lpad(iteration, 3, '0'))_starts.csv"),
                  start_columns, start_rows)
    replay_columns = (
        "global_index", "timestamp", "converged", "phasor_recoverable",
        "maximum_equation_residual", "maximum_scaled_residual",
        "vmin_pu", "vmin_bus", "vmax_pu", "vmax_bus", "violation_pu",
        "violation_type", "violation_bus", "load_multiplier", "pv_factor",
        "substation_p_kw", "substation_q_kvar", "upstream_apparent_kva",
        "replay_passed", "failure_reason",
    )
    replay_values = [Tuple(getfield(row, Symbol(column)) for column in replay_columns)
                     for row in replay_rows]
    _cg_write_csv(joinpath(directory, "iteration_$(lpad(iteration, 3, '0'))_replay.csv"),
                  replay_columns, replay_values)
end

function run_ac_constraint_generation(
    validation_data::BenchmarkData,
    config::ACConstraintGenerationConfig;
    initial_indices=deterministic_seed_indices(validation_data),
    spec_builder=multistart_specs,
    solve_fn=solve_ac_multistart,
    replay_fn=_cg_replay_interval,
)
    mkpath(config.output_directory)
    signature = _cg_signature(validation_data, config)
    state = config.resume ? _cg_read_state(config, signature) : nothing
    history = state === nothing ? NamedTuple[] : _cg_read_history(config)
    active_indices = state === nothing ? sort(unique(Int.(initial_indices))) : state.active_indices
    all(index -> index in validation_data.indices, active_indices) ||
        throw(ArgumentError("active-set checkpoint contains an index outside validation data"))
    capacities = state === nothing ? Dict(bus => NaN for bus in CANDIDATE_BUSES) : state.capacities_kw
    completed = state === nothing ? 0 : state.completed_iteration
    resumed = state !== nothing
    if state !== nothing && !isempty(state.terminal_status)
        return (status=state.terminal_status, history=history, active_indices=active_indices,
                capacities_kw=capacities, resumed=resumed, completed_iterations=completed)
    end
    final_status = "max_iterations"
    for iteration in (completed + 1):config.max_iterations
        active_before = length(active_indices)
        active_data = subset_benchmark_data(validation_data, active_indices)
        specs = collect(spec_builder(active_data; seed=config.seed))
        length(specs) >= 10 || throw(ArgumentError(
            "production AC search requires at least ten deterministic starts",
        ))
        if all(isfinite, values(capacities))
            pushfirst!(specs, _cg_previous_spec(capacities, config.seed))
        end
        starts = solve_fn(active_data, specs)
        best = best_ac_result(starts)
        if best === nothing
            final_status = "no_accepted_ac_start"
            start_summary = _cg_start_summary(starts)
            push!(history, (
                iteration=iteration, active_before=active_before, active_after=active_before,
                accepted_start_count=0, best_start_name="", objective_kw=NaN,
                c13_kw=NaN, c20_kw=NaN, c24_kw=NaN, c30_kw=NaN,
                replay_count=0, replay_failure_count=0, violating_count=0,
                max_violation_pu=NaN, added_indices="", stop_reason=final_status,
                minimum_voltage_pu=NaN, minimum_voltage_bus=0, minimum_voltage_timestamp="",
                maximum_voltage_pu=NaN, maximum_voltage_bus=0, maximum_voltage_timestamp="",
                worst_violation_type="", worst_violation_bus=0, worst_violation_timestamp="",
                maximum_equation_residual=NaN, maximum_scaled_residual=NaN,
                minimum_substation_p_kw=NaN, maximum_substation_p_kw=NaN,
                minimum_substation_q_kvar=NaN, maximum_substation_q_kvar=NaN,
                maximum_upstream_apparent_kva=NaN,
                solve_time_seconds=_cg_sum_property(starts, :solve_time_seconds),
                replay_time_seconds=0.0, added_timestamps="",
                checkpoint_path=_cg_state_path(config), checkpoint_status="written_terminal",
                start_summary=start_summary,
            ))
            _cg_write_iteration_details(config, iteration, starts, NamedTuple[])
            _cg_write_history(config, history)
            _cg_write_state(config, signature, iteration, active_indices, capacities, final_status)
            completed = iteration
            break
        end
        capacities = Dict(bus => getfield(best, Symbol("c$(bus)_kw")) for bus in CANDIDATE_BUSES)
        replay_started = time()
        replay_rows = replay_fn === _cg_replay_interval ?
            [replay_fn(validation_data, local_t, capacities;
                       voltage_tolerance_pu=config.voltage_tolerance_pu)
             for local_t in eachindex(validation_data.indices)] :
            [replay_fn(validation_data, local_t, capacities)
             for local_t in eachindex(validation_data.indices)]
        replay_time_seconds = time() - replay_started
        failures = count(row -> !isfinite(row.violation_pu), replay_rows)
        violating = count(row -> !row.replay_passed || row.violation_pu > 0.0, replay_rows)
        ranked = rank_replay_violations(replay_rows, active_indices)
        additions = failures > config.maximum_replay_failures ? Int[] :
                    [row.global_index for row in ranked[1:min(config.batch_size, length(ranked))]]
        append!(active_indices, additions)
        sort!(unique!(active_indices))
        stop_reason = ""
        if failures > config.maximum_replay_failures
            final_status = "replay_failure_limit"
            stop_reason = final_status
        elseif failures == 0 && violating == 0
            final_status = "converged"
            stop_reason = final_status
        elseif isempty(additions)
            final_status = failures > config.maximum_replay_failures ?
                           "unresolved_replay_failures" : "unresolved_voltage_violations"
            stop_reason = final_status
        end
        accepted_count = count(row -> row.accepted, starts)
        start_summary = _cg_start_summary(starts)
        maximum_violation = isempty(replay_rows) ? NaN : maximum(row.violation_pu for row in replay_rows)
        trustworthy_rows = [row for row in replay_rows if isfinite(row.violation_pu) &&
                            isfinite(row.vmin_pu) && isfinite(row.vmax_pu)]
        min_row = isempty(trustworthy_rows) ? nothing : argmin(row -> row.vmin_pu, trustworthy_rows)
        max_row = isempty(trustworthy_rows) ? nothing : argmax(row -> row.vmax_pu, trustworthy_rows)
        all_ranked = rank_replay_violations(replay_rows, Int[])
        worst_row = isempty(all_ranked) ? nothing : first(all_ranked)
        added_timestamps = join((
            Dates.format(validation_data.profile.timestamps[index], dateformat"yyyy-mm-dd HH:MM:SS")
            for index in additions
        ), ';')
        push!(history, (
            iteration=iteration, active_before=active_before, active_after=length(active_indices),
            accepted_start_count=accepted_count, best_start_name=best.start_name,
            objective_kw=best.objective_kw,
            c13_kw=capacities[13], c20_kw=capacities[20],
            c24_kw=capacities[24], c30_kw=capacities[30],
            replay_count=length(replay_rows), replay_failure_count=failures,
            violating_count=violating, max_violation_pu=maximum_violation,
            minimum_voltage_pu=min_row === nothing ? NaN : min_row.vmin_pu,
            minimum_voltage_bus=min_row === nothing ? 0 : min_row.vmin_bus,
            minimum_voltage_timestamp=min_row === nothing ? "" : min_row.timestamp,
            maximum_voltage_pu=max_row === nothing ? NaN : max_row.vmax_pu,
            maximum_voltage_bus=max_row === nothing ? 0 : max_row.vmax_bus,
            maximum_voltage_timestamp=max_row === nothing ? "" : max_row.timestamp,
            worst_violation_type=worst_row === nothing ? "" : worst_row.violation_type,
            worst_violation_bus=worst_row === nothing ? 0 : worst_row.violation_bus,
            worst_violation_timestamp=worst_row === nothing ? "" : worst_row.timestamp,
            maximum_equation_residual=_cg_finite_extreme(maximum, trustworthy_rows, :maximum_equation_residual),
            maximum_scaled_residual=_cg_finite_extreme(maximum, trustworthy_rows, :maximum_scaled_residual),
            minimum_substation_p_kw=_cg_finite_extreme(minimum, trustworthy_rows, :substation_p_kw),
            maximum_substation_p_kw=_cg_finite_extreme(maximum, trustworthy_rows, :substation_p_kw),
            minimum_substation_q_kvar=_cg_finite_extreme(minimum, trustworthy_rows, :substation_q_kvar),
            maximum_substation_q_kvar=_cg_finite_extreme(maximum, trustworthy_rows, :substation_q_kvar),
            maximum_upstream_apparent_kva=_cg_finite_extreme(maximum, trustworthy_rows, :upstream_apparent_kva),
            solve_time_seconds=_cg_sum_property(starts, :solve_time_seconds),
            replay_time_seconds=replay_time_seconds,
            added_indices=join(additions, ';'), added_timestamps=added_timestamps,
            checkpoint_path=_cg_state_path(config),
            checkpoint_status=isempty(stop_reason) ? "written_resumable" : "written_terminal",
            stop_reason=stop_reason,
            start_summary=start_summary,
        ))
        _cg_write_iteration_details(config, iteration, starts, replay_rows)
        _cg_write_history(config, history)
        terminal = stop_reason
        _cg_write_state(config, signature, iteration, active_indices, capacities, terminal)
        completed = iteration
        isempty(stop_reason) || break
    end
    return (status=final_status, history=history, active_indices=active_indices,
            capacities_kw=capacities, resumed=resumed, completed_iterations=completed)
end
