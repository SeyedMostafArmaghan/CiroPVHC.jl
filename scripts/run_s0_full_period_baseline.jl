using CiroPVHC
using Printf

CiroPVHC._load_s0_solver!()

const S0_ROOT_VOLTAGES = (1.00, 1.03, 1.05)
const S0_MERGED_CSV_FILES = (
    "s0_summary.csv",
    "s0_interval_metrics.csv",
    "s0_branch_peak_metrics.csv",
    "s0_voltage_violations.csv",
    "s0_solver_failures.csv",
    "s0_critical_intervals.csv",
)

function repository_commit(repository_root::AbstractString)
    return try
        readchomp(`git -C $repository_root rev-parse HEAD`)
    catch
        "unknown"
    end
end

function run_single_root(
    repository_root::AbstractString,
    input_path::AbstractString,
    root_voltage_pu::Float64,
    output_directory::AbstractString,
)
    result = run_s0_full_period_baseline(
        input_path,
        output_directory;
        config=S0BaselineConfig(root_voltages_pu=[root_voltage_pu]),
        repository_commit=repository_commit(repository_root),
    )
    summary = only(result.summaries)
    @printf(
        "S0 child V0=%.2f completed: solved=%d failed=%d fallbacks=%d violations=%d runtime=%.3f s\n",
        root_voltage_pu,
        summary.solved_intervals,
        summary.solver_failed_intervals,
        summary.operational_model_fallback_intervals,
        summary.intervals_with_voltage_violations,
        result.total_runtime_seconds,
    )
    return result
end

function merge_csv_parts(destination::AbstractString, part_paths::Vector{String})
    open(destination, "w") do output
        for (part_index, part_path) in enumerate(part_paths)
            for (line_index, line) in enumerate(eachline(part_path))
                part_index > 1 && line_index == 1 && continue
                println(output, line)
            end
        end
    end
end

function parse_summary_value(column::AbstractString, value::AbstractString)
    integer_columns = Set((
        "interval_count",
        "solved_intervals",
        "solver_failed_intervals",
        "operational_model_fallback_intervals",
        "numerically_valid_intervals",
        "operationally_feasible_intervals",
        "intervals_with_voltage_violations",
        "undervoltage_bus_time_count",
        "overvoltage_bus_time_count",
        "global_minimum_voltage_bus",
        "global_maximum_voltage_bus",
        "peak_branch_id",
        "zero_pv_export_intervals",
    ))
    column in integer_columns && return parse(Int, value)
    column == "fully_validated" && return value == "true"
    numeric_value = tryparse(Float64, value)
    return numeric_value === nothing ? value : numeric_value
end

function read_part_summary(path::AbstractString)
    lines = readlines(path)
    length(lines) == 2 || error("Expected one S0 summary row in $path")
    columns = split(lines[1], ',')
    values = split(lines[2], ',')
    length(columns) == length(values) || error("Malformed S0 summary row in $path")
    parsed = Tuple(parse_summary_value(column, value) for (column, value) in zip(columns, values))
    return NamedTuple{Tuple(Symbol.(columns))}(parsed)
end

function metadata_number(path::AbstractString, key::AbstractString)
    pattern = Regex("\\\"" * key * "\\\": ([0-9.eE+-]+)")
    for line in eachline(path)
        matched = match(pattern, line)
        matched === nothing || return parse(Float64, matched.captures[1])
    end
    error("Metadata key $key is missing from $path")
end

function metadata_case_runtime(path::AbstractString)
    pattern = r"\"case_solver_runtime_seconds\": \[([0-9.eE+-]+)"
    for line in eachline(path)
        matched = match(pattern, line)
        matched === nothing || return parse(Float64, matched.captures[1])
    end
    error("Case runtime is missing from $path")
end

function all_ac_records_pass(path::AbstractString)
    lines = eachline(path)
    header = split(first(lines), ',')
    status_index = findfirst(==("ac_validation_status"), header)
    status_index === nothing && error("AC status column is missing from $path")
    record_count = 0
    for line in lines
        record_count += 1
        split(line, ',')[status_index] == "PASS" || return false
    end
    return record_count == 4
end

