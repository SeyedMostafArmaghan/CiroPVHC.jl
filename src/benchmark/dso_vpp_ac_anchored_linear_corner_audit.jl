module DSOVPPACAnchoredLinearCornerAudit

using Dates
using Printf
using SHA

include("dso_vpp_export_side_axis_scan.jl")
const AxisScan = DSOVPPExportSideAxisScan
const Stage0 = AxisScan.Stage0

const DIAGNOSTIC_VARIANT = "AC_ANCHORED_LINDISTFLOW"
const IMPLEMENTATION_ID = "CiroPVHC.DSOVPPACAnchoredLinearCornerAudit.v1"
const PHASE_B_COMMIT = "24138a3423875d1c58f814b8f448cebdd8287383"
const PREREGISTRATION_COMMIT = "79d92dce83a41cc0407897b78afa43d6252cd70f"
const CAPACITY_RELATIVE_PATH =
    "results/dso_vpp_ac_map_pilot/export_side_axis_capacity_bounds.csv"
const EXPECTED_CAPACITY_SHA256 =
    "79ae1cd38ca705399babfa104e4f14c75f18d9bed4ecd4cd5b4b99d044a6af92"
const LIMITING_TIMESTAMP = DateTime(2012, 10, 15, 13, 0, 0)
const NO_PROBE_STATEMENT =
    "No AC radial scan, LinDistFlow radial scan, direction probe, DOE, VPP optimization, or Jacobian sensitivity was run."

Base.@kwdef struct AuditConfig
    repository_root::String = normpath(joinpath(@__DIR__, "..", ".."))
    output_directory::String =
        joinpath(repository_root, "results", "dso_vpp_ac_map_pilot")
    timestamp::DateTime = LIMITING_TIMESTAMP
    reference_pv_capacity_kw::Float64 = 850.0
    vmax_pu::Float64 = 1.05
    coefficient_epsilon::Float64 = 1e-14
    axis_tie_tolerance_kw::Float64 = 1e-6
    near_binding_tolerance_v2::Float64 = 1e-10
    condition_number_threshold::Float64 = 1e10
    angular_deduplication_tolerance_rad::Float64 = 1e-12
    overwrite::Bool = false
    exact_command::String =
        "julia --project=. scripts/run_dso_vpp_ac_anchored_linear_corner_audit.jl"
end

function validate_config(config::AuditConfig)
    config.timestamp == LIMITING_TIMESTAMP || throw(ArgumentError(
        "the audit timestamp is provenance-locked to $LIMITING_TIMESTAMP",
    ))
    config.reference_pv_capacity_kw == 850.0 || throw(ArgumentError(
        "the reference-PV capacity is provenance-locked to 850 kW",
    ))
    config.vmax_pu == Stage0.VMAX_PU || throw(ArgumentError(
        "the audit upper-voltage limit must equal the committed AC limit",
    ))
    config.coefficient_epsilon >= 0 ||
        throw(ArgumentError("coefficient epsilon must be nonnegative"))
    config.axis_tie_tolerance_kw >= 0 ||
        throw(ArgumentError("axis tie tolerance must be nonnegative"))
    config.near_binding_tolerance_v2 >= 0 ||
        throw(ArgumentError("near-binding tolerance must be nonnegative"))
    config.condition_number_threshold > 1 ||
        throw(ArgumentError("condition-number threshold must exceed one"))
    config.angular_deduplication_tolerance_rad >= 0 ||
        throw(ArgumentError("angular tolerance must be nonnegative"))
    return config
end

function git_output(root, arguments...)
    command = String["git", "-C", String(root), String.(arguments)...]
    return strip(read(Cmd(command), String))
end

function committed_blob(root, commit, relative_path)
    object = "$(commit):$(replace(relative_path, '\\' => '/'))"
    return read(Cmd(["git", "-C", root, "cat-file", "blob", object]))
end

sha256_hex(bytes) = bytes2hex(SHA.sha256(bytes))
sha256_file(path) = open(path, "r") do io
    bytes2hex(SHA.sha256(io))
end

function parse_simple_csv(text::AbstractString)
    lines = [line for line in split(replace(text, "\r\n" => "\n"), '\n')
             if !isempty(line)]
    isempty(lines) && return NamedTuple[]
    names = Symbol.(split(first(lines), ','))
    rows = NamedTuple[]
    for line in lines[2:end]
        values = split(line, ','; keepempty=true)
        length(values) == length(names) || throw(ArgumentError(
            "unsupported comma-containing field in simple CSV",
        ))
        push!(rows, NamedTuple{Tuple(names)}(Tuple(values)))
    end
    return rows
end

