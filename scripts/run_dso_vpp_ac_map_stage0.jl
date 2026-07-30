function main()
    repository_root = normpath(joinpath(@__DIR__, ".."))
    Base.include(
        Main,
        joinpath(repository_root, "src", "benchmark", "dso_vpp_ac_map_stage0.jl"),
    )
    module_ref = Base.invokelatest(getfield, Main, :DSOVPPACMapStage0)
    runner = Base.invokelatest(getfield, module_ref, :run_stage0)
    result = Base.invokelatest(
        runner,
        repository_root,
    )
    timing = result.timing
    println("output_directory=$(result.output_directory)")
    println("benchmark_evaluations=$(timing.benchmark_evaluations)")
    println("benchmark_wall_seconds=$(timing.benchmark_wall_seconds)")
    println("converged_count=$(timing.converged_count)")
    println("within_limits_count=$(timing.within_limits_count)")
    println("upper_voltage_violation_count=$(timing.upper_voltage_violation_count)")
    println("lower_voltage_violation_count=$(timing.lower_voltage_violation_count)")
    println("unresolved_count=$(timing.unresolved_count)")
    println("peak_rss_bytes=$(timing.peak_rss_bytes)")
    println("total_allocated_bytes=$(timing.total_allocated_bytes)")
    println("total_gc_time_ms=$(timing.total_gc_time_ms)")
end

main()
