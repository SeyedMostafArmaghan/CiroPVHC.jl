using CiroPVHC
using Dates
using Printf

const SNAPSHOT_TIMESTAMP = DateTime(2011, 2, 5, 18, 0, 0)
const ROOT_VOLTAGES_PU = (1.00, 1.03, 1.05)

csv_value(value::AbstractFloat) = @sprintf("%.15g", value)
csv_value(value) = string(value)

function write_csv(path::AbstractString, rows)
    isempty(rows) && error("refusing to write an empty CSV: $path")
    columns = propertynames(first(rows))
    open(path, "w") do io
        println(io, join(string.(columns), ','))
        for row in rows
            println(io, join((csv_value(getproperty(row, column)) for column in columns), ','))
        end
    end
end

function snapshot_multiplier(path::AbstractString, timestamp::DateTime)
    lines = eachline(path)
    header = split(first(lines), ',')
    time_column = only(findall(==("datetime"), header))
    multiplier_column = only(findall(==("load_multiplier"), header))
    target = Dates.format(timestamp, dateformat"yyyy-mm-dd HH:MM:SS")
    for line in lines
        fields = split(line, ',')
        fields[time_column] == target || continue
        return parse(Float64, fields[multiplier_column])
    end
    error("snapshot timestamp not found: $target")
end

function prior_snapshot_rows(path::AbstractString, timestamp::DateTime)
    lines = eachline(path)
    header = split(first(lines), ',')
    target = Dates.format(timestamp, dateformat"yyyy-mm-dd HH:MM:SS")
    rows = Dict{Float64,NamedTuple}()
    for line in lines
        fields = split(line, ',')
        fields[2] == target || continue
        row = NamedTuple{Tuple(Symbol.(header))}(Tuple(fields))
        root = parse(Float64, row.root_voltage_pu)
        rows[root] = (
            minimum_voltage_pu=parse(Float64, row.minimum_voltage_pu),
            substation_active_power_kw=parse(Float64, row.substation_active_power_kw),
            substation_reactive_power_kvar=parse(Float64, row.substation_reactive_power_kvar),
            active_losses_kw=parse(Float64, row.active_losses_kw),
            reactive_losses_kvar=parse(Float64, row.reactive_losses_kvar),
        )
    end
    length(rows) == length(ROOT_VOLTAGES_PU) || error("previous snapshot rows are incomplete")
    return rows
end

function five_lowest_buses(result)
    order = sortperm(
        collect(eachindex(result.voltage_magnitudes_pu));
        by=index -> (result.voltage_magnitudes_pu[index], index),
    )
    return order[1:5]
end

function five_highest_branches(result)
    return sort(result.branches; by=branch -> (-branch.apparent_power_kva, branch.branch_id))[1:5]
end

function report_table_row(result)
    min_voltage, min_bus = findmin(result.voltage_magnitudes_pu)
    max_voltage, max_bus = findmax(result.voltage_magnitudes_pu)
    max_current = result.branches[argmax(branch.current_a for branch in result.branches)]
    return (
        root_voltage_pu=result.root_voltage_pu,
        case_role=result.root_voltage_pu == 1.00 ? "central_baseline" : "sensitivity",
        snapshot_timestamp=Dates.format(SNAPSHOT_TIMESTAMP, dateformat"yyyy-mm-dd HH:MM:SS"),
        load_multiplier=result.load_multiplier,
        convergence_status=result.converged ? "CONVERGED" : "NOT_CONVERGED",
        iterations=result.iterations,
        minimum_voltage_pu=min_voltage,
        minimum_voltage_bus=min_bus,
        maximum_voltage_pu=max_voltage,
        maximum_voltage_bus=max_bus,
        substation_active_power_kw=result.substation_active_power_kw,
        substation_reactive_power_kvar=result.substation_reactive_power_kvar,
        substation_apparent_power_kva=hypot(result.substation_active_power_kw, result.substation_reactive_power_kvar),
        active_losses_kw=result.active_losses_kw,
        reactive_losses_kvar=result.reactive_losses_kvar,
        maximum_current_branch_id=max_current.branch_id,
        maximum_current_from_bus=max_current.from_bus,
        maximum_current_to_bus=max_current.to_bus,
        maximum_current_a=max_current.current_a,
        active_balance_residual_kw=result.active_balance_residual_kw,
        reactive_balance_residual_kvar=result.reactive_balance_residual_kvar,
        maximum_voltage_equation_residual_pu=result.maximum_voltage_equation_residual_pu,
        maximum_kcl_residual_pu=result.maximum_kcl_residual_pu,
        pv_capacity_kw=result.pv_capacity_kw,
        ev_load_kw=result.ev_load_kw,
        bess_charge_kw=result.bess_charge_kw,
        bess_discharge_kw=result.bess_discharge_kw,
        voltage_limits_applied=result.voltage_limits_applied,
        thermal_limits_applied=result.thermal_limits_applied,
    )
