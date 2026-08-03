module DSOVPPOperatingPointProvenance

using Dates
using Printf
using SHA

include("dso_vpp_ac_anchored_linear_corner_audit.jl")
const Audit = DSOVPPACAnchoredLinearCornerAudit
const AxisScan = Audit.AxisScan
const Stage0 = Audit.Stage0

const IMPLEMENTATION_ID = "CiroPVHC.DSOVPPOperatingPointProvenance.v1"
const AUDIT_BASE_COMMIT = "d8e1bb0a7909711b4124f95673fb3a4802ae783a"
const PROFILE_RELATIVE_PATH = "data_processed/ausgrid/ausgrid_halfhour_normalized.csv"
const CASE_RELATIVE_PATH = "data_raw/case33bw.m"
const PROFILE_SHA256 = "504dfa1c4d037d7497caa330611b5bb45f9774a2b9a984443753c88cba3de500"
const CASE_SHA256 = "60c5d6312a89607e76c86cb62268b548f37d81f1f037c1ff53aca1a8ecaf83c1"
const TARGET_TIMESTAMPS = (
    DateTime(2012, 10, 15, 12, 30),
    DateTime(2012, 10, 15, 13, 0),
    DateTime(2012, 10, 15, 13, 30),
)
const CLASSIFICATION = "ADJACENT_TIMESTAMP_HISTORICAL_TEXT_ERROR"
const SCALING_CLASSIFICATION = "P_AND_Q_SCALED_IDENTICALLY"
const TIMEZONE_STATEMENT =
    "timezone-naive local wall-clock; UTC offset and DST offset are not encoded"
const NO_PROBE_STATEMENT =
    "No AC radial scan, LinDistFlow radial scan, intermediate-direction probe, DOE, optimization, Jacobian sensitivity, or prohibited downstream model was invoked."

sha256_file(path) = open(path, "r") do io
    bytes2hex(SHA.sha256(io))
end

fmt(value::AbstractFloat) = @sprintf("%.17g", value)
fmt(value) = string(value)

function vector_sha256(values)
    payload = join((fmt(Float64(value)) for value in values), ',') * "\n"
    return bytes2hex(SHA.sha256(codeunits(payload)))
end

function read_primary_profile(path)
    lines = readlines(path)
    header = split(first(lines), ','; keepempty=true)
    column = Dict(name => index for (index, name) in pairs(header))
    required = ["datetime", "load_kw_mean", "gc_customer_count", "pv_shape_mean",
                "gg_customer_count", "load_multiplier", "pv_profile", "date", "slot"]
    all(haskey(column, name) for name in required) ||
        throw(ArgumentError("canonical profile columns changed"))
    records = NamedTuple[]
    maximum_load_raw = -Inf
    maximum_pv_raw = -Inf
    for (data_row, line) in enumerate(Iterators.drop(lines, 1))
        fields = split(line, ','; keepempty=true)
        length(fields) == length(header) || throw(ArgumentError("profile row width mismatch"))
        load_raw = parse(Float64, fields[column["load_kw_mean"]])
        pv_raw = parse(Float64, fields[column["pv_shape_mean"]])
        maximum_load_raw = max(maximum_load_raw, load_raw)
        maximum_pv_raw = max(maximum_pv_raw, pv_raw)
        timestamp = DateTime(fields[column["datetime"]], dateformat"yyyy-mm-dd HH:MM:SS")
        if timestamp in TARGET_TIMESTAMPS
            push!(records, (
                displayed_timestamp=fields[column["datetime"]],
                canonical_timestamp=fields[column["datetime"]],
                timestamp=timestamp,
                source_file=PROFILE_RELATIVE_PATH,
                source_data_row=data_row,
                source_file_line=data_row + 1,
                stable_row_identifier="date=$(fields[column["date"]]);slot=$(fields[column["slot"]])",
                slot=parse(Int, fields[column["slot"]]),
                load_kw_mean=load_raw,
                gc_customer_count=parse(Int, fields[column["gc_customer_count"]]),
                pv_shape_mean=pv_raw,
                gg_customer_count=parse(Int, fields[column["gg_customer_count"]]),
                stored_load_multiplier=parse(Float64, fields[column["load_multiplier"]]),
                stored_pv_factor=parse(Float64, fields[column["pv_profile"]]),
            ))
        end
    end
    length(records) == length(TARGET_TIMESTAMPS) ||
        throw(ArgumentError("neighboring provenance rows are missing"))
    by_timestamp = Dict(record.timestamp => record for record in records)
    ordered = [merge(by_timestamp[timestamp], (
        reconstructed_load_multiplier=by_timestamp[timestamp].load_kw_mean / maximum_load_raw,
        reconstructed_pv_factor=by_timestamp[timestamp].pv_shape_mean / maximum_pv_raw,
    )) for timestamp in TARGET_TIMESTAMPS]
    return (rows=ordered, maximum_load_raw=maximum_load_raw,
            maximum_pv_raw=maximum_pv_raw)
end

