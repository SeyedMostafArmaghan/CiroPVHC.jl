#!/usr/bin/env julia

include(joinpath(@__DIR__, "..", "src", "benchmark",
                 "dso_vpp_operating_point_provenance.jl"))
using .DSOVPPOperatingPointProvenance

function main(arguments=ARGS)
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
    isempty(setdiff(Set(keys(values)), Set(["output-dir", "compare-primary-dir"]))) ||
        throw(ArgumentError("unknown value option"))
    isempty(setdiff(flags, Set(["overwrite"]))) || throw(ArgumentError("unknown flag"))
    repository_root = normpath(joinpath(@__DIR__, ".."))
    output_directory = abspath(get(values, "output-dir",
        joinpath(repository_root, "results", "dso_vpp_ac_map_pilot")))
    result = write_artifacts(output_directory; repository_root=repository_root,
                             overwrite="overwrite" in flags)
    println("Primary classification: $(CLASSIFICATION)")
    println("P/Q scaling: $(SCALING_CLASSIFICATION)")
    println("Nearest inactive bus: $(result.nearest_inactive.bus)")
    println("Lambda_lin: $(result.lambda_lin)")
    if haskey(values, "compare-primary-dir")
        primary = abspath(values["compare-primary-dir"])
        check_path = output_paths(primary).reproducibility
        comparisons = compare_artifacts(primary, output_directory, check_path)
        println("Reproducibility: $(length(comparisons)) byte-identical scientific artifacts")
    end
    println(NO_PROBE_STATEMENT)
    return result
end

if abspath(PROGRAM_FILE) == abspath(@__FILE__)
    main()
end
