using SHA
using Statistics

function read_simple_csv(path::String)
    lines = readlines(path)
    isempty(lines) && error("$path is empty")
    headers = split(first(lines), ','; keepempty=true)
    length(unique(headers)) == length(headers) || error("$path has duplicate columns")
    rows = Vector{Dict{String,String}}()
    for (offset, line) in enumerate(lines[2:end])
        line_number = offset + 1
        isempty(line) && continue
        fields = split(line, ','; keepempty=true)
        length(fields) == length(headers) ||
            error("$path line $line_number has $(length(fields)) fields; expected $(length(headers))")
        push!(rows, Dict(headers .=> fields))
    end
    return (; headers, rows)
end

function require_columns(table, required::Vector{String}, label::String)
    missing_columns = [name for name in required if !(name in table.headers)]
    isempty(missing_columns) ||
        error("$label is missing columns: $(join(missing_columns, ", "))")
    isempty(table.rows) && error("$label has no data rows")
end

function parse_float(row, column::String)
    parse(Float64, row[column])
end

function parse_int(row, column::String)
    parse(Int, row[column])
end

function parse_bool(row, column::String)
    value = lowercase(row[column])
    value == "true" && return true
    value == "false" && return false
    error("Invalid Boolean value '$value' in column $column")
end

function metric_map(rows)
    Dict(row["metric"] => row["value"] for row in rows)
end

function assert_approx(actual::Real, expected::Real, tolerance::Real, label::String)
    isapprox(actual, expected; atol=tolerance, rtol=0.0) ||
        error("$label mismatch: actual=$actual expected=$expected tolerance=$tolerance")
end

function sha256_file(path::String)
    open(path, "r") do io
        return bytes2hex(SHA.sha256(io))
    end
end

function lf_normalized_bytes(path::String)
    codeunits(replace(read(path, String), "\r\n" => "\n"))
end

function sha256_lf_normalized(path::String)
    bytes2hex(SHA.sha256(lf_normalized_bytes(path)))
end

function parse_external_base(args::Vector{String})
    prefix = "--external-base="
    matches = [arg[length(prefix) + 1:end] for arg in args if startswith(arg, prefix)]
    length(matches) <= 1 || error("Specify --external-base at most once")
    isempty(matches) ? nothing : only(matches)
end

function validate_manifest(manifest_path::String, repository_root::String, external_base)
    table = read_simple_csv(manifest_path)
    require_columns(
        table,
        [
            "logical_artifact",
            "original_filename",
            "byte_size",
            "sha256",
            "artifact_role",
            "storage",
            "evidence_set",
        ],
        "evidence_manifest.csv",
    )
    allowed_storage = Set(["git", "external"])
    all(row["storage"] in allowed_storage for row in table.rows) ||
        error("evidence_manifest.csv contains an invalid storage value")
    all(parse_int(row, "byte_size") > 0 for row in table.rows) ||
        error("evidence_manifest.csv contains a non-positive byte size")
    all(occursin(r"^[0-9a-f]{64}$", row["sha256"]) for row in table.rows) ||
        error("evidence_manifest.csv contains an invalid SHA-256 value")
    logical_names = [row["logical_artifact"] for row in table.rows]
    length(unique(logical_names)) == length(logical_names) ||
        error("evidence_manifest.csv logical_artifact values must be unique")

    checked_git = 0
    checked_external = 0
    for row in table.rows
        storage = row["storage"]
        path = if storage == "git"
            joinpath(repository_root, split(row["logical_artifact"], '/')...)
        elseif external_base === nothing
            nothing
        else
            joinpath(external_base, split(row["original_filename"], '/')...)
        end
        path === nothing && continue
        isfile(path) || error("Manifest artifact is missing: $path")
        actual_size = storage == "git" ? length(lf_normalized_bytes(path)) : filesize(path)
        actual_hash = storage == "git" ? sha256_lf_normalized(path) : sha256_file(path)
        actual_size == parse_int(row, "byte_size") ||
            error("Manifest size mismatch for $path")
        actual_hash == row["sha256"] ||
            error("Manifest SHA-256 mismatch for $path")
        if storage == "git"
            checked_git += 1
        else
            checked_external += 1
        end
    end
    return (; rows=length(table.rows), checked_git, checked_external)