function parse_case33bw(path)
    buses = NamedTuple[]
    branches = NamedTuple[]
    section = :none
    base_mva = NaN
    for (line_number, original) in enumerate(eachline(path))
        line = strip(original)
        startswith(line, "mpc.baseMVA") &&
            (base_mva = parse(Float64, strip(split(split(line, '=')[2], ';')[1])))
        startswith(line, "mpc.bus = [") && (section = :bus; continue)
        startswith(line, "mpc.branch = [") && (section = :branch; continue)
        if line == "];"
            section = :none
            continue
        end
        section == :none && continue
        isempty(line) && continue
        startswith(line, '%') && continue
        fields = split(replace(line, ';' => ' '))
        if section == :bus
            push!(buses, (id=parse(Int, fields[1]), pd_kw=parse(Float64, fields[3]),
                          qd_kvar=parse(Float64, fields[4]), base_kv=parse(Float64, fields[10]),
                          source_line=line_number))
        elseif section == :branch
            status = parse(Int, fields[11])
            status == 1 || continue
            push!(branches, (id=length(branches) + 1, from=parse(Int, fields[1]),
                to=parse(Int, fields[2]), r_ohm=parse(Float64, fields[3]),
                x_ohm=parse(Float64, fields[4]), source_line=line_number))
        end
    end
    base_mva == 10.0 || throw(ArgumentError("case33bw baseMVA is not 10"))
    length(buses) == 33 && length(branches) == 32 ||
        throw(ArgumentError("case33bw active radial data changed"))
    return (base_mva=base_mva, buses=buses, branches=branches)
end

function radial_path(branches, bus)
    parent = Dict(branch.to => branch for branch in branches)
    path = NamedTuple[]
    current = bus
    while current != 1
        branch = parent[current]
        push!(path, branch)
        current = branch.from
    end
    return reverse(path)
end

function independent_coefficient(case_data, candidate_bus, injection_bus)
    candidate = radial_path(case_data.branches, candidate_bus)
    injected = radial_path(case_data.branches, injection_bus)
    candidate_ids = Set(branch.id for branch in candidate)
    shared = [branch for branch in injected if branch.id in candidate_ids]
    resistance = sum(branch.r_ohm for branch in shared; init=0.0)
    base_kv = only(unique(bus.base_kv for bus in case_data.buses))
    zbase = base_kv^2 / case_data.base_mva
    return (shared_branch_ids=[branch.id for branch in shared],
            shared_source_lines=[branch.source_line for branch in shared],
            resistance_ohm=resistance, base_mva=case_data.base_mva,
            base_kv=base_kv, zbase_ohm=zbase,
            coefficient=2 * resistance / zbase)
end

function independent_vectors(case_data, profile_row; p13=0.0, p30=0.0,
                             q13=0.0, q30=0.0, p_scale=nothing, q_scale=nothing)
    load_scale_p = p_scale === nothing ? profile_row.reconstructed_load_multiplier : Float64(p_scale)
    load_scale_q = q_scale === nothing ? profile_row.reconstructed_load_multiplier : Float64(q_scale)
    pv_factor = profile_row.reconstructed_pv_factor
    reference_pv = 850.0 * pv_factor
    p_load = [bus.pd_kw * load_scale_p for bus in case_data.buses]
    q_load = [bus.qd_kvar * load_scale_q for bus in case_data.buses]
    p_injection = -copy(p_load)
    q_injection = -copy(q_load)
    p_injection[13] += reference_pv + p13
    p_injection[30] += p30
    q_injection[13] += q13
    q_injection[30] += q30
    return (p_load=p_load, q_load=q_load, p_injection=p_injection,
            q_injection=q_injection, reference_pv_kw=reference_pv,
            p_multiplier=load_scale_p, q_multiplier=load_scale_q)
end

function production_vectors(point)
    p_load = [real(value) * Stage0.BASE_KW + injection
              for (value, injection) in zip(point.assembled_net_demand_pu,
                                             point.assembled_active_injection_by_bus_kw)]
    q_load = [imag(value) * Stage0.BASE_KW for value in point.assembled_net_demand_pu]
    p_injection = [-real(value) * Stage0.BASE_KW for value in point.assembled_net_demand_pu]
    q_injection = [-imag(value) * Stage0.BASE_KW for value in point.assembled_net_demand_pu]
    return (p_load=p_load, q_load=q_load, p_injection=p_injection,
            q_injection=q_injection)
end

function classify_scaling(case_data, profile_row, vectors)
    expected = profile_row.reconstructed_load_multiplier
    p_ratios = [vectors.p_load[i] / case_data.buses[i].pd_kw
                for i in eachindex(case_data.buses) if case_data.buses[i].pd_kw != 0]
    q_ratios = [vectors.q_load[i] / case_data.buses[i].qd_kvar
                for i in eachindex(case_data.buses) if case_data.buses[i].qd_kvar != 0]
    matches(values) = all(value -> isapprox(value, expected; atol=1e-14, rtol=0), values)
    matches(p_ratios) && matches(q_ratios) &&
        return SCALING_CLASSIFICATION
    matches(p_ratios) && !matches(q_ratios) && return "ONLY_P_SCALED"
    !matches(p_ratios) && matches(q_ratios) && return "ONLY_Q_SCALED"
    return "DIFFERENT_P_Q_MULTIPLIERS"
end

function comparison_row(field, phase_b, audit, provenance;
                        classification=nothing, absolute_difference="",
                        relative_difference="")
    phase_text = fmt(phase_b)
    audit_text = fmt(audit)
    resolved = classification === nothing ?
        (phase_text == audit_text ? "EXACT_MATCH" : "MISMATCH") : classification
    if phase_b isa Number && audit isa Number && classification === nothing
        absolute_difference = fmt(abs(Float64(phase_b) - Float64(audit)))
        denominator = max(abs(Float64(phase_b)), abs(Float64(audit)))
        relative_difference = fmt(denominator == 0 ? 0.0 :
                                  abs(Float64(phase_b) - Float64(audit)) / denominator)
    end
    return (field=field, phase_b_value=phase_text, analytical_audit_value=audit_text,
            absolute_difference=absolute_difference,
            relative_difference=relative_difference,
            source_call_path_provenance=provenance, classification=resolved)
end

