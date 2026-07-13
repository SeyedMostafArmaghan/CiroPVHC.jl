include(joinpath(@__DIR__, "..", "src", "CiroPVHC.jl"))

using .CiroPVHC

function rounded(value::Real; digits::Int=4)
    return isfinite(Float64(value)) ? string(round(Float64(value); digits=digits)) : "unavailable"
end

function joined(values)
    return isempty(values) ? "[]" : "[" * join(values, ", ") * "]"
end

function percent_from_fraction(value::Real; digits::Int=4)
    return isfinite(Float64(value)) ? rounded(100.0 * Float64(value); digits=digits) : "unavailable"
end

function print_full_result(result::S2UnmanagedEVResult)
    println()
    println("EV scale: $(rounded(result.ev_penetration_scale; digits=2))")
    println("base_load_kw: $(rounded(result.base_load_kw))")
    println("unmanaged_ev_load_kw: $(rounded(result.unmanaged_ev_load_kw))")
    println("total_load_kw: $(rounded(result.total_load_kw))")
    println("total_ev_reactive_power_kvar: $(rounded(result.total_ev_reactive_power_kvar))")
    println("stage1_status: $(result.stage1_termination_status)")
    println("stage2_status: $(result.stage2_termination_status)")
    println("stage1_hc_kw: $(rounded(result.stage1_hc_kw))")
    println("stage2_accepted_hc_kw: $(rounded(result.stage2_accepted_hc_kw))")
    println("physical_validity_flag: $(result.physical_validity_flag)")
    println("delta_HC_kw_vs_S1: $(rounded(result.delta_HC_kw))")
    println("delta_HC_percent_vs_S1: $(rounded(result.delta_HC_percent))")
    println("total_pv_injected_kw: $(rounded(result.total_pv_injected_kw))")
    println("total_pv_curtailed_kw: $(rounded(result.total_pv_curtailed_kw))")
    println("PV_curtailment_percentage: $(rounded(result.pv_curtailment_percentage))")
    println("substation_active_power_kw: $(rounded(result.substation_active_power_kw))")
    println("substation_reactive_power_kvar: $(rounded(result.substation_reactive_power_kvar))")
    println("network_losses_kw: $(rounded(result.network_losses_kw))")
    println("loss_percentage: $(rounded(result.loss_percentage))")
    println("voltage_min: $(rounded(result.voltage_min; digits=5))")
    println("voltage_max: $(rounded(result.voltage_max; digits=5))")
    println("voltage_min_bus: $(result.voltage_min_bus)")
    println("voltage_max_bus: $(result.voltage_max_bus)")
    println("max_line_loading: $(rounded(result.max_line_loading; digits=5))")
    println("max_line_loading_branch: $(result.max_line_loading_branch)")
    println("max_current_loading: $(rounded(result.max_current_loading; digits=5))")
    println("max_current_loading_branch: $(result.max_current_loading_branch)")
    println("active_limiting_constraints: $(joined(result.active_limiting_constraints))")
    println("result_classification: $(result.result_classification)")
end

function sensitivity_summary_rows(results::AbstractVector{<:S2UnmanagedEVResult})
    return [
        String[
            rounded(result.ev_penetration_scale; digits=2),
            rounded(result.unmanaged_ev_load_kw),
            rounded(result.total_load_kw),
            rounded(result.stage2_accepted_hc_kw),
            rounded(result.delta_HC_kw),
            rounded(result.delta_HC_percent),
            rounded(result.network_losses_kw),
            rounded(result.loss_percentage),
            rounded(result.voltage_min; digits=5),
            rounded(result.voltage_max; digits=5),
            percent_from_fraction(result.max_line_loading),
            percent_from_fraction(result.max_current_loading),
            rounded(result.pv_curtailment_percentage),
            string(result.physical_validity_flag),
            result.result_classification,
        ]
        for result in results
    ]
end

function print_sensitivity_summary(results::AbstractVector{<:S2UnmanagedEVResult})
    headers = String[
        "EV scale",
        "EV load kW",
        "Total load kW",
        "Accepted HC kW",
        "Delta HC vs S1 kW",
        "Delta HC vs S1 %",
        "Losses kW",
        "Loss %",
        "Vmin p.u.",
        "Vmax p.u.",
        "Max line loading %",
        "Max current loading %",
        "Curtailment %",
        "Physical validity",
        "Classification",
    ]
    rows = sensitivity_summary_rows(results)
    all_rows = vcat([headers], rows)
    widths = [maximum(length(row[column]) for row in all_rows) for column in eachindex(headers)]

    function print_row(row)
        println("| ", join((rpad(value, widths[index]) for (index, value) in enumerate(row)), " | "), " |")
    end

    println()
    println("S2 unmanaged-EV sensitivity summary")
    print_row(headers)
    println("|", join((repeat("-", width + 2) for width in widths), "|"), "|")
    for row in rows
        print_row(row)
    end