function committed_capacity_data(config::AuditConfig)
    bytes = committed_blob(
        config.repository_root, PHASE_B_COMMIT, CAPACITY_RELATIVE_PATH,
    )
    digest = sha256_hex(bytes)
    digest == EXPECTED_CAPACITY_SHA256 || throw(ArgumentError(
        "committed capacity CSV SHA-256 mismatch: $digest",
    ))
    rows = parse_simple_csv(String(bytes))
    valid = [row for row in rows if row.axis_status == "VALID_REFINED_BOUND"]
    isempty(valid) && throw(ArgumentError("capacity CSV has no valid refined bounds"))
    axis_rows(axis_bus) = [row for row in valid if parse(Int, row.axis_bus) == axis_bus]
    scales = Dict(
        bus => minimum(parse(Float64, row.axis_capacity_kW) for row in axis_rows(bus))
        for bus in (13, 30)
    )
    limiting = Dict(
        bus => axis_rows(bus)[argmin(
            parse(Float64, row.axis_capacity_kW) for row in axis_rows(bus)
        )]
        for bus in (13, 30)
    )
    for bus in (13, 30)
        DateTime(limiting[bus].timestamp, dateformat"yyyy-mm-dd HH:MM:SS") ==
            config.timestamp || throw(ArgumentError(
                "axis $bus limiting timestamp differs from the locked audit timestamp",
            ))
    end
    return (sha256=digest, rows=rows, valid_rows=valid,
            scales_kw=scales, limiting_rows=limiting)
end

function axis_ranking(bus_ids, delta_v2, coefficients, coefficient_epsilon,
                      tie_tolerance_kw)
    length(bus_ids) == length(delta_v2) == length(coefficients) ||
        throw(ArgumentError("axis-vector length mismatch"))
    rows = NamedTuple[]
    for index in eachindex(bus_ids)
        coefficient = Float64(coefficients[index])
        controlling = coefficient > coefficient_epsilon
        limit_kw = controlling ?
            Float64(delta_v2[index]) / coefficient * Stage0.BASE_KW : Inf
        push!(rows, (
            bus=Int(bus_ids[index]), delta_v2=Float64(delta_v2[index]),
            coefficient_pu_per_pu=coefficient,
            coefficient_v2_per_kw=coefficient / Stage0.BASE_KW,
            controlling=controlling, linear_axis_limit_kw=limit_kw,
        ))
    end
    sort!(rows; by=row -> (
        isfinite(row.linear_axis_limit_kw) ? 0 : 1,
        row.linear_axis_limit_kw, row.bus,
    ))
    finite_rows = [row for row in rows if isfinite(row.linear_axis_limit_kw)]
    isempty(finite_rows) && throw(ArgumentError("axis has no controlling constraints"))
    minimum_limit = first(finite_rows).linear_axis_limit_kw
    ties = sort!([row.bus for row in finite_rows
                  if abs(row.linear_axis_limit_kw - minimum_limit) <= tie_tolerance_kw])
    ranked = [merge(row, (rank=rank,)) for (rank, row) in enumerate(rows)]
    return (rows=ranked, minimum_limit_kw=minimum_limit, tie_buses=ties)
end

function axis_classification(axis_bus, tie_buses)
    length(tie_buses) > 1 && return "LINEAR_AXIS_$(axis_bus)_AMBIGUOUS_TIE"
    return only(tie_buses) == axis_bus ?
        "LINEAR_AXIS_$(axis_bus)_SELF_BINDS" :
        "LINEAR_AXIS_$(axis_bus)_BINDS_ELSEWHERE"
end