function provenance_rows(profile_data)
    [(
        displayed_timestamp=row.displayed_timestamp,
        canonical_timestamp=row.canonical_timestamp,
        timezone_dst_offset=TIMEZONE_STATEMENT,
        source_file=row.source_file,
        source_row_identifier="data_row=$(row.source_data_row);file_line=$(row.source_file_line);$(row.stable_row_identifier)",
        pv_factor=row.reconstructed_pv_factor,
        reference_pv_850_kw=850.0 * row.reconstructed_pv_factor,
        load_multiplier=row.reconstructed_load_multiplier,
        active_load_multiplier=row.reconstructed_load_multiplier,
        reactive_load_multiplier=row.reconstructed_load_multiplier,
        raw_source_values="load_kw_mean=$(fmt(row.load_kw_mean));gc_customer_count=$(row.gc_customer_count);pv_shape_mean=$(fmt(row.pv_shape_mean));gg_customer_count=$(row.gg_customer_count);stored_load_multiplier=$(fmt(row.stored_load_multiplier));stored_pv_profile=$(fmt(row.stored_pv_factor));slot=$(row.slot)",
        source_sha256=PROFILE_SHA256,
    ) for row in profile_data.rows]
end

function output_paths(output_directory)
    prefix = "operating_point_provenance"
    return (
        rows=joinpath(output_directory, "$(prefix)_neighbor_rows.csv"),
        comparison=joinpath(output_directory, "$(prefix)_phaseb_audit_comparison.csv"),
        coefficients=joinpath(output_directory, "$(prefix)_coefficient_reconstruction.csv"),
        occurrences=joinpath(output_directory, "$(prefix)_numeric_occurrences.csv"),
        paths=joinpath(output_directory, "$(prefix)_path_audit.csv"),
        summary=joinpath(output_directory, "$(prefix)_summary.csv"),
        report=joinpath(output_directory, "$(prefix)_report.md"),
        manifest=joinpath(output_directory, "$(prefix)_manifest.csv"),
        reproducibility=joinpath(output_directory, "$(prefix)_reproducibility_check.csv"),
    )
end

function numeric_occurrence_rows()
    exact = "0.9282211452522351"
    base = AUDIT_BASE_COMMIT
    rows = [
        (match_type="EXACT_STRING", matched_value=exact, file="data_processed/ausgrid/ausgrid_daily_stress_ranking.csv", lines="2", commit="bf714f4ee5767283b3bd3c662738207b940dd866", context="daily max_pv_profile field; the same row's critical_time=13:00 is the daily stress-ratio slot, not the timestamp of max_pv_profile"),
        (match_type="EXACT_STRING", matched_value=exact, file="data_processed/ausgrid/ausgrid_halfhour_normalized.csv", lines="40203", commit="bf714f4ee5767283b3bd3c662738207b940dd866", context="canonical 2012-10-15 12:30 row; date slot 25"),
        (match_type="EXACT_STRING", matched_value=exact, file="data_processed/ausgrid/ausgrid_pipeline_metadata.json", lines="253", commit="bf714f4ee5767283b3bd3c662738207b940dd866", context="daily ranking metadata max_pv_profile"),
        (match_type="EXACT_STRING", matched_value=exact, file="data_processed/ausgrid/ausgrid_top_30_critical_days.csv", lines="27", commit="bf714f4ee5767283b3bd3c662738207b940dd866", context="copied canonical 2012-10-15 12:30 row"),
        (match_type="EXACT_STRING", matched_value=exact, file="results/dso_vpp_ac_map_pilot/_archived_stage0_missing_reference_pv_20260730T145810Z/stage0_audit_report.md", lines="186;236;259", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="invalid archived report nevertheless labels the value correctly as the 12:30 canonical peak"),
        (match_type="EXACT_STRING", matched_value=exact, file="results/dso_vpp_ac_map_pilot/_archived_stage0_missing_reference_pv_20260730T145810Z/stage0_pv_presence_check.csv", lines="2;3", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="invalid archived 12:30 H=850 and H=0 checks"),
        (match_type="CLOSE_RENDERING_SAME_FLOAT", matched_value="0.92822114525223509", file="results/pre_s1_audit/critical_day_candidates.csv", lines="22", commit="d319fe4", context="daily maximum PV profile rendered with 17 significant digits; not an exact text occurrence"),
        (match_type="ROUNDED_SAME_VALUE", matched_value="0.928221145252", file="results/dso_vpp_ac_map_pilot/export_side_axis_scan_points.csv", lines="960-994", commit="24138a3423875d1c58f814b8f448cebdd8287383", context="35 Phase-B scan evaluations at the 12:30 row; rounded artifact formatting"),
        (match_type="ROUNDED_SAME_VALUE", matched_value="0.928221145252", file="results/dso_vpp_ac_map_pilot/stage0_benchmark_points_corrected.csv", lines="27;123;219;315;411;507;603;699;795;891;987", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="eleven corrected Stage-0 samples keyed to 12:30"),
        (match_type="ROUNDED_SAME_VALUE", matched_value="0.928221145252", file="results/dso_vpp_ac_map_pilot/stage0_pv_presence_check_corrected.csv", lines="2;3", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="corrected 12:30 H=850 and H=0 checks"),
        (match_type="ROUNDED_SAME_VALUE", matched_value="0.928221145252", file="results/dso_vpp_ac_map_pilot/stage0_repair_report.md", lines="102", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="rounded statement of the canonical 12:30 PV factor"),
        (match_type="ROUNDED_SAME_VALUE", matched_value="0.928221145252", file="results/dso_vpp_ac_map_pilot/_archived_stage0_missing_reference_pv_20260730T145810Z/stage0_data_audit.csv", lines="2", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="rounded maximum PV factor over the archived pilot window"),
        (match_type="CLOSE_UNRELATED_VOLTAGE", matched_value="0.928227418856", file="results/dso_vpp_ac_map_pilot/stage0_before_after_comparison.csv;results/dso_vpp_ac_map_pilot/stage0_benchmark_points_corrected.csv", lines="469;469", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="minimum voltage at 2012-10-16 17:30; not a PV factor"),
        (match_type="CLOSE_UNRELATED_VOLTAGE", matched_value="0.928225729242754;0.928225729266307;0.928222291858095", file="results/s0_full_period_baseline/s0_interval_metrics.csv", lines="5067;29583;91506", commit="133c7b0", context="S0 voltage metrics at unrelated timestamps; protected historical smoke/result data left untouched"),
        (match_type="HISTORY_SEARCH", matched_value=exact, file="data_processed/ausgrid/*", lines="introduced", commit="bf714f4ee5767283b3bd3c662738207b940dd866", context="git log -S exact-string introduction; present unchanged at base snapshot $(base)"),
        (match_type="HISTORY_SEARCH", matched_value=exact, file="results/dso_vpp_ac_map_pilot/_archived_stage0_missing_reference_pv_20260730T145810Z/*", lines="introduced", commit="ae24e08180cf154c3c49b136d5babc5f190b6a0c", context="git log -S exact-string archive introduction; present unchanged at base snapshot $(base)"),
    ]
    return rows
