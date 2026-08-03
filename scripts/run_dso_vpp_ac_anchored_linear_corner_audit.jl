#!/usr/bin/env julia

include(joinpath(@__DIR__, "..", "src", "benchmark",
                 "dso_vpp_ac_anchored_linear_corner_audit.jl"))
using .DSOVPPACAnchoredLinearCornerAudit

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

function main(arguments=ARGS)
    values, flags = option_map(arguments)
    allowed_values = Set(["output-dir", "compare-primary-dir"])
    isempty(setdiff(Set(keys(values)), allowed_values)) ||
        throw(ArgumentError("unknown value option"))
    isempty(setdiff(flags, Set(["overwrite"]))) ||
        throw(ArgumentError("unknown flag"))
    repository_root = normpath(joinpath(@__DIR__, ".."))
    output_directory = abspath(get(
        values, "output-dir",
        joinpath(repository_root, "results", "dso_vpp_ac_map_pilot"),
    ))
    actual_command = "julia --project=. scripts/run_dso_vpp_ac_anchored_linear_corner_audit.jl" *
                     (isempty(arguments) ? "" : " " * join(arguments, " "))
    command = haskey(values, "compare-primary-dir") ?
        "julia --project=. scripts/run_dso_vpp_ac_anchored_linear_corner_audit.jl --overwrite" :
        actual_command
    config = AuditConfig(
        repository_root=repository_root,
        output_directory=output_directory,
        overwrite="overwrite" in flags,
        exact_command=command,
    )
    println("Repository root: $repository_root")
    println("Output directory: $output_directory")
    println("Executed command: $actual_command")
    println("Diagnostic variant: $DIAGNOSTIC_VARIANT")
    println("MANDATORY SCOPE: one zero-VPP AC baseline plus analytical all-bus linear algebra; no radial or direction probe.")
    result = write_audit_artifacts(config)
    envelope = result.envelope
    println("Axis argmins: 13=>$(envelope.ranking13.tie_buses), 30=>$(envelope.ranking30.tie_buses)")
    println("Corner classification: $(envelope.classification)")
    println("Intersection: P13=$(envelope.p_kw[1]) kW, P30=$(envelope.p_kw[2]) kW")
    println("Normalized angle: $(envelope.normalized_angle_rad) rad ($(envelope.normalized_angle_deg) deg)")
    if haskey(values, "compare-primary-dir")
        primary_directory = abspath(values["compare-primary-dir"])
        reproducibility_path = output_paths(primary_directory).reproducibility
        comparisons = write_reproducibility_check(
            primary_directory, output_directory, reproducibility_path,
        )
        primary_config = AuditConfig(
            repository_root=repository_root,
            output_directory=primary_directory,
            overwrite=true,
            exact_command="julia --project=. scripts/run_dso_vpp_ac_anchored_linear_corner_audit.jl --overwrite",
        )
        primary_result = run_analytical_audit(primary_config)
        refresh_manifest(merge(primary_result, (paths=output_paths(primary_directory),)))
        println("Scientific reproducibility: $(length(comparisons)) artifacts, zero mismatches.")
    end
    println(NO_PROBE_STATEMENT)
    return result
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    main()
end