function analyze_envelope(
    bus_ids, delta_v2, coefficients_13, coefficients_30, scales_kw;
    coefficient_epsilon=1e-14,
    axis_tie_tolerance_kw=1e-6,
    near_binding_tolerance_v2=1e-10,
    condition_number_threshold=1e10,
)
    n = length(bus_ids)
    n == length(delta_v2) == length(coefficients_13) == length(coefficients_30) ||
        throw(ArgumentError("all-bus vector length mismatch"))
    length(unique(bus_ids)) == n || throw(ArgumentError("bus IDs must be unique"))
    all(isfinite, delta_v2) || throw(ArgumentError("voltage headrooms must be finite"))
    all(isfinite, coefficients_13) && all(isfinite, coefficients_30) ||
        throw(ArgumentError("topology coefficients must be finite"))
    all(value >= 0 for value in coefficients_13) &&
        all(value >= 0 for value in coefficients_30) ||
        throw(ArgumentError("topology coefficients must be nonnegative"))
    all(haskey(scales_kw, bus) && scales_kw[bus] > 0 for bus in (13, 30)) ||
        throw(ArgumentError("positive normalization scales are required"))

    ranking13 = axis_ranking(
        bus_ids, delta_v2, coefficients_13, coefficient_epsilon,
        axis_tie_tolerance_kw,
    )
    ranking30 = axis_ranking(
        bus_ids, delta_v2, coefficients_30, coefficient_epsilon,
        axis_tie_tolerance_kw,
    )
    index_by_bus = Dict(bus => index for (index, bus) in pairs(bus_ids))
    all(haskey(index_by_bus, bus) for bus in (13, 30)) ||
        throw(ArgumentError("candidate buses 13 and 30 must be present"))
    i13 = index_by_bus[13]
    i30 = index_by_bus[30]
    matrix = [
        Float64(coefficients_13[i13]) Float64(coefficients_30[i13]);
        Float64(coefficients_13[i30]) Float64(coefficients_30[i30]);
    ]
    rhs = Float64[delta_v2[i13], delta_v2[i30]]
    a, b = matrix[1, 1], matrix[1, 2]
    c, d = matrix[2, 1], matrix[2, 2]
    determinant = a * d - b * c
    squared_frobenius = a^2 + b^2 + c^2 + d^2
    singular_discriminant = sqrt(max(
        squared_frobenius^2 - 4 * determinant^2, 0.0,
    ))
    largest_singular = sqrt((squared_frobenius + singular_discriminant) / 2)
    smallest_singular = sqrt(max(
        (squared_frobenius - singular_discriminant) / 2, 0.0,
    ))
    condition_number = smallest_singular > 0 ?
        largest_singular / smallest_singular : Inf
    well_conditioned = isfinite(condition_number) &&
                       condition_number <= condition_number_threshold &&
                       abs(determinant) > coefficient_epsilon^2
    p_pu = well_conditioned ? [
        (d * rhs[1] - b * rhs[2]) / determinant,
        (-c * rhs[1] + a * rhs[2]) / determinant,
    ] : fill(NaN, 2)
    p_kw = p_pu .* Stage0.BASE_KW
    positive = well_conditioned && all(value > 0 for value in p_kw)
    residual = well_conditioned ? [
        a * p_pu[1] + b * p_pu[2] - rhs[1],
        c * p_pu[1] + d * p_pu[2] - rhs[2],
    ] : fill(NaN, 2)
    normalized_residual = well_conditioned ? [
        abs(residual[index]) / max(abs(rhs[index]), eps(Float64)) for index in 1:2
    ] : fill(Inf, 2)
    margins = well_conditioned ? [
        Float64(delta_v2[index]) -
        Float64(coefficients_13[index]) * p_pu[1] -
        Float64(coefficients_30[index]) * p_pu[2]
        for index in eachindex(bus_ids)
    ] : fill(NaN, n)
    near_binding = well_conditioned ? sort!([
        Int(bus_ids[index]) for index in eachindex(bus_ids)
        if abs(margins[index]) <= near_binding_tolerance_v2
    ]) : Int[]
    violated = well_conditioned ? sort!([
        Int(bus_ids[index]) for index in eachindex(bus_ids)
        if margins[index] < -near_binding_tolerance_v2
    ]) : Int[]
    inactive_positive = well_conditioned ? [
        margins[index] for index in eachindex(margins)
        if !(Int(bus_ids[index]) in near_binding) && margins[index] > 0
    ] : Float64[]
    next_positive = isempty(inactive_positive) ? Inf : minimum(inactive_positive)
    active_residual_scale = isempty(near_binding) ? Inf : maximum(
        abs(margins[index_by_bus[bus]]) for bus in near_binding
    )
    active_inactive_separation = isfinite(next_positive) ?
        next_positive - active_residual_scale : Inf

    classification = if !well_conditioned
        "ILL_CONDITIONED_INTERSECTION"
    elseif !positive
        "NO_POSITIVE_13_30_INTERSECTION"
    elseif !isempty(violated)
        "CANDIDATE_INTERSECTION_CUT_OFF_BY_OTHER_BUS"
    elseif !(13 in near_binding && 30 in near_binding)
        "CANDIDATE_INTERSECTION_CUT_OFF_BY_OTHER_BUS"
    elseif length(near_binding) > 2
        "AMBIGUOUS_MULTIPLE_LINEAR_CONSTRAINTS"
    else
        "EXPOSED_LINEAR_CORNER_13_30"
    end

    normalized_angle = positive ? atan(
        p_kw[2] / scales_kw[30], p_kw[1] / scales_kw[13],
    ) : NaN
    raw_angle = positive ? atan(p_kw[2], p_kw[1]) : NaN
    cross_axis_inequalities = (
        bus13_beats_bus30_on_axis13=
            delta_v2[i13] / coefficients_13[i13] <
            delta_v2[i30] / coefficients_13[i30],
        bus30_beats_bus13_on_axis30=
            delta_v2[i30] / coefficients_30[i30] <
            delta_v2[i13] / coefficients_30[i13],
    )
    margin_rows = [(
        bus=Int(bus_ids[index]), delta_v2=Float64(delta_v2[index]),
        coefficient_13_pu_per_pu=Float64(coefficients_13[index]),
        coefficient_30_pu_per_pu=Float64(coefficients_30[index]),
        contribution_13_v2=well_conditioned ?
            Float64(coefficients_13[index]) * p_pu[1] : NaN,
        contribution_30_v2=well_conditioned ?
            Float64(coefficients_30[index]) * p_pu[2] : NaN,
        margin_v2=margins[index],
        near_binding=Int(bus_ids[index]) in near_binding,
        violated=Int(bus_ids[index]) in violated,
    ) for index in eachindex(bus_ids)]
    sort!(margin_rows; by=row -> (isfinite(row.margin_v2) ? row.margin_v2 : Inf, row.bus))

    return (
        ranking13=ranking13, ranking30=ranking30,
        axis13_classification=axis_classification(13, ranking13.tie_buses),
        axis30_classification=axis_classification(30, ranking30.tie_buses),
        matrix=matrix, rhs=rhs, determinant=determinant,
        condition_number=condition_number, well_conditioned=well_conditioned,
        p_pu=p_pu, p_kw=p_kw, positive_quadrant=positive,
        residual=residual, normalized_residual=normalized_residual,
        margins=margins, margin_rows=margin_rows,
        minimum_margin_v2=well_conditioned ? minimum(margins) : NaN,
        near_binding_buses=near_binding, violated_buses=violated,
        next_smallest_positive_margin_v2=next_positive,
        active_inactive_separation_v2=active_inactive_separation,
        classification=classification,
        normalized_angle_rad=normalized_angle,
        normalized_angle_deg=rad2deg(normalized_angle),
        raw_kw_angle_rad=raw_angle, raw_kw_angle_deg=rad2deg(raw_angle),
        angle_difference_rad=raw_angle - normalized_angle,
        angle_difference_deg=rad2deg(raw_angle - normalized_angle),
        cross_axis_inequalities=cross_axis_inequalities,
    )
