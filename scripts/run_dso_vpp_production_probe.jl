function main()
    repository_root = normpath(joinpath(@__DIR__, ".."))
    source_path = joinpath(
        repository_root, "src", "benchmark", "dso_vpp_production_probe.jl",
    )
    Base.include(Main, source_path)
    module_ref = Base.invokelatest(getfield, Main, :DSOVPPProductionProbe)
    flag = Base.invokelatest(getfield, module_ref, :EXECUTION_FLAG)
    execution_authorized = flag in ARGS
    runner = Base.invokelatest(getfield, module_ref, :run_production_probe)
    result = Base.invokelatest(
        runner, repository_root; execution_authorized=execution_authorized,
    )
    println("output_directory=$(result.output_directory)")
    println("resume_mode=$(result.resume_mode)")
    println("wall_seconds=$(result.wall_seconds)")
    println("actual_ac_evaluations=$(result.total_actual_evaluations)")
    println("logical_evaluations=$(result.total_logical_evaluations)")
    println("retry_count=$(result.retries)")
    println("nonconverged_attempt_count=$(result.nonconverged_attempts)")
    println("unresolved_count=$(result.unresolved_count)")
    println("guard_limited_count=$(result.guard_count)")
    println("axis_reentry_count=$(result.axis_reentry_count)")
    println("ray_reentry_count=$(result.ray_reentry_count)")
    println("anchor_classification=$(result.anchor_classification)")
    println("classification=$(result.classification)")
end

main()