end

function write_report(path, results, prior, runtime_seconds)
    central = only(result for result in results if result.root_voltage_pu == 1.00)
    open(path, "w") do io
        println(io, "# S0 unconstrained AC baseline snapshot")
        println(io)
        println(io, "The central baseline uses V0=1.00 p.u. V0=1.03 and V0=1.05 p.u. are sensitivity cases only.")
        println(io, "The solved timestamp is `2011-02-05 18:00:00`, whose normalized Ausgrid load multiplier is 1.0.")
        println(io)
        println(io, "The primary calculation is an independent nonlinear radial AC backward/forward sweep with constant-PQ IEEE 33-bus loads. PV, EV, and BESS are zero. No voltage band, branch-current bound, apparent-power rating, transformer rating, export policy, or loss cap is present in the solve. No SOCP model is used for the reported values.")
        println(io)
        println(io, "## Raw results")
        println(io)
        println(io, "| V0 | role | Vmin (bus) | Vmax (bus) | Psub (kW) | Qsub (kvar) | Ploss (kW) | Qloss (kvar) | iterations |")
        println(io, "|---:|:---|:---|:---|---:|---:|---:|---:|---:|")
        for result in results
            vmin, bmin = findmin(result.voltage_magnitudes_pu)
            vmax, bmax = findmax(result.voltage_magnitudes_pu)
            role = result.root_voltage_pu == 1.00 ? "central baseline" : "sensitivity"
            @printf(io, "| %.2f | %s | %.9f (%d) | %.9f (%d) | %.6f | %.6f | %.6f | %.6f | %d |\n",
                result.root_voltage_pu, role, vmin, bmin, vmax, bmax,
                result.substation_active_power_kw, result.substation_reactive_power_kvar,
                result.active_losses_kw, result.reactive_losses_kvar, result.iterations)
        end
        println(io)
        println(io, "## Five lowest-voltage buses at V0=1.00")
        println(io)
        println(io, "| bus | voltage (p.u.) |")
        println(io, "|---:|---:|")
        for bus in five_lowest_buses(central)
            @printf(io, "| %d | %.12f |\n", bus, central.voltage_magnitudes_pu[bus])
        end
        println(io)
        println(io, "## Five highest-|S| branches at V0=1.00")
        println(io)
        println(io, "| branch | from | to | P (kW) | Q (kvar) | |S| (kVA) | current (A) |")
        println(io, "|---:|---:|---:|---:|---:|---:|---:|")
        for branch in five_highest_branches(central)
            @printf(io, "| %d | %d | %d | %.6f | %.6f | %.6f | %.6f |\n",
                branch.branch_id, branch.from_bus, branch.to_bus, branch.active_power_kw,
                branch.reactive_power_kvar, branch.apparent_power_kva, branch.current_a)
        end
        println(io)
        println(io, "## Numerical checks")
        println(io)
        for result in results
            old = prior[result.root_voltage_pu]
            vmin = minimum(result.voltage_magnitudes_pu)
            @printf(io, "- V0=%.2f: status=%s; P balance residual=%.3e kW; Q balance residual=%.3e kvar; voltage-equation residual=%.3e p.u.; KCL residual=%.3e p.u.; differences from the previous peak snapshot: Vmin=%.3e p.u., Psub=%.3e kW, Qsub=%.3e kvar.\n",
                result.root_voltage_pu, result.converged ? "CONVERGED" : "NOT_CONVERGED",
                result.active_balance_residual_kw, result.reactive_balance_residual_kvar,
                result.maximum_voltage_equation_residual_pu, result.maximum_kcl_residual_pu,
                abs(vmin - old.minimum_voltage_pu),
                abs(result.substation_active_power_kw - old.substation_active_power_kw),
                abs(result.substation_reactive_power_kvar - old.substation_reactive_power_kvar))
        end
        println(io)
        @printf(io, "Runtime: %.6f s. The existing 52,608-interval outputs were reused only to identify and cross-check the common-factor peak snapshot; the full period was not recalculated.\n", runtime_seconds)
    end