end

function default_baseline_evaluator(network, profile, profile_index, config)
    scan_config = AxisScan.ScanConfig(
        repository_root=config.repository_root,
        output_directory=config.output_directory,
        reference_pv_capacity_kw=config.reference_pv_capacity_kw,
    )
    return AxisScan.evaluate_fixed_injection(
        network, profile, profile_index, 0.0, 0.0, scan_config;
        warm_start_source="flat_start_linear_corner_audit_baseline",
    )
end

function run_analytical_audit(
    config::AuditConfig=AuditConfig();
    baseline_evaluator=default_baseline_evaluator,
)
    validate_config(config)
    capacity = committed_capacity_data(config)
    scan_config = AxisScan.ScanConfig(
        repository_root=config.repository_root,
        output_directory=config.output_directory,
        reference_pv_capacity_kw=config.reference_pv_capacity_kw,
    )
    data = AxisScan.load_canonical_data(scan_config)
    AxisScan.validate_radial_topology(data.network)
    profile_index = findfirst(==(config.timestamp), data.profile.timestamps)
    profile_index === nothing && throw(ArgumentError("audit timestamp is absent"))
    profile_index in data.indices || throw(ArgumentError("audit timestamp is outside pilot window"))
    baseline = baseline_evaluator(data.network, data.profile, profile_index, config)
    baseline.power_flow_status == "CONVERGED" ||
        throw(ArgumentError("baseline primary AC power flow did not converge"))
    baseline.replay_status == "PASSED" ||
        throw(ArgumentError("baseline AC replay did not pass"))
    baseline.p13_vpp_kw == 0.0 && baseline.p30_vpp_kw == 0.0 ||
        throw(ArgumentError("baseline evaluator did not use zero VPP commands"))
    baseline.reference_pv_capacity_kw == config.reference_pv_capacity_kw ||
        throw(ArgumentError("baseline evaluator used the wrong reference-PV capacity"))
    baseline.timestamp == Dates.format(config.timestamp, dateformat"yyyy-mm-dd HH:MM:SS") ||
        throw(ArgumentError("baseline evaluator used the wrong timestamp"))
    baseline_v2 = abs2.(baseline.primary_voltage_complex_pu)
    bus_ids = [bus.id for bus in data.network.buses]
    delta_v2 = config.vmax_pu^2 .- baseline_v2
    coefficients13 = [
        AxisScan.topology_coefficient(data.network, bus, 13) for bus in bus_ids
    ]
    coefficients30 = [
        AxisScan.topology_coefficient(data.network, bus, 30) for bus in bus_ids
    ]
    envelope = analyze_envelope(
        bus_ids, delta_v2, coefficients13, coefficients30, capacity.scales_kw;
        coefficient_epsilon=config.coefficient_epsilon,
        axis_tie_tolerance_kw=config.axis_tie_tolerance_kw,
        near_binding_tolerance_v2=config.near_binding_tolerance_v2,
        condition_number_threshold=config.condition_number_threshold,
    )
    ac_axis_kw = Dict(
        bus => parse(Float64, capacity.limiting_rows[bus].axis_capacity_kW)
        for bus in (13, 30)
    )
    relative_gap = Dict(
        13 => (envelope.ranking13.minimum_limit_kw - ac_axis_kw[13]) / ac_axis_kw[13],
        30 => (envelope.ranking30.minimum_limit_kw - ac_axis_kw[30]) / ac_axis_kw[30],
    )
    all_bus_rows = NamedTuple[]
    rank13 = Dict(row.bus => row.rank for row in envelope.ranking13.rows)
    rank30 = Dict(row.bus => row.rank for row in envelope.ranking30.rows)
    limit13 = Dict(row.bus => row.linear_axis_limit_kw for row in envelope.ranking13.rows)
    limit30 = Dict(row.bus => row.linear_axis_limit_kw for row in envelope.ranking30.rows)
    for index in eachindex(bus_ids)
        bus = bus_ids[index]
        push!(all_bus_rows, (
            bus=bus, baseline_ac_voltage_squared=baseline_v2[index],
            voltage_headroom_squared=delta_v2[index],
            coefficient_13_pu_per_pu=coefficients13[index],
            coefficient_30_pu_per_pu=coefficients30[index],
            coefficient_13_v2_per_kw=coefficients13[index] / Stage0.BASE_KW,
            coefficient_30_v2_per_kw=coefficients30[index] / Stage0.BASE_KW,
            axis_13_limit_kw=limit13[bus], axis_13_rank=rank13[bus],
            axis_30_limit_kw=limit30[bus], axis_30_rank=rank30[bus],
        ))
    end
    return (
        config=config, data=data, profile_index=profile_index, baseline=baseline,
        baseline_v2=baseline_v2, capacity=capacity, envelope=envelope,
        ac_axis_kw=ac_axis_kw, relative_gap=relative_gap,
        all_bus_rows=all_bus_rows,
        baseline_call_count=1, radial_or_direction_probe_executed=false,
    )