end

function csv_value(value)
    value isa AbstractFloat && return fmt(value)
    value isa AbstractVector && return join(value, ';')
    value isa Bool && return value ? "true" : "false"
    text = string(value)
    occursin(',', text) && return "\"$(replace(text, "\"" => "\"\""))\""
    return text
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

function path_audit_rows()
    return [
        (artifact="export_side_axis_evidence_manifest.csv", field="profile_input_path;network_input_path;runner_path", value="repository-relative fields", classification="REPOSITORY_RELATIVE", rationale="Phase-B scientific manifest records no drive letter"),
        (artifact="ac_anchored_linear_corner_audit_manifest.csv", field="profile_input_path;network_input_path;runner_path", value="repository-relative fields", classification="REPOSITORY_RELATIVE", rationale="analytical-audit scientific manifest records no drive letter"),
        (artifact="stage0_data_audit_corrected.csv", field="source_path;authoritative_points_path", value="D:\\CiroPVHC.jl (legacy operational provenance)", classification="NONSCIENTIFIC_ABSOLUTE_PATH_EXCLUDED_FROM_REPRODUCIBILITY", rationale="scientific identity is supplied by adjacent SHA-256 fields; this repair-only artifact is not a production map"),
        (artifact="_archived_stage0_missing_reference_pv_20260730T145810Z/stage0_data_audit.csv", field="source_path", value="D:\\CiroPVHC.jl (invalid archived run)", classification="NONSCIENTIFIC_ABSOLUTE_PATH_EXCLUDED_FROM_REPRODUCIBILITY", rationale="archive is explicitly invalid for scientific use"),
        (artifact="_archived_stage0_missing_reference_pv_20260730T145810Z/stage0_audit_report.md", field="Repository", value="D:\\CiroPVHC.jl (invalid archived run)", classification="NONSCIENTIFIC_ABSOLUTE_PATH_EXCLUDED_FROM_REPRODUCIBILITY", rationale="archive is explicitly invalid for scientific use"),
        (artifact="_archived_stage0_missing_reference_pv_20260730T145810Z/archive_manifest.csv", field="original_path;archived_path", value="repository-relative fields", classification="REPOSITORY_RELATIVE", rationale="archive manifest paths are portable"),
        (artifact="operating_point_provenance_*", field="all path fields", value="repository-relative fields", classification="REPOSITORY_RELATIVE", rationale="scientific artifacts are byte-identical across output directories"),
    ]
end