end

function main()
    repository_root = normpath(joinpath(@__DIR__, ".."))
    results_root = joinpath(repository_root, "results", "s1c_curtailment_benchmark")

    sitings = read_simple_csv(joinpath(results_root, "screened_configurations.csv"))
    h0 = read_simple_csv(joinpath(results_root, "zero_curtailment_hc.csv"))
    probes = read_simple_csv(joinpath(results_root, "annual_curtailment_probes.csv"))
    bracket = read_simple_csv(joinpath(results_root, "common_bracket.csv"))
    interpolation = read_simple_csv(joinpath(results_root, "hc1_interpolated.csv"))
    sweep = read_simple_csv(joinpath(results_root, "bus13_sweep_per_year.csv"))
    materiality = read_simple_csv(joinpath(results_root, "materiality_summary.csv"))

    require_columns(
        sitings,
        [
            "siting_tag",
            "share_bus13",
            "share_bus20",
            "share_bus24",
            "share_bus30",
            "configuration_type",
            "equal_share",
        ],
        "screened_configurations.csv",
    )
    require_columns(
        h0,
        ["siting_tag", "H0_kw", "binding_mechanism", "critical_interval"],
        "zero_curtailment_hc.csv",
    )
    require_columns(
        probes,
        [
            "siting_tag",
            "H_kw",
            "A_count",
            "B_count",
            "C_count",
            "solved_count",
            "fail_count",
            "replay_fail_count",
            "consistency_count",
            "r2010_pct",
            "r2011_pct",
            "r2012_pct",
            "annual_curtailment_pct",
            "limiting_year",
        ],
        "annual_curtailment_probes.csv",
    )
    require_columns(
        bracket,
        [
            "siting_tag",
            "H0_kw",
            "r810_pct",
            "r850_pct",
            "r810_lt_1",
            "r850_gt_1",
            "r810_lt_r850",
            "invalid810_count",
            "invalid850_count",
            "bracketed",
        ],
        "common_bracket.csv",
    )
    require_columns(
        interpolation,
        ["rank", "siting_tag", "HC1_interp_810_850_kw"],
        "hc1_interpolated.csv",
    )
    require_columns(
        sweep,
        [
            "H_kw",
            "data_year",
            "E_available_kWh",
            "E_curtailed_kWh",
            "annual_curtailment_pct",
        ],
        "bus13_sweep_per_year.csv",
    )
    require_columns(
        materiality,
        ["metric", "value", "units", "status"],
        "materiality_summary.csv",
    )

    expected_tags = [
        "13",
        "20",
        "24",
        "30",
        "13+20",
        "13+24",
        "13+30",
        "20+24",
        "20+30",
        "24+30",
        "13+20+24+30",
    ]
    expected_tag_set = Set(expected_tags)
    length(sitings.rows) == 11 || error("Expected 11 screened configurations")
    Set(row["siting_tag"] for row in sitings.rows) == expected_tag_set ||
        error("Screened-configuration tags do not match the canonical set")
    all(parse_bool(row, "equal_share") for row in sitings.rows) ||
        error("All curated configurations must use equal sharing over selected buses")
    for row in sitings.rows
        total_share =
            parse_float(row, "share_bus13") +
            parse_float(row, "share_bus20") +
            parse_float(row, "share_bus24") +
            parse_float(row, "share_bus30")
        assert_approx(total_share, 1.0, 1.0e-12, "Siting share total for $(row["siting_tag"])")
    end

    length(h0.rows) == 11 || error("Expected 11 zero-curtailment HC rows")
    Set(row["siting_tag"] for row in h0.rows) == expected_tag_set ||
        error("H0 tags do not match the canonical set")
    all(row["binding_mechanism"] == "no-export" for row in h0.rows) ||
        error("Every H0 row must identify no-export as the binding mechanism")
    all(parse_int(row, "critical_interval") == 40203 for row in h0.rows) ||
        error("Unexpected H0 critical interval")

    length(probes.rows) == 44 || error("Expected 44 annual-curtailment probe rows")
    capacities = [810.0, 850.0, 975.0, 1075.0]
    for tag in expected_tags
        rows = sort(
            [row for row in probes.rows if row["siting_tag"] == tag];
            by=row -> parse_float(row, "H_kw"),
        )
        length(rows) == 4 || error("Expected four probe rows for $tag")
        [parse_float(row, "H_kw") for row in rows] == capacities ||
            error("Probe capacities mismatch for $tag")
        all(parse_int(row, "limiting_year") == 2012 for row in rows) ||
            error("Unexpected limiting year for $tag")
        all(
            parse_float(row, "annual_curtailment_pct") ==
            max(
                parse_float(row, "r2010_pct"),
                parse_float(row, "r2011_pct"),
                parse_float(row, "r2012_pct"),
            ) for row in rows
        ) || error("Annual-curtailment maximum mismatch for $tag")
        issorted([parse_float(row, "annual_curtailment_pct") for row in rows]) ||
            error("Sampled annual curtailment is not monotone for $tag")
    end

    count810 = [row for row in probes.rows if parse_float(row, "H_kw") == 810.0]
    length(count810) == 11 || error("Expected 11 H=810 rows")
    counted_probe_rows = [row for row in probes.rows if !isempty(row["A_count"])]
    length(counted_probe_rows) == 42 ||
        error("Expected interval counts for 42 of the 44 probe rows")
    for row in counted_probe_rows
        parse_int(row, "A_count") +
        parse_int(row, "B_count") +
        parse_int(row, "C_count") == 52608 ||
            error("Probe interval count mismatch for $(row["siting_tag"]) at H=$(row["H_kw"])")
        parse_int(row, "solved_count") == parse_int(row, "B_count") ||
            error("Probe solved/B mismatch for $(row["siting_tag"]) at H=$(row["H_kw"])")
        parse_int(row, "C_count") == 0 &&
            parse_int(row, "fail_count") == 0 &&
            parse_int(row, "replay_fail_count") == 0 &&
            parse_int(row, "consistency_count") == 0 ||
            error("Probe validation failure for $(row["siting_tag"]) at H=$(row["H_kw"])")
    end

    length(bracket.rows) == 11 || error("Expected 11 common-bracket rows")
    Set(row["siting_tag"] for row in bracket.rows) == expected_tag_set ||
        error("Common-bracket tags do not match the canonical set")
    all(
        parse_bool(row, "r810_lt_1") &&
        parse_bool(row, "r850_gt_1") &&
        parse_bool(row, "r810_lt_r850") &&
        parse_int(row, "invalid810_count") == 0 &&
        parse_int(row, "invalid850_count") == 0 &&
        parse_bool(row, "bracketed") for row in bracket.rows
    ) || error("Not all screened configurations pass the common bracket")

    probe_lookup = Dict(
        (row["siting_tag"], parse_float(row, "H_kw")) =>
            parse_float(row, "annual_curtailment_pct") for row in probes.rows
    )
    h0_lookup = Dict(row["siting_tag"] => parse_float(row, "H0_kw") for row in h0.rows)
    for row in bracket.rows
        tag = row["siting_tag"]
        assert_approx(parse_float(row, "H0_kw"), h0_lookup[tag], 1.0e-9, "H0 for $tag")
        assert_approx(
            parse_float(row, "r810_pct"),
            probe_lookup[(tag, 810.0)],
            1.0e-12,
            "r810 for $tag",
        )
        assert_approx(
            parse_float(row, "r850_pct"),
            probe_lookup[(tag, 850.0)],
            1.0e-12,
            "r850 for $tag",
        )
    end
    length(interpolation.rows) == 11 || error("Expected 11 interpolation rows")
    Set(row["siting_tag"] for row in interpolation.rows) == expected_tag_set ||
        error("Interpolation tags do not match the canonical set")
    calculated_hc = Float64[]
    for row in interpolation.rows
        tag = row["siting_tag"]
        r810 = probe_lookup[(tag, 810.0)]
        r850 = probe_lookup[(tag, 850.0)]
        hc = 810.0 + (1.0 - r810) * 40.0 / (r850 - r810)
        assert_approx(
            parse_float(row, "HC1_interp_810_850_kw"),
            hc,
            5.0e-7,
            "Descriptive interpolation for $tag",
        )
        push!(calculated_hc, hc)
    end
    issorted([parse_float(row, "HC1_interp_810_850_kw") for row in interpolation.rows]) ||
        error("Interpolation rows must be ranked from lowest to highest")
    [parse_int(row, "rank") for row in interpolation.rows] == collect(1:11) ||
        error("Interpolation ranks must be 1:11")

    length(sweep.rows) == 60 || error("Expected 60 rows in the 20-point three-year sweep")
    length(unique(parse_float(row, "H_kw") for row in sweep.rows)) == 20 ||
        error("Expected 20 unique bus-13 sweep capacities")
    Set(parse_int(row, "data_year") for row in sweep.rows) == Set([2010, 2011, 2012]) ||
        error("Unexpected bus-13 sweep years")
    all(
        isapprox(
            parse_float(row, "annual_curtailment_pct"),
            100.0 * parse_float(row, "E_curtailed_kWh") /
            parse_float(row, "E_available_kWh");
            atol=5.0e-9,
            rtol=0.0,
        ) for row in sweep.rows
    ) || error("Bus-13 sweep energy ratios are inconsistent")

    metrics = metric_map(materiality.rows)
    calculated_min = minimum(calculated_hc)
    calculated_max = maximum(calculated_hc)
    calculated_mean = mean(calculated_hc)
    calculated_spread = 100.0 * (calculated_max - calculated_min) / calculated_mean
    calculated_bound = 100.0 * (850.0 - 810.0) / 810.0
    assert_approx(parse(Float64, metrics["interpolated_min"]), calculated_min, 5.0e-7, "Minimum HC")
    assert_approx(parse(Float64, metrics["interpolated_max"]), calculated_max, 5.0e-7, "Maximum HC")
    assert_approx(parse(Float64, metrics["interpolated_mean"]), calculated_mean, 5.0e-7, "Mean HC")
    assert_approx(
        parse(Float64, metrics["interpolated_relative_spread"]),
        calculated_spread,
        5.0e-9,
        "Relative spread",
    )
    assert_approx(
        parse(Float64, metrics["monotonicity_based_bracket_bound"]),
        calculated_bound,
        5.0e-9,
        "Monotonicity-based bracket bound",
    )
    metrics["interpolated_min_siting"] == "13+20+24+30" ||
        error("Unexpected minimum-HC siting")
    metrics["interpolated_max_siting"] == "13" ||
        error("Unexpected maximum-HC siting")
    parse(Int, metrics["screened_configuration_count"]) == 11 ||
        error("Materiality summary configuration count mismatch")
    parse(Int, metrics["interval_count"]) == 52608 ||
        error("Materiality summary interval count mismatch")
    hc_by_tag = Dict(
        row["siting_tag"] => parse_float(row, "HC1_interp_810_850_kw") for
        row in interpolation.rows
    )
    single_bus_hc = [hc_by_tag[tag] for tag in ["13", "20", "24", "30"]]
    multi_bus_hc = [hc_by_tag[tag] for tag in setdiff(expected_tags, ["13", "20", "24", "30"])]
    minimum(single_bus_hc) > maximum(multi_bus_hc) ||
        error("Single-bus versus equal-share multi-bus ordering mismatch")

    manifest_result = validate_manifest(
        joinpath(results_root, "evidence_manifest.csv"),
        repository_root,
        parse_external_base(ARGS),
    )

    println("S1-C_CURATED_VALIDATION_PASS=true")
    println("screened_configurations=11")
    println("bus13_sweep_rows=60")
    println("annual_probe_rows=44")
    println("all11_common_bracket=true")
    println("interpolated_min_kw=$(round(calculated_min; digits=9))")
    println("interpolated_max_kw=$(round(calculated_max; digits=9))")
    println("interpolated_mean_kw=$(round(calculated_mean; digits=9))")
    println("interpolated_relative_spread_pct=$(round(calculated_spread; digits=9))")
    println("monotonicity_based_bracket_bound_pct=$(round(calculated_bound; digits=9))")
    println("manifest_rows=$(manifest_result.rows)")
    println("manifest_git_hashes_checked=$(manifest_result.checked_git)")
    println("manifest_external_hashes_checked=$(manifest_result.checked_external)")
end

main()
