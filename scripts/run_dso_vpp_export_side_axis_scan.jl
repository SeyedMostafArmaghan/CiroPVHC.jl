#!/usr/bin/env julia

include(joinpath(@__DIR__, "..", "src", "benchmark",
                 "dso_vpp_export_side_axis_scan.jl"))
using .DSOVPPExportSideAxisScan

function usage()
    println("""
Usage: julia --project=. scripts/run_dso_vpp_export_side_axis_scan.jl [options]

Options:
  --output-dir=PATH
  --H-kW=FLOAT
  --reference-pv-bus=INT
  --Vmin=FLOAT
  --Vmax=FLOAT
  --initial-step-rule=total_canonical_nominal_active_load_kW/64
  --initial-step-kW=FLOAT
  --max-doubling-steps=INT
  --max-refinement-steps=INT
  --capacity-tolerance-kW=FLOAT
  --voltage-margin-tolerance-pu=FLOAT
  --near-binding-tolerance-pu=FLOAT
  --max-intervals=INT             (deterministic smoke runs only)
  --compare-primary-dir=PATH      (scan, then compare scientific outputs)
  --overwrite
  --help

The default command scans all 96 canonical timestamps and both one-at-a-time
export axes. Existing output files are never overwritten without --overwrite.
""")
end

function option_map(arguments)
    values = Dict{String,String}()
    flags = Set{String}()
    for argument in arguments
        if startswith(argument, "--") && occursin('=', argument)
            key, value = split(argument[3:end], '='; limit=2)
            values[key] = value
        elseif startswith(argument, "--")
            push!(flags, argument[3:end])
        else
            throw(ArgumentError("unexpected positional argument: $argument"))
        end
    end
    return values, flags
end

function typed(option_values, key, default, type)
    haskey(option_values, key) || return default
    return parse(type, option_values[key])
end

function main(arguments=ARGS)
    option_values, flags = option_map(arguments)
    if "help" in flags
        usage()
        return nothing
    end
    allowed_values = Set([
        "output-dir", "H-kW", "reference-pv-bus", "Vmin", "Vmax",
        "initial-step-rule", "initial-step-kW", "max-doubling-steps",
        "max-refinement-steps", "capacity-tolerance-kW",
        "voltage-margin-tolerance-pu", "near-binding-tolerance-pu",
        "max-intervals", "compare-primary-dir",
    ])
    unknown_values = setdiff(Set(keys(option_values)), allowed_values)
    isempty(unknown_values) || throw(ArgumentError(
        "unknown options: $(join(sort!(collect(unknown_values)), ", "))",
    ))
    setdiff(flags, Set(["overwrite"])) |> isempty ||
        throw(ArgumentError("unknown flags: $(join(sort!(collect(setdiff(flags, Set(["overwrite"])))), ", "))"))
    repository_root = normpath(joinpath(@__DIR__, ".."))
    output_directory = get(
        option_values, "output-dir",
        joinpath(repository_root, "results", "dso_vpp_ac_map_pilot"),
    )
    explicit_initial = haskey(option_values, "initial-step-kW") ?
        parse(Float64, option_values["initial-step-kW"]) : nothing
    maximum_intervals = haskey(option_values, "max-intervals") ?
        parse(Int, option_values["max-intervals"]) : nothing
    command = "julia --project=. scripts/run_dso_vpp_export_side_axis_scan.jl" *
              (isempty(arguments) ? "" : " " * join(arguments, " "))
    config = ScanConfig(
        repository_root=repository_root,
        output_directory=abspath(output_directory),
        reference_pv_capacity_kw=typed(option_values, "H-kW", 850.0, Float64),
        reference_pv_bus=typed(option_values, "reference-pv-bus", 13, Int),
        vmin_pu=typed(option_values, "Vmin", 0.90, Float64),
        vmax_pu=typed(option_values, "Vmax", 1.05, Float64),
        initial_step_rule=get(option_values, "initial-step-rule",
                              "total_canonical_nominal_active_load_kW/64"),
        initial_step_kw=explicit_initial,
        maximum_doubling_steps=typed(option_values, "max-doubling-steps", 12, Int),
        maximum_refinement_steps=typed(option_values, "max-refinement-steps", 60, Int),
        capacity_tolerance_kw=typed(option_values, "capacity-tolerance-kW", 1.0, Float64),
        voltage_margin_tolerance_pu=typed(
            option_values, "voltage-margin-tolerance-pu", 1e-5, Float64,
        ),
        binding_tolerance_pu=typed(
            option_values, "near-binding-tolerance-pu", 1e-5, Float64,
        ),
        overwrite="overwrite" in flags,
        maximum_intervals=maximum_intervals,
        exact_command=command,
    )
    data = load_canonical_data(config)
    step = config.initial_step_kw === nothing ?
        sum(bus.pd_kw for bus in data.network.buses) / 64 : config.initial_step_kw
    intervals = length(data.indices)
    expected_evaluations = intervals * 2 * (1 + 8 + 15)
    worst_evaluations = intervals * 2 *
                        (1 + config.maximum_doubling_steps + config.maximum_refinement_steps)
    println("Resolved configuration: H=$(config.reference_pv_capacity_kw) kW, reference PV bus=$(config.reference_pv_bus), V=$(config.vmin_pu)-$(config.vmax_pu) p.u., initial step=$step kW, intervals=$intervals, capacity tolerance=$(config.capacity_tolerance_kw) kW, voltage tolerance=$(config.voltage_margin_tolerance_pu) p.u., binding tolerance=$(config.binding_tolerance_pu) p.u.")
    println("Estimated evaluations: $expected_evaluations expected; $worst_evaluations guarded worst case.")
    println("Estimated runtime: <= 60 seconds; estimated RAM: <= 891289600 bytes.")
    println("Output directory: $(config.output_directory)")
    for path in values(output_paths(config.output_directory))
        println("Output path: $path")
    end
    println("MANDATORY SCOPE: computing one-axis-at-a-time bounds, not a two-dimensional feasible region, not a DOE, and not a Cartesian-product feasibility certificate.")
    result = run_scan(config)
    println("Completed $(length(result.capacity_rows)) capacity rows and $(length(result.point_rows)) evaluations in $(round(result.elapsed_seconds; digits=3)) seconds.")
    if haskey(option_values, "compare-primary-dir")
        primary_directory = abspath(option_values["compare-primary-dir"])
        check_path = joinpath(primary_directory,
                              "export_side_axis_reproducibility_check.csv")
        comparisons = write_reproducibility_check(
            primary_directory, config.output_directory, check_path,
        )
        append_manifest_output_hash(
            joinpath(primary_directory, "export_side_axis_evidence_manifest.csv"),
            check_path,
        )
        println("Scientific reproducibility comparison: $(sum(row.compared_rows for row in comparisons)) compared rows, $(sum(row.scientific_mismatches for row in comparisons)) mismatches, maximum discrepancy $(maximum(row.maximum_numerical_discrepancy for row in comparisons)).")
        println("Reproducibility check: $check_path")
    end
    return result
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    main()
end