end

function csv_value(value)
    value isa Bool && return value ? "true" : "false"
    value isa AbstractFloat && isnan(value) && return "NaN"
    value isa AbstractFloat && isinf(value) && return value > 0 ? "Inf" : "-Inf"
    value isa AbstractFloat && return @sprintf("%.15g", value)
    value isa AbstractVector && return join(value, ';')
    return string(value)
end

function write_csv(path, rows, fields)
    open(path, "w") do io
        println(io, join(String.(fields), ','))
        for row in rows
            println(io, join((csv_value(getproperty(row, field)) for field in fields), ','))
        end
    end
    return path
end

function output_paths(output_directory)
    prefix = "ac_anchored_linear_corner_audit"
    return (
        all_bus=joinpath(output_directory, "$(prefix)_all_bus_limits.csv"),
        ranking13=joinpath(output_directory, "$(prefix)_axis_13_ranking.csv"),
        ranking30=joinpath(output_directory, "$(prefix)_axis_30_ranking.csv"),
        margins=joinpath(output_directory, "$(prefix)_corner_margins.csv"),
        summary=joinpath(output_directory, "$(prefix)_summary.csv"),
        report=joinpath(output_directory, "$(prefix)_report.md"),
        manifest=joinpath(output_directory, "$(prefix)_manifest.csv"),
        reproducibility=joinpath(output_directory, "$(prefix)_reproducibility_check.csv"),
    )
end

function ensure_output_policy(paths, overwrite)
    existing = [path for path in values(paths) if isfile(path)]
    isempty(existing) || overwrite || throw(ArgumentError(
        "refusing to overwrite audit outputs without --overwrite: $(join(existing, ", "))",
    ))
end

function ranking_output_rows(ranking)
    return [(
        rank=row.rank, bus=row.bus, delta_v2=row.delta_v2,
        coefficient_pu_per_pu=row.coefficient_pu_per_pu,
        coefficient_v2_per_kw=row.coefficient_v2_per_kw,
        controlling=row.controlling, linear_axis_limit_kw=row.linear_axis_limit_kw,
    ) for row in ranking.rows]
end