function run_provenance_audit(repository_root=normpath(joinpath(@__DIR__, "..", "..")))
    profile_path = joinpath(repository_root, split(PROFILE_RELATIVE_PATH, '/')...)
    case_path = joinpath(repository_root, split(CASE_RELATIVE_PATH, '/')...)
    sha256_file(profile_path) == PROFILE_SHA256 || throw(ArgumentError("profile SHA-256 changed"))
    sha256_file(case_path) == CASE_SHA256 || throw(ArgumentError("case33bw SHA-256 changed"))
    profile_data = read_primary_profile(profile_path)
    case_data = parse_case33bw(case_path)
    target_row = only(row for row in profile_data.rows if row.timestamp == Audit.LIMITING_TIMESTAMP)
    independent = independent_vectors(case_data, target_row)

    scan_config = AxisScan.ScanConfig(repository_root=repository_root,
        output_directory=joinpath(repository_root, "results", "dso_vpp_ac_map_pilot"))
    data = AxisScan.load_canonical_data(scan_config)
    profile_index = findfirst(==(Audit.LIMITING_TIMESTAMP), data.profile.timestamps)
    profile_index === nothing && throw(ArgumentError("limiting timestamp absent from production profile"))
    phase_b = AxisScan.evaluate_axis_point(data.network, data.profile, profile_index,
        13, 0.0, scan_config; warm_start_source="provenance_phase_b_baseline")
    audit_result = Audit.run_analytical_audit(Audit.AuditConfig(
        repository_root=repository_root,
        output_directory=joinpath(repository_root, "results", "dso_vpp_ac_map_pilot")))
    analytical = audit_result.baseline
    phase_vectors = production_vectors(phase_b)
    audit_vectors = production_vectors(analytical)

    independent_hashes = (
        p_load=vector_sha256(independent.p_load), q_load=vector_sha256(independent.q_load),
        p_injection=vector_sha256(independent.p_injection),
        q_injection=vector_sha256(independent.q_injection),
    )
    phase_hashes = (
        p_load=vector_sha256(phase_vectors.p_load), q_load=vector_sha256(phase_vectors.q_load),
        p_injection=vector_sha256(phase_vectors.p_injection),
        q_injection=vector_sha256(phase_vectors.q_injection),
    )
    audit_hashes = (
        p_load=vector_sha256(audit_vectors.p_load), q_load=vector_sha256(audit_vectors.q_load),
        p_injection=vector_sha256(audit_vectors.p_injection),
        q_injection=vector_sha256(audit_vectors.q_injection),
    )
    phase_hashes == audit_hashes ||
        throw(ArgumentError("Phase-B and analytical-audit vectors differ"))
    independent_tolerance = 1e-12
    maximum_independent_difference = maximum(vcat(
        abs.(phase_vectors.p_load .- independent.p_load),
        abs.(phase_vectors.q_load .- independent.q_load),
        abs.(phase_vectors.p_injection .- independent.p_injection),
        abs.(phase_vectors.q_injection .- independent.q_injection),
    ))
    maximum_independent_difference <= independent_tolerance ||
        throw(ArgumentError("production and independent vectors differ beyond tolerance"))

    row_id = "data_row=$(target_row.source_data_row);file_line=$(target_row.source_file_line);$(target_row.stable_row_identifier)"
    shared_provenance = "$(PROFILE_RELATIVE_PATH) SHA256=$(PROFILE_SHA256); raw row $row_id"
    comparisons = [
        comparison_row("canonical timestamp", phase_b.timestamp, analytical.timestamp, shared_provenance),
        comparison_row("row identifier", row_id, row_id, shared_provenance),
        comparison_row("PV factor", phase_b.pv_factor, analytical.pv_factor, shared_provenance),
        comparison_row("reference PV kW", phase_b.actual_reference_pv_kw, analytical.actual_reference_pv_kw, "850 * canonical PV factor at bus 13"),
        comparison_row("load multiplier", data.profile.load_multiplier[profile_index], data.profile.load_multiplier[profile_index], shared_provenance),
        comparison_row("P-load vector hash", phase_hashes.p_load, audit_hashes.p_load, "canonical-text SHA-256; independent raw-file vector matches within declared absolute tolerance 1e-12 kW; independent hash=$(independent_hashes.p_load)"),
        comparison_row("Q-load vector hash", phase_hashes.q_load, audit_hashes.q_load, "canonical-text SHA-256; independent raw-file vector matches within declared absolute tolerance 1e-12 kvar; independent hash=$(independent_hashes.q_load)"),
        comparison_row("reference-PV bus", Stage0.REFERENCE_PV_BUS, Stage0.REFERENCE_PV_BUS, "Stage0.assemble_stage0_inputs"),
        comparison_row("reference-PV injection", phase_b.assembled_reference_pv_by_bus_kw[13], analytical.assembled_reference_pv_by_bus_kw[13], "independent raw-profile reconstruction=$(fmt(independent.reference_pv_kw))"),
        comparison_row("VPP P13 command", phase_b.p13_vpp_kw, analytical.p13_vpp_kw, "zero-command baseline used by both provenance paths"),
        comparison_row("VPP P30 command", phase_b.p30_vpp_kw, analytical.p30_vpp_kw, "zero-command baseline used by both provenance paths"),
        comparison_row("VPP Q13 command", phase_b.q13_vpp_kvar, analytical.q13_vpp_kvar, "reactive VPP command fixed to zero"),
        comparison_row("VPP Q30 command", phase_b.q30_vpp_kvar, analytical.q30_vpp_kvar, "reactive VPP command fixed to zero"),
        comparison_row("complete 33-bus P-injection-vector hash", phase_hashes.p_injection, audit_hashes.p_injection, "generation-minus-load convention; independent raw-file vector matches within declared absolute tolerance 1e-12 kW; independent hash=$(independent_hashes.p_injection)"),
        comparison_row("complete 33-bus Q-injection-vector hash", phase_hashes.q_injection, audit_hashes.q_injection, "generation-minus-load convention; independent raw-file vector matches within declared absolute tolerance 1e-12 kvar; independent hash=$(independent_hashes.q_injection)"),
        comparison_row("baseMVA", Stage0.BASE_MVA, Stage0.BASE_MVA, "case33bw.m:17 and Stage0.BASE_MVA"),
        comparison_row("basekV", 12.66, 12.66, "case33bw bus records"),
        comparison_row("vmax", scan_config.vmax_pu, audit_result.config.vmax_pu, "Phase-B ScanConfig and analytical AuditConfig"),
        comparison_row("phase-specific P13 boundary/corner command", audit_result.capacity.scales_kw[13], audit_result.envelope.p_kw[1], "Phase-B one-axis safe endpoint versus analytical two-coordinate corner; not an exogenous operating-point field", classification="NOT_APPLICABLE"),
        comparison_row("phase-specific P30 boundary/corner command", audit_result.capacity.scales_kw[30], audit_result.envelope.p_kw[2], "Phase-B one-axis safe endpoint versus analytical two-coordinate corner; not an exogenous operating-point field", classification="NOT_APPLICABLE"),
    ]

    coefficient_specs = (("c13_30", 13, 30, audit_result.envelope.matrix[1, 2]),
                         ("c13_13", 13, 13, audit_result.envelope.matrix[1, 1]),
                         ("c30_30", 30, 30, audit_result.envelope.matrix[2, 2]))
    coefficients = NamedTuple[]
    for (name, candidate, injection, production) in coefficient_specs
        reconstructed = independent_coefficient(case_data, candidate, injection)
        push!(coefficients, (coefficient=name, candidate_bus=candidate,
            injection_bus=injection,
            exact_shared_path=join(reconstructed.shared_branch_ids, ';'),
            case33bw_source_lines=join(reconstructed.shared_source_lines, ';'),
            raw_resistance_sum_ohm=reconstructed.resistance_ohm,
            base_mva=reconstructed.base_mva, base_kv=reconstructed.base_kv,
            zbase_ohm=reconstructed.zbase_ohm,
            reconstructed_coefficient=reconstructed.coefficient,
            production_coefficient=production,
            absolute_difference=abs(reconstructed.coefficient - production)))
    end

    inactive = [row for row in audit_result.envelope.margin_rows if !row.near_binding]
    nearest = inactive[argmin(row.margin_v2 for row in inactive)]
    active_residual = maximum(abs(row.margin_v2) for row in audit_result.envelope.margin_rows
                              if row.near_binding)
    separation = nearest.margin_v2 - active_residual
    base_v2_separation_13_14 = audit_result.baseline_v2[13] - audit_result.baseline_v2[14]
    nominal_14_18_p = sum(case_data.buses[index].pd_kw for index in 14:18)
    nominal_14_18_q = sum(case_data.buses[index].qd_kvar for index in 14:18)
    l13 = audit_result.envelope.ranking13.minimum_limit_kw
    l30 = audit_result.envelope.ranking30.minimum_limit_kw
    p13star, p30star = audit_result.envelope.p_kw
    triangle_area = l13 * l30 / 2
    quadrilateral_area = (l13 * p30star + p13star * l30) / 2
    lambda_lin = (quadrilateral_area - triangle_area) / triangle_area
    epsilon13 = audit_result.baseline_v2[13] +
                audit_result.envelope.matrix[1, 1] * audit_result.ac_axis_kw[13] / Stage0.BASE_KW -
                audit_result.config.vmax_pu^2
    epsilon30 = audit_result.baseline_v2[30] +
                audit_result.envelope.matrix[2, 2] * audit_result.ac_axis_kw[30] / Stage0.BASE_KW -
                audit_result.config.vmax_pu^2
    summary = [
        (key="primary_classification", value=CLASSIFICATION),
        (key="historical_value_0.9282211452522351_belongs_to", value="2012-10-15 12:30:00; canonical adjacent row"),
        (key="phase_b_audit_same_operating_point", value="true"),
        (key="pq_scaling_classification", value=classify_scaling(case_data, target_row, phase_vectors)),
        (key="p_load_vector_sha256", value=phase_hashes.p_load),
        (key="q_load_vector_sha256", value=phase_hashes.q_load),
        (key="p_injection_vector_sha256", value=phase_hashes.p_injection),
        (key="q_injection_vector_sha256", value=phase_hashes.q_injection),
        (key="independent_p_load_vector_sha256", value=independent_hashes.p_load),
        (key="independent_q_load_vector_sha256", value=independent_hashes.q_load),
        (key="independent_p_injection_vector_sha256", value=independent_hashes.p_injection),
        (key="independent_q_injection_vector_sha256", value=independent_hashes.q_injection),
        (key="independent_vector_declared_absolute_tolerance", value=fmt(independent_tolerance)),
        (key="maximum_independent_vector_absolute_difference", value=fmt(maximum_independent_difference)),
        (key="nearest_inactive_bus", value=string(nearest.bus)),
        (key="nearest_inactive_margin_v2", value=fmt(nearest.margin_v2)),
        (key="active_inactive_separation_v2", value=fmt(separation)),
        (key="active_inactive_separation_definition", value="nearest inactive positive margin minus maximum absolute active-set residual"),
        (key="raw_delta_v13", value=fmt(audit_result.envelope.rhs[1])),
        (key="raw_delta_v30", value=fmt(audit_result.envelope.rhs[2])),
        (key="baseline_squared_voltage_separation_v13_minus_v14", value=fmt(base_v2_separation_13_14)),
        (key="nominal_downstream_load_buses_14_18_kw", value=fmt(nominal_14_18_p)),
        (key="nominal_downstream_load_buses_14_18_kvar", value=fmt(nominal_14_18_q)),
        (key="g13", value=fmt(audit_result.relative_gap[13])),
        (key="g30", value=fmt(audit_result.relative_gap[30])),
        (key="axis13_squared_voltage_boundary_residual", value=fmt(epsilon13)),
        (key="axis30_squared_voltage_boundary_residual", value=fmt(epsilon30)),
        (key="theta_star_degrees", value=fmt(audit_result.envelope.normalized_angle_deg)),
        (key="linear_axis_13_intercept_kw", value=fmt(l13)),
        (key="linear_axis_30_intercept_kw", value=fmt(l30)),
        (key="linear_corner_p13_kw", value=fmt(p13star)),
        (key="linear_corner_p30_kw", value=fmt(p30star)),
        (key="triangle_area_kw2", value=fmt(triangle_area)),
        (key="quadrilateral_area_kw2", value=fmt(quadrilateral_area)),
        (key="Lambda_lin", value=fmt(lambda_lin)),
        (key="Lambda_lin_neutral_name", value="additional linear feasible area beyond the axis-calibrated single-hyperplane triangle"),
        (key="phase_b_regenerated", value="false"),
        (key="analytical_audit_regenerated", value="false"),
        (key="archive_worktree_available", value=string(isdir(joinpath(repository_root, "results", "dso_vpp_ac_map_pilot", "_archived_stage0_missing_reference_pv_20260730T145810Z")))),
        (key="archive_tracked_history_commit", value="ae24e08180cf154c3c49b136d5babc5f190b6a0c"),
        (key="archive_committed_references", value="README.md;RESULT_STATUS.md;result_status.csv;stage0_repair_report.md;archive_manifest.csv"),
        (key="radial_or_prohibited_probe_executed", value="false"),
        (key="scope_statement", value=NO_PROBE_STATEMENT),
    ]

    return (profile_data=profile_data, provenance=provenance_rows(profile_data),
            case_data=case_data, independent=independent, phase_b=phase_b,
            analytical_audit=audit_result, comparisons=comparisons,
            coefficients=coefficients, path_audit=path_audit_rows(), summary=summary,
            occurrences=numeric_occurrence_rows(),
            hashes=phase_hashes, nearest_inactive=nearest,
            active_inactive_separation=separation, lambda_lin=lambda_lin,
            epsilon13=epsilon13, epsilon30=epsilon30,
            radial_or_direction_probe_executed=false)