function combine_root_outputs(
    repository_root::AbstractString,
    input_path::AbstractString,
    output_directory::AbstractString,
    part_directories::Vector{String},
    total_runtime_seconds::Float64,
)
    mkpath(output_directory)
    for filename in S0_MERGED_CSV_FILES
        merge_csv_parts(
            joinpath(output_directory, filename),
            [joinpath(directory, filename) for directory in part_directories],
        )
    end

    summaries = [read_part_summary(joinpath(directory, "s0_summary.csv")) for directory in part_directories]
    case_solver_runtimes = [
        metadata_case_runtime(joinpath(directory, "s0_metadata.json"))
        for directory in part_directories
    ]
    all_ac_passed = all(
        all_ac_records_pass(joinpath(directory, "s0_critical_intervals.csv"))
        for directory in part_directories
    )
    profile = read_ausgrid_s0_load_profile(input_path)
    config = S0BaselineConfig()
    output_filenames = sort([S0_MERGED_CSV_FILES... , "s0_metadata.json", "s0_report.md"])
    Base.invokelatest(
        CiroPVHC._s0_write_metadata,
        joinpath(output_directory, "s0_metadata.json"),
        profile,
        config,
        summaries,
        case_solver_runtimes,
        total_runtime_seconds,
        repository_commit(repository_root),
        output_filenames,
    )
    Base.invokelatest(
        CiroPVHC._s0_write_report,
        joinpath(output_directory, "s0_report.md"),
        profile,
        summaries,
        case_solver_runtimes,
        total_runtime_seconds,
        all_ac_passed,
    )
    return (summaries=summaries, case_solver_runtimes=case_solver_runtimes, ac_validation_passed=all_ac_passed)
end

function finish_orchestrated_run(
    repository_root::AbstractString,
    input_path::AbstractString,
    part_root::AbstractString,
    part_directories::Vector{String},
    total_runtime_seconds::Float64,
)
    output_directory = joinpath(repository_root, "results", "s0_full_period_baseline")
    combined = combine_root_outputs(
        repository_root,
        input_path,
        output_directory,
        part_directories,
        total_runtime_seconds,
    )

    expected_part_root = abspath(joinpath(repository_root, "results", ".s0_full_period_baseline_parts"))
    abspath(part_root) == expected_part_root || error("Refusing to remove unexpected S0 part directory")
    rm(part_root; recursive=true, force=true)

    println("S0 full-period baseline validation completed")
    @printf("runtime_seconds=%.3f\n", total_runtime_seconds)
    println("ac_validation_passed=", combined.ac_validation_passed)
    for summary in combined.summaries
        @printf(
            "V0=%.2f solved=%d failed=%d diagnostic_fallbacks=%d violation_intervals=%d Vmin=%.9f peak_substation_kva=%.6f fully_validated=%s\n",
            summary.root_voltage_pu,
            summary.solved_intervals,
            summary.solver_failed_intervals,
            summary.operational_model_fallback_intervals,
            summary.intervals_with_voltage_violations,
            summary.global_minimum_voltage_pu,
            summary.peak_substation_apparent_power_kva,
            summary.fully_validated ? "true" : "false",
        )
    end
    println("outputs=", abspath(output_directory))
    return combined
end

function run_orchestrator(repository_root::AbstractString, input_path::AbstractString)
    part_root = joinpath(repository_root, "results", ".s0_full_period_baseline_parts")
    part_directories = [joinpath(part_root, @sprintf("v0_%0.2f", root)) for root in S0_ROOT_VOLTAGES]
    mkpath(part_root)
    script_path = abspath(@__FILE__)
    julia_command = Base.julia_cmd()
    started = time()
    for (root_voltage_pu, part_directory) in zip(S0_ROOT_VOLTAGES, part_directories)
        command = `$julia_command --threads=$(Threads.nthreads()) --project=$repository_root $script_path --single-root $root_voltage_pu $part_directory`
        try
            run(command)
        catch first_error
            println("S0 child V0=$(root_voltage_pu) failed once; retrying in a fresh process: ", first_error)
            run(command)
        end
    end
    total_runtime_seconds = time() - started
    finish_orchestrated_run(repository_root, input_path, part_root, part_directories, total_runtime_seconds)
end

function main()
    repository_root = normpath(joinpath(@__DIR__, ".."))
    input_path = joinpath(
        repository_root,
        "data_processed",
        "ausgrid",
        "ausgrid_halfhour_normalized.csv",
    )
    if length(ARGS) == 3 && ARGS[1] == "--single-root"
        run_single_root(repository_root, input_path, parse(Float64, ARGS[2]), abspath(ARGS[3]))
        return
    elseif ARGS == ["--combine-parts"]
        part_root = joinpath(repository_root, "results", ".s0_full_period_baseline_parts")
        part_directories = [joinpath(part_root, @sprintf("v0_%0.2f", root)) for root in S0_ROOT_VOLTAGES]
        total_runtime_seconds = sum(
            metadata_number(joinpath(directory, "s0_metadata.json"), "runtime_seconds")
            for directory in part_directories
        )
        finish_orchestrated_run(repository_root, input_path, part_root, part_directories, total_runtime_seconds)
        return
    end
    isempty(ARGS) || error("Usage: run_s0_full_period_baseline.jl [--single-root V0 OUTPUT_DIRECTORY | --combine-parts]")
    run_orchestrator(repository_root, input_path)
end

main()