function summary_rows(result)
    config = result.config
    envelope = result.envelope
    baseline = result.baseline
    return [
        (key="diagnostic_variant", value=DIAGNOSTIC_VARIANT),
        (key="implementation_id", value=IMPLEMENTATION_ID),
        (key="timestamp", value=Dates.format(config.timestamp, dateformat"yyyy-mm-dd HH:MM:SS")),
        (key="baseline_source", value="abs2(primary AC fixed-injection phasor at zero VPP commands)"),
        (key="baseline_call_graph", value="run_analytical_audit->default_baseline_evaluator->AxisScan.evaluate_fixed_injection->Stage0.evaluate_point->Stage0.assemble_stage0_inputs->Stage0.primary_power_flow"),
        (key="baseline_p13_vpp_kw", value=csv_value(baseline.p13_vpp_kw)),
        (key="baseline_p30_vpp_kw", value=csv_value(baseline.p30_vpp_kw)),
        (key="reference_pv_capacity_kw", value=csv_value(config.reference_pv_capacity_kw)),
        (key="reference_pv_factor", value=csv_value(baseline.pv_factor)),
        (key="reference_pv_injection_kw", value=csv_value(baseline.actual_reference_pv_kw)),
        (key="load_multiplier", value=csv_value(result.data.profile.load_multiplier[result.profile_index])),
        (key="coefficient_epsilon", value=csv_value(config.coefficient_epsilon)),
        (key="axis_tie_tolerance_kw", value=csv_value(config.axis_tie_tolerance_kw)),
        (key="near_binding_tolerance_v2", value=csv_value(config.near_binding_tolerance_v2)),
        (key="condition_number_threshold", value=csv_value(config.condition_number_threshold)),
        (key="axis_13_argmin_buses", value=csv_value(envelope.ranking13.tie_buses)),
        (key="axis_13_classification", value=envelope.axis13_classification),
        (key="axis_13_linear_limit_kw", value=csv_value(envelope.ranking13.minimum_limit_kw)),
        (key="axis_13_ac_limit_kw", value=csv_value(result.ac_axis_kw[13])),
        (key="axis_13_relative_gap", value=csv_value(result.relative_gap[13])),
        (key="axis_30_argmin_buses", value=csv_value(envelope.ranking30.tie_buses)),
        (key="axis_30_classification", value=envelope.axis30_classification),
        (key="axis_30_linear_limit_kw", value=csv_value(envelope.ranking30.minimum_limit_kw)),
        (key="axis_30_ac_limit_kw", value=csv_value(result.ac_axis_kw[30])),
        (key="axis_30_relative_gap", value=csv_value(result.relative_gap[30])),
        (key="c_13_13_pu_per_pu", value=csv_value(envelope.matrix[1, 1])),
        (key="c_13_30_pu_per_pu", value=csv_value(envelope.matrix[1, 2])),
        (key="c_30_13_pu_per_pu", value=csv_value(envelope.matrix[2, 1])),
        (key="c_30_30_pu_per_pu", value=csv_value(envelope.matrix[2, 2])),
        (key="intersection_determinant", value=csv_value(envelope.determinant)),
        (key="intersection_condition_number", value=csv_value(envelope.condition_number)),
        (key="intersection_p13_kw", value=csv_value(envelope.p_kw[1])),
        (key="intersection_p30_kw", value=csv_value(envelope.p_kw[2])),
        (key="intersection_positive_quadrant", value=csv_value(envelope.positive_quadrant)),
        (key="intersection_normalized_residual_13", value=csv_value(envelope.normalized_residual[1])),
        (key="intersection_normalized_residual_30", value=csv_value(envelope.normalized_residual[2])),
        (key="corner_classification", value=envelope.classification),
        (key="minimum_margin_v2", value=csv_value(envelope.minimum_margin_v2)),
        (key="near_binding_buses", value=csv_value(envelope.near_binding_buses)),
        (key="violated_buses", value=csv_value(envelope.violated_buses)),
        (key="next_smallest_positive_margin_v2", value=csv_value(envelope.next_smallest_positive_margin_v2)),
        (key="active_inactive_separation_v2", value=csv_value(envelope.active_inactive_separation_v2)),
        (key="capacity_csv_committed_sha256", value=result.capacity.sha256),
        (key="normalization_scale_13_kw", value=csv_value(result.capacity.scales_kw[13])),
        (key="normalization_scale_30_kw", value=csv_value(result.capacity.scales_kw[30])),
        (key="normalized_angle_rad", value=csv_value(envelope.normalized_angle_rad)),
        (key="normalized_angle_deg", value=csv_value(envelope.normalized_angle_deg)),
        (key="raw_kw_angle_rad", value=csv_value(envelope.raw_kw_angle_rad)),
        (key="raw_kw_angle_deg", value=csv_value(envelope.raw_kw_angle_deg)),
        (key="raw_minus_normalized_angle_rad", value=csv_value(envelope.angle_difference_rad)),
        (key="raw_minus_normalized_angle_deg", value=csv_value(envelope.angle_difference_deg)),
        (key="radial_or_direction_probe_executed", value="false"),
        (key="scope_statement", value=NO_PROBE_STATEMENT),
    ]
end