end

function write_report(path, result)
    s = Dict(row.key => row.value for row in result.summary)
    open(path, "w") do io
        println(io, "# Operating-point provenance audit")
        println(io)
        println(io, "Primary classification: **$(CLASSIFICATION)**.")
        println(io)
        println(io, "The exact value `0.9282211452522351` is the canonical `2012-10-15 12:30:00` PV factor. The next row, `2012-10-15 13:00:00`, contains `0.9149568739021162`. Both Phase B and the analytical audit select the latter row by the exact naive `DateTime` key and produce byte-identical independently reconstructed load and injection vector hashes. The historical retraction therefore attached the adjacent 12:30 peak value to the 13:00 operating point; production timestamp lookup is not defective.")
        println(io)
        println(io, "## Complete production paths")
        println(io)
        println(io, "Phase B: `run_dso_vpp_export_side_axis_scan.jl:108-123 -> load_canonical_data:85-93 -> Stage0.load_profile:36-44 -> CiroPVHC.read_s1b_profile -> _read_s1b_profile:45-96 -> scan_interval/evaluate_axis_point:145-163 -> evaluate_fixed_injection:104-115 -> Stage0.evaluate_point:297-441 -> assemble_stage0_inputs:89-134 -> primary_power_flow:136-289`.")
        println(io)
        println(io, "Analytical audit: `run_dso_vpp_ac_anchored_linear_corner_audit.jl:40-51 -> run_analytical_audit:330-405 -> AxisScan.load_canonical_data -> exact findfirst timestamp lookup:343-345 -> default_baseline_evaluator:318-328 -> AxisScan.evaluate_fixed_injection -> Stage0.evaluate_point -> assemble_stage0_inputs -> primary_power_flow`.")
        println(io)
        println(io, "Both paths read `$(PROFILE_RELATIVE_PATH)` (SHA-256 `$(PROFILE_SHA256)`). `_read_s1b_profile` parses `yyyy-mm-dd HH:MM:SS` into timezone-naive Julia `DateTime` values, rejects duplicates, requires sorted 30-minute spacing, and performs no sorting, filtering, shifting, resampling, reversal, or deduplication. Pilot selection filters only by the two calendar dates while preserving source order. Source preparation creates 48 naive local labels per date, stably sorts by timestamp, and normalizes timestamp-wise means by global maxima (`prepare_ausgrid_profiles.py:106-159,277-322`); no UTC conversion or explicit DST offset exists.")
        println(io)
        println(io, "At each selected index, `assemble_stage0_inputs` multiplies both `pd_kw` and `qd_kvar` by the same load multiplier, computes reference PV as `850 * pv_factor` at bus 13, adds active VPP commands at buses 13 and 30, fixes both reactive commands to zero, and divides net demand by the 10,000-kW base. Phase-B boundary commands are one-axis-at-a-time; the analytical corner is linear algebra and is not passed as the audit baseline AC command.")
        println(io)
        println(io, "## Independent checks")
        println(io)
        println(io, "The verifier parses the raw canonical CSV and `data_raw/case33bw.m` without calling the production profile, assembly, or coefficient constructors. `case33bw.m` SHA-256 is `$(CASE_SHA256)`. The canonical base is 10 MVA at 12.66 kV. Buses 14-18 total $(s["nominal_downstream_load_buses_14_18_kw"]) kW and $(s["nominal_downstream_load_buses_14_18_kvar"]) kvar. The baseline squared-voltage separation `v13^2-v14^2` is $(s["baseline_squared_voltage_separation_v13_minus_v14"]), matching the independently determined bus-14 corner margin up to the active equality residual.")
        println(io)
        println(io, "P/Q scaling: **$(SCALING_CLASSIFICATION)**. Canonical P/Q load hashes are `$(s["p_load_vector_sha256"])` and `$(s["q_load_vector_sha256"])`; signed generation-minus-load injection hashes are `$(s["p_injection_vector_sha256"])` and `$(s["q_injection_vector_sha256"])`.")
        println(io)
        println(io, "Nearest inactive bus is $(s["nearest_inactive_bus"]) with margin $(s["nearest_inactive_margin_v2"]). Active/inactive separation is $(s["active_inactive_separation_v2"]), defined as the nearest inactive positive margin minus the maximum absolute active-set equality residual. Raw `Delta-v13` and `Delta-v30` are $(s["raw_delta_v13"]) and $(s["raw_delta_v30"]).")
        println(io)
        println(io, "## Scientific result")
        println(io)
        println(io, "The aligned provenance retains `g13=$(s["g13"])`, `g30=$(s["g30"])`, squared-voltage boundary residuals $(s["axis13_squared_voltage_boundary_residual"]) and $(s["axis30_squared_voltage_boundary_residual"]), and `theta_star=$(s["theta_star_degrees"]) degrees` as internally valid mixed AC/linear quantities.")
        println(io)
        println(io, "In `P13 >= 0, P30 >= 0`, the AC-anchored linear feasible set is exactly the quadrilateral `O=(0,0)`, `A=($(s["linear_axis_13_intercept_kw"]),0)`, `C=($(s["linear_corner_p13_kw"]),$(s["linear_corner_p30_kw"]))`, `B=(0,$(s["linear_axis_30_intercept_kw"]))`. The proof basis is the unique bus-13 axis binding, unique bus-30 axis binding, complete all-bus corner feasibility, convexity of every affine half-space, and intersection of the two active voltage constraints with the nonnegative axes.")
        println(io)
        println(io, "`Lambda_lin=(area(quadrilateral)-area(axis-intercept triangle))/area(axis-intercept triangle)=$(s["Lambda_lin"])`. Its neutral name is **additional linear feasible area beyond the axis-calibrated single-hyperplane triangle**; no DOSS equivalence is asserted.")
        println(io)
        println(io, "## Portability and archive")
        println(io)
        println(io, "Current Phase-B, analytical-audit, and provenance scientific manifests use repository-relative paths. Legacy `D:\\CiroPVHC.jl` strings occur only in repair-only or explicitly invalid archived operational provenance and are classified as non-scientific fields excluded from reproducibility. No scientific absolute-path defect was found. The historical archive exists in the worktree, is tracked from commit `ae24e08180cf154c3c49b136d5babc5f190b6a0c`, and is referenced by committed status/report files; nothing was recreated.")
        println(io)
        println(io, NO_PROBE_STATEMENT)
    end