end

function main()
    repository_root = normpath(joinpath(@__DIR__, ".."))
    output_directory = joinpath(repository_root, "results", "s0_unconstrained_baseline")
    input_path = joinpath(repository_root, "data_processed", "ausgrid", "ausgrid_halfhour_normalized.csv")
    prior_path = joinpath(repository_root, "results", "s0_full_period_baseline", "s0_interval_metrics.csv")
    mkpath(output_directory)

    started = time()
    multiplier = snapshot_multiplier(input_path, SNAPSHOT_TIMESTAMP)
    multiplier == 1.0 || error("expected normalized peak multiplier 1.0, found $multiplier")
    prior = prior_snapshot_rows(prior_path, SNAPSHOT_TIMESTAMP)
    results = [solve_s0_unconstrained_snapshot(multiplier, root) for root in ROOT_VOLTAGES_PU]
    all(result -> result.converged, results) || error("an AC snapshot did not converge")

    summary_rows = [report_table_row(result) for result in results]
    bus_rows = NamedTuple[]
    branch_rows = NamedTuple[]
    for result in results
        for (rank, bus) in enumerate(five_lowest_buses(result))
            push!(bus_rows, (
                root_voltage_pu=result.root_voltage_pu,
                case_role=result.root_voltage_pu == 1.00 ? "central_baseline" : "sensitivity",
                rank=rank,
                bus=bus,
                voltage_pu=result.voltage_magnitudes_pu[bus],
            ))
        end
        for (rank, branch) in enumerate(five_highest_branches(result))
            push!(branch_rows, (
                root_voltage_pu=result.root_voltage_pu,
                case_role=result.root_voltage_pu == 1.00 ? "central_baseline" : "sensitivity",
                rank=rank,
                branch_id=branch.branch_id,
                from_bus=branch.from_bus,
                to_bus=branch.to_bus,
                active_power_kw=branch.active_power_kw,
                reactive_power_kvar=branch.reactive_power_kvar,
                apparent_power_kva=branch.apparent_power_kva,
                current_pu=branch.current_pu,
                current_a=branch.current_a,
            ))
        end
    end

    write_csv(joinpath(output_directory, "s0_unconstrained_summary.csv"), summary_rows)
    write_csv(joinpath(output_directory, "s0_worst_buses.csv"), bus_rows)
    write_csv(joinpath(output_directory, "s0_highest_flow_branches.csv"), branch_rows)
    runtime_seconds = time() - started
    write_report(
        joinpath(output_directory, "s0_unconstrained_report.md"),
        results,
        prior,
        runtime_seconds,
    )
    @printf("S0 unconstrained AC snapshot completed in %.6f s\n", runtime_seconds)
end

main()