function write_report(path, result)
    config = result.config
    envelope = result.envelope
    open(path, "w") do io
        println(io, "# AC-anchored LinDistFlow all-bus linear-corner audit")
        println(io)
        println(io, "- Diagnostic classification: **`$DIAGNOSTIC_VARIANT`**.")
        println(io, "- Phase-B commit: `$PHASE_B_COMMIT`.")
        println(io, "- Original preregistration commit: `$PREREGISTRATION_COMMIT`.")
        println(io, "- Limiting timestamp: `$(Dates.format(config.timestamp, dateformat"yyyy-mm-dd HH:MM:SS"))`.")
        println(io, "- Committed capacity CSV SHA-256: `$(result.capacity.sha256)` (computed from the Phase-B Git blob, not CRLF-translated checkout bytes).")
        println(io, "- Command: `$(config.exact_command)`.")
        println(io)
        println(io, "## Exact baseline provenance")
        println(io)
        println(io, "The baseline squared voltage is `v_j^0 = abs2(primary_voltage_complex_pu[j])` from one corrected fixed-injection AC solve at `P13_VPP=P30_VPP=0`. The production data path is `run_analytical_audit -> default_baseline_evaluator -> AxisScan.evaluate_fixed_injection -> Stage0.evaluate_point -> Stage0.assemble_stage0_inputs -> Stage0.primary_power_flow`. The assembly reads the canonical timestamp's load multiplier and PV factor, places `850*f_t` kW of reference PV at bus 13, applies zero VPP injection at buses 13 and 30, scales the canonical active and reactive loads, converts net demand on the 10,000-kW base, and solves the radial AC equations. The primary phasors—not the replay voltage vector and not a flat classical-LinDistFlow baseline—supply `v_j^0`.")
        println(io)
        println(io, "At this timestamp, `f_t=$(csv_value(result.baseline.pv_factor))`, reference PV is `$(csv_value(result.baseline.actual_reference_pv_kw)) kW`, and the load multiplier is `$(csv_value(result.data.profile.load_multiplier[result.profile_index]))`.")
        println(io)
        println(io, "## Complete all-bus axis rankings")
        println(io)
        println(io, "Coefficients at or below `$(config.coefficient_epsilon)` are non-controlling and reported as `Inf`. Axis ties use an absolute `$(config.axis_tie_tolerance_kw) kW` tolerance.")
        for (axis, ranking, classification) in (
            (13, envelope.ranking13, envelope.axis13_classification),
            (30, envelope.ranking30, envelope.axis30_classification),
        )
            println(io)
            println(io, "### Axis $axis — `$classification`")
            println(io)
            println(io, "| Rank | Bus | Delta v^2 | c(j,$axis) | Limit (kW) |")
            println(io, "|---:|---:|---:|---:|---:|")
            for row in ranking.rows
                println(io, "| $(row.rank) | $(row.bus) | $(csv_value(row.delta_v2)) | $(csv_value(row.coefficient_pu_per_pu)) | $(csv_value(row.linear_axis_limit_kw)) |")
            end
        end
        println(io)
        println(io, "Axis 13: linear `$(csv_value(envelope.ranking13.minimum_limit_kw)) kW`, exact AC `$(csv_value(result.ac_axis_kw[13])) kW`, relative gap `$(csv_value(result.relative_gap[13]))`. Axis 30: linear `$(csv_value(envelope.ranking30.minimum_limit_kw)) kW`, exact AC `$(csv_value(result.ac_axis_kw[30])) kW`, relative gap `$(csv_value(result.relative_gap[30]))`. These are two axis results only and establish no complete two-dimensional inclusion relation.")
        println(io)
        println(io, "## Bus-13/bus-30 candidate intersection")
        println(io)
        println(io, "The coefficient matrix in squared-voltage per per-unit power is `[$(csv_value(envelope.matrix[1,1])) $(csv_value(envelope.matrix[1,2])); $(csv_value(envelope.matrix[2,1])) $(csv_value(envelope.matrix[2,2]))]`; its determinant is `$(csv_value(envelope.determinant))` and 2-norm condition number is `$(csv_value(envelope.condition_number))` (threshold `$(csv_value(config.condition_number_threshold))`).")
        println(io)
        println(io, "The equality intersection is `P13*=$(csv_value(envelope.p_kw[1])) kW`, `P30*=$(csv_value(envelope.p_kw[2])) kW`; both coordinates are strictly positive: `$(envelope.positive_quadrant)`. Normalized equality residuals are `$(csv_value(envelope.normalized_residual[1]))` and `$(csv_value(envelope.normalized_residual[2]))`.")
        println(io)
        println(io, "The selected-line intercept inequalities are `L(13,13)<L(30,13): $(envelope.cross_axis_inequalities.bus13_beats_bus30_on_axis13)` and `L(30,30)<L(13,30): $(envelope.cross_axis_inequalities.bus30_beats_bus13_on_axis30)`. Together with nonnegative coefficients and a nonsingular, well-conditioned matrix, the opposite intercept ordering places the two selected-line intersection in the open positive quadrant.")
        println(io)
        println(io, "## Full-envelope exposure check — `$(envelope.classification)`")
        println(io)
        println(io, "All bus constraints were evaluated at the candidate. Minimum margin: `$(csv_value(envelope.minimum_margin_v2))`; near-binding tolerance: `$(csv_value(config.near_binding_tolerance_v2))`; near-binding buses: `$(csv_value(envelope.near_binding_buses))`; violated buses: `$(csv_value(envelope.violated_buses))`; next-smallest positive inactive margin: `$(csv_value(envelope.next_smallest_positive_margin_v2))`; active/inactive separation: `$(csv_value(envelope.active_inactive_separation_v2))`.")
        println(io)
        println(io, "## Fixed normalized direction")
        println(io)
        println(io, "Using `s13=$(csv_value(result.capacity.scales_kw[13])) kW` and `s30=$(csv_value(result.capacity.scales_kw[30])) kW`, the normalized corner direction is `theta*=$(csv_value(envelope.normalized_angle_rad)) rad = $(csv_value(envelope.normalized_angle_deg)) deg`. The diagnostic raw-kW angle is `$(csv_value(envelope.raw_kw_angle_rad)) rad = $(csv_value(envelope.raw_kw_angle_deg)) deg`, a difference of `$(csv_value(envelope.angle_difference_rad)) rad = $(csv_value(envelope.angle_difference_deg)) deg`. The raw-kW angle must not be used by the normalized radial probe.")
        println(io)
        println(io, "## Scope")
        println(io)
        println(io, NO_PROBE_STATEMENT)
    end
    return path
end