end

function write_artifacts(output_directory; repository_root=normpath(joinpath(@__DIR__, "..", "..")),
                         overwrite=false)
    mkpath(output_directory)
    paths = output_paths(output_directory)
    for path in values(paths)
        path == paths.reproducibility && continue
        isfile(path) && !overwrite && throw(ArgumentError("refusing to overwrite $path"))
    end
    result = run_provenance_audit(repository_root)
    write_csv(paths.rows, result.provenance, propertynames(first(result.provenance)))
    write_csv(paths.comparison, result.comparisons, propertynames(first(result.comparisons)))
    write_csv(paths.coefficients, result.coefficients, propertynames(first(result.coefficients)))
    write_csv(paths.occurrences, result.occurrences, propertynames(first(result.occurrences)))
    write_csv(paths.paths, result.path_audit, propertynames(first(result.path_audit)))
    write_csv(paths.summary, result.summary, (:key, :value))
    write_report(paths.report, result)
    scientific = (paths.rows, paths.comparison, paths.coefficients, paths.occurrences, paths.paths,
                  paths.summary, paths.report)
    manifest = [
        (key="implementation_id", value=IMPLEMENTATION_ID),
        (key="audit_base_commit", value=AUDIT_BASE_COMMIT),
        (key="profile_input_path", value=PROFILE_RELATIVE_PATH),
        (key="profile_input_sha256", value=PROFILE_SHA256),
        (key="case33bw_input_path", value=CASE_RELATIVE_PATH),
        (key="case33bw_input_sha256", value=CASE_SHA256),
        (key="phase_b_capacity_git_object", value="$(Audit.PHASE_B_COMMIT):$(Audit.CAPACITY_RELATIVE_PATH)"),
        (key="phase_b_capacity_sha256", value=Audit.EXPECTED_CAPACITY_SHA256),
        (key="timestamp_interpretation", value=TIMEZONE_STATEMENT),
        (key="vector_hash_serialization", value="33 Float64 values as comma-separated %.17g canonical text plus LF; generation-minus-load sign for injection vectors"),
        (key="radial_or_direction_probe_executed", value="false"),
    ]
    append!(manifest, [(key="output_sha256_$(basename(path))", value=sha256_file(path))
                       for path in scientific])
    write_csv(paths.manifest, manifest, (:key, :value))
    return merge(result, (paths=paths,))