end

function trend_word(initial::Real, final::Real; tolerance::Float64=1e-4)
    if final > initial + tolerance
        return "increased"
    elseif final < initial - tolerance
        return "decreased"
    end
    return "remained effectively unchanged"
end

function voltage_headroom(result::S2UnmanagedEVResult, config::S2UnmanagedEVConfig)
    values = (result.voltage_min - config.vmin_pu, config.vmax_pu - result.voltage_max)
    return all(isfinite, values) ? minimum(values) : NaN
end

function loading_headroom(result::S2UnmanagedEVResult)
    values = (1.0 - result.max_line_loading, 1.0 - result.max_current_loading)
    return all(isfinite, values) ? minimum(values) : NaN
end

function print_interpretation(results::AbstractVector{<:S2UnmanagedEVResult}, config::S2UnmanagedEVConfig)
    valid_results = sort(
        [result for result in results if result.physical_validity_flag];
        by=result -> result.ev_penetration_scale,
    )
    invalid_results = [result for result in results if !result.physical_validity_flag]

    println()
    println("Automatic interpretation")
    if length(valid_results) >= 2
        low_scale = first(valid_results)
        high_scale = last(valid_results)
        println(
            "Across valid cases from EV scale $(rounded(low_scale.ev_penetration_scale; digits=2)) " *
            "to $(rounded(high_scale.ev_penetration_scale; digits=2)), accepted HC " *
            "$(trend_word(low_scale.stage2_accepted_hc_kw, high_scale.stage2_accepted_hc_kw)) " *
            "from $(rounded(low_scale.stage2_accepted_hc_kw)) to " *
            "$(rounded(high_scale.stage2_accepted_hc_kw)) kW.",
        )
        println(
            "Network losses $(trend_word(low_scale.network_losses_kw, high_scale.network_losses_kw)) " *
            "from $(rounded(low_scale.network_losses_kw)) to " *
            "$(rounded(high_scale.network_losses_kw)) kW.",
        )
        println(
            "Voltage headroom $(trend_word(voltage_headroom(low_scale, config), voltage_headroom(high_scale, config))) " *
            "and line/current headroom $(trend_word(loading_headroom(low_scale), loading_headroom(high_scale); tolerance=1e-5)); " *
            "a decrease means operation moved closer to a limit.",
        )
    elseif length(valid_results) == 1
        println("Only EV scale $(rounded(valid_results[1].ev_penetration_scale; digits=2)) produced a physically valid case.")
    else
        println("No requested EV scale produced a physically valid case.")
    end

    if isempty(invalid_results)
        println("No requested scale became infeasible or failed the physical-validity gate.")
    else
        invalid_scales = join((rounded(result.ev_penetration_scale; digits=2) for result in invalid_results), ", ")
        classifications = join(unique(result.result_classification for result in invalid_results), ", ")
        println("Scales $(invalid_scales) were not accepted as physical HC cases: $(classifications).")
    end

    classifications = unique(result.result_classification for result in valid_results)
    if isempty(classifications)
        println("No active limiting-constraint classification is available.")
    elseif length(classifications) == 1
        println("The active limiting-constraint classification remained $(only(classifications)).")
    else
        println("The active limiting-constraint classification changed across valid scales: $(join(classifications, "; ")).")
    end
end

config = S2UnmanagedEVConfig()
scales = collect(DEFAULT_S2_UNMANAGED_EV_SENSITIVITY_SCALES)
results = solve_s2_unmanaged_ev_sensitivity(scales; config=config)
csv_path = write_s2_unmanaged_ev_sensitivity_csv(
    joinpath(@__DIR__, "..", "results", "s2_unmanaged_ev_sensitivity.csv"),
    results,
)

println("CiroPVHC S2 PV + unmanaged EV sensitivity study")
println("selected_time_index: $(config.selected_time_index)")
println("s1_locked_hc_baseline_kw: $(rounded(config.s1_hc_baseline_kw))")
println("sensitivity_scales: $(joined(string.(scales)))")
println("unmanaged_ev_charging: fixed active and reactive demand, not optimized")

for result in results
    print_full_result(result)
end

print_sensitivity_summary(results)
println()
println("CSV output: $(csv_path)")
print_interpretation(results, config)