function manifest_rows(result, paths)
    root = result.config.repository_root
    status = git_output(root, "status", "--short")
    rows = [
        (key="phase_b_commit", value=PHASE_B_COMMIT),
        (key="original_preregistration_commit", value=PREREGISTRATION_COMMIT),
        (key="artifact_commit", value="SELF_REFERENCE: Git commit containing this manifest"),
        (key="generation_git_head", value=git_output(root, "rev-parse", "HEAD")),
        (key="generation_worktree_clean", value=isempty(status) ? "true" : "false"),
        (key="generation_git_status_sha256", value=sha256_hex(Vector{UInt8}(codeunits(status)))),
        (key="julia_version", value=string(VERSION)),
        (key="machine_architecture", value=Sys.MACHINE),
        (key="operating_system", value=string(Sys.KERNEL)),
        (key="julia_threads", value=string(Threads.nthreads())),
        (key="manifest_toml_sha256", value=sha256_file(joinpath(root, "Manifest.toml"))),
        (key="network_input_path", value="src/data/ieee33.jl"),
        (key="network_input_sha256", value=sha256_file(joinpath(root, "src", "data", "ieee33.jl"))),
        (key="profile_input_path", value="data_processed/ausgrid/ausgrid_halfhour_normalized.csv"),
        (key="profile_input_sha256", value=sha256_file(joinpath(root, "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv"))),
        (key="capacity_input_git_object", value="$PHASE_B_COMMIT:$CAPACITY_RELATIVE_PATH"),
        (key="capacity_input_committed_sha256", value=result.capacity.sha256),
        (key="diagnostic_variant", value=DIAGNOSTIC_VARIANT),
        (key="implementation_id", value=IMPLEMENTATION_ID),
        (key="runner_path", value="scripts/run_dso_vpp_ac_anchored_linear_corner_audit.jl"),
        (key="exact_command", value=result.config.exact_command),
        (key="execution_scope", value="ONE_AC_FIXED_INJECTION_BASELINE_PLUS_ANALYTICAL_LINEAR_ALGEBRA"),
        (key="radial_or_direction_probe_executed", value="false"),
    ]
    for name in (:all_bus, :ranking13, :ranking30, :margins, :summary, :report,
                 :reproducibility)
        path = getproperty(paths, name)
        isfile(path) || continue
        push!(rows, (key="output_sha256_$(basename(path))", value=sha256_file(path)))
    end
    return rows
end

function write_audit_artifacts(config::AuditConfig=AuditConfig())
    validate_config(config)
    paths = output_paths(config.output_directory)
    mkpath(config.output_directory)
    ensure_output_policy(paths, config.overwrite)
    result = run_analytical_audit(config)
    write_csv(paths.all_bus, result.all_bus_rows, propertynames(first(result.all_bus_rows)))
    ranking13 = ranking_output_rows(result.envelope.ranking13)
    ranking30 = ranking_output_rows(result.envelope.ranking30)
    write_csv(paths.ranking13, ranking13, propertynames(first(ranking13)))
    write_csv(paths.ranking30, ranking30, propertynames(first(ranking30)))
    write_csv(paths.margins, result.envelope.margin_rows,
              propertynames(first(result.envelope.margin_rows)))
    summary = summary_rows(result)
    write_csv(paths.summary, summary, (:key, :value))
    write_report(paths.report, result)
    write_csv(paths.manifest, manifest_rows(result, paths), (:key, :value))
    return merge(result, (paths=paths,))
end

const SCIENTIFIC_OUTPUTS = (:all_bus, :ranking13, :ranking30, :margins, :summary, :report)

function write_reproducibility_check(primary_directory, duplicate_directory,
                                     output_path)
    primary_paths = output_paths(primary_directory)
    duplicate_paths = output_paths(duplicate_directory)
    rows = NamedTuple[]
    for name in SCIENTIFIC_OUTPUTS
        primary = getproperty(primary_paths, name)
        duplicate = getproperty(duplicate_paths, name)
        primary_bytes = read(primary)
        duplicate_bytes = read(duplicate)
        push!(rows, (
            artifact=basename(primary), primary_sha256=sha256_hex(primary_bytes),
            duplicate_sha256=sha256_hex(duplicate_bytes),
            scientific_mismatches=primary_bytes == duplicate_bytes ? 0 : 1,
        ))
    end
    write_csv(output_path, rows, propertynames(first(rows)))
    sum(row.scientific_mismatches for row in rows) == 0 ||
        throw(ArgumentError("fresh regeneration has scientific mismatches"))
    return rows
end

function refresh_manifest(result)
    write_csv(result.paths.manifest, manifest_rows(result, result.paths), (:key, :value))
    return result.paths.manifest
end

export AuditConfig, DIAGNOSTIC_VARIANT, IMPLEMENTATION_ID, PHASE_B_COMMIT,
       PREREGISTRATION_COMMIT, CAPACITY_RELATIVE_PATH, EXPECTED_CAPACITY_SHA256,
       LIMITING_TIMESTAMP, NO_PROBE_STATEMENT, committed_capacity_data,
       axis_ranking, axis_classification, analyze_envelope,
       default_baseline_evaluator, run_analytical_audit, output_paths,
       write_audit_artifacts, write_reproducibility_check, refresh_manifest

end