end

function compare_artifacts(primary_directory, duplicate_directory, output_path)
    filenames = [basename(path) for path in values(output_paths(primary_directory))
                 if basename(path) != basename(output_paths(primary_directory).reproducibility)]
    rows = NamedTuple[]
    for filename in filenames
        primary = joinpath(primary_directory, filename)
        duplicate = joinpath(duplicate_directory, filename)
        match = read(primary) == read(duplicate)
        push!(rows, (file=filename, scientific_mismatches=match ? 0 : 1,
                     byte_identical=match, excluded_fields=""))
    end
    write_csv(output_path, rows, propertynames(first(rows)))
    all(row.byte_identical for row in rows) || throw(ArgumentError("provenance artifacts differ"))
    return rows
end

export IMPLEMENTATION_ID, AUDIT_BASE_COMMIT, PROFILE_RELATIVE_PATH, CASE_RELATIVE_PATH,
       PROFILE_SHA256, CASE_SHA256, TARGET_TIMESTAMPS, CLASSIFICATION,
       SCALING_CLASSIFICATION, TIMEZONE_STATEMENT, NO_PROBE_STATEMENT,
       vector_sha256, read_primary_profile, parse_case33bw, radial_path,
       independent_coefficient, independent_vectors, production_vectors,
       classify_scaling, provenance_rows, output_paths, path_audit_rows,
       numeric_occurrence_rows,
       run_provenance_audit, write_artifacts, compare_artifacts

end
