const S0_INTERVAL_METRIC_COLUMNS = (
    "root_voltage_pu",
    "timestamp",
    "load_multiplier",
    "operational_solver_status",
    "diagnostic_solver_status",
    "solution_source",
    "primal_available",
    "numerical_validation_passed",
    "operational_voltage_feasible",
    "total_active_load_kw",
    "total_reactive_load_kvar",
    "minimum_voltage_pu",
    "minimum_voltage_bus",
    "maximum_voltage_pu",
    "maximum_voltage_bus",
    "undervoltage_bus_count",
    "overvoltage_bus_count",
    "substation_active_power_kw",
    "substation_reactive_power_kvar",
    "substation_apparent_power_kva",
    "substation_direction",
    "active_losses_kw",
    "reactive_losses_kvar",
    "active_loss_percentage",
    "maximum_ell_pu2",
    "maximum_current_branch_id",
    "maximum_current_a",
    "maximum_soc_gap_pu2",
    "minimum_soc_gap_pu2",
    "maximum_active_balance_residual_kw",
    "maximum_reactive_balance_residual_kvar",
    "maximum_voltage_drop_residual_pu2",
    "root_voltage_residual_pu2",
    "substation_active_balance_residual_kw",
    "substation_reactive_balance_residual_kvar",
)

const S0_SUMMARY_COLUMNS = (
    "root_voltage_pu",
    "interval_count",
    "solved_intervals",
    "solver_failed_intervals",
    "operational_model_fallback_intervals",
    "numerically_valid_intervals",
    "operationally_feasible_intervals",
    "intervals_with_voltage_violations",
    "violation_interval_percentage",
    "undervoltage_bus_time_count",
    "overvoltage_bus_time_count",
    "global_minimum_voltage_pu",
    "global_minimum_voltage_bus",
    "global_minimum_voltage_timestamp",
    "global_maximum_voltage_pu",
    "global_maximum_voltage_bus",
    "global_maximum_voltage_timestamp",
    "peak_branch_id",
    "peak_branch_ell_pu2",
    "peak_branch_current_a",
    "peak_branch_current_timestamp",
    "peak_substation_apparent_power_kva",
    "peak_substation_timestamp",
    "maximum_active_losses_kw",
    "maximum_active_losses_timestamp",
    "maximum_active_loss_percentage",
    "maximum_active_loss_percentage_timestamp",
    "average_active_loss_percentage",
    "maximum_soc_gap_pu2",
    "minimum_soc_gap_pu2",
    "zero_pv_export_intervals",
    "fully_validated",
)

const S0_BRANCH_PEAK_COLUMNS = (
    "root_voltage_pu",
    "branch_id",
    "from_bus",
    "to_bus",
    "peak_ell_pu2",
    "peak_current_pu",
    "peak_current_a",
    "base_current_a",
    "current_conversion_verified",
    "peak_timestamp",
    "sending_active_power_kw",
    "sending_reactive_power_kvar",
    "sending_apparent_power_kva",
    "receiving_active_power_kw",
    "receiving_reactive_power_kvar",
    "receiving_apparent_power_kva",
    "maximum_soc_gap_pu2",
    "minimum_soc_gap_pu2",
)

const S0_VOLTAGE_VIOLATION_COLUMNS = (
    "root_voltage_pu",
    "timestamp",
    "bus",
    "voltage_pu",
    "limit_type",
    "limit_pu",
    "violation_magnitude_pu",
)

const S0_SOLVER_FAILURE_COLUMNS = (
    "root_voltage_pu",
    "timestamp",
    "load_multiplier",
    "operational_solver_status",
    "diagnostic_solver_status",
    "primal_available",
    "failure_reason",
)

const S0_CRITICAL_INTERVAL_COLUMNS = (
    "root_voltage_pu",
    "selection_reason",
    "timestamp",
    "load_multiplier",
    "socp_minimum_voltage_pu",
    "socp_peak_branch_id",
    "socp_peak_branch_current_a",
    "socp_substation_apparent_power_kva",
    "socp_active_loss_percentage",
    "ac_validation_status",
    "ac_iterations",
    "ac_maximum_voltage_difference_pu",
    "ac_substation_active_difference_kw",
    "ac_substation_reactive_difference_kvar",
)

struct S0BaselineConfig
    root_voltages_pu::Vector{Float64}
    vmin_pu::Float64
    vmax_pu::Float64
    diagnostic_vmin_pu::Float64
    diagnostic_vmax_pu::Float64
    dt_hours::Float64
    expected_intervals::Int
    balance_tolerance_kw::Float64
    voltage_drop_tolerance_pu2::Float64
    soc_gap_tolerance_pu2::Float64
    root_voltage_tolerance_pu2::Float64
    ell_tolerance_pu2::Float64
    voltage_tolerance_pu::Float64
    export_tolerance_kw::Float64
    ac_voltage_tolerance_pu::Float64
    ac_power_tolerance_kw::Float64
    pv_capacity_kw::Float64
    ev_load_kw::Float64
    bess_charge_kw::Float64
    bess_discharge_kw::Float64
    no_export_constraint_active::Bool
    loss_cap_constraint_active::Bool
end

function S0BaselineConfig(;
    root_voltages_pu::AbstractVector{<:Real}=[1.00, 1.03, 1.05],
    vmin_pu::Real=0.95,
    vmax_pu::Real=1.05,
    diagnostic_vmin_pu::Real=0.80,
    diagnostic_vmax_pu::Real=1.10,
    dt_hours::Real=0.5,
    expected_intervals::Integer=52_608,
    balance_tolerance_kw::Real=1e-3,
    voltage_drop_tolerance_pu2::Real=1e-8,
    soc_gap_tolerance_pu2::Real=1e-7,
    root_voltage_tolerance_pu2::Real=1e-9,
    ell_tolerance_pu2::Real=1e-10,
    voltage_tolerance_pu::Real=1e-7,
    export_tolerance_kw::Real=1e-6,
    ac_voltage_tolerance_pu::Real=2e-5,
    ac_power_tolerance_kw::Real=2e-2,
)
    roots = Float64.(root_voltages_pu)
    _require(!isempty(roots), "at least one S0 root voltage is required")
    _require(all(isfinite, roots) && all(>(0.0), roots), "S0 root voltages must be finite and positive")
    _check_unique(roots, "S0 root voltages")
    _require(0.0 < vmin_pu <= vmax_pu, "S0 operational voltage bounds are inconsistent")
    _require(0.0 < diagnostic_vmin_pu < vmin_pu, "S0 diagnostic minimum voltage must be below the operational minimum")
    _require(diagnostic_vmax_pu >= vmax_pu, "S0 diagnostic maximum voltage must include the operational maximum")
    _require(all(v -> diagnostic_vmin_pu <= v <= diagnostic_vmax_pu, roots), "S0 root voltage is outside diagnostic bounds")
    _check_positive(dt_hours, "S0 time step")
    _require(expected_intervals > 0, "S0 expected interval count must be positive")
    for (value, label) in (
        (balance_tolerance_kw, "S0 balance tolerance"),
        (voltage_drop_tolerance_pu2, "S0 voltage-drop tolerance"),
        (soc_gap_tolerance_pu2, "S0 SOC-gap tolerance"),
        (root_voltage_tolerance_pu2, "S0 root-voltage tolerance"),
        (ell_tolerance_pu2, "S0 ell tolerance"),
        (voltage_tolerance_pu, "S0 voltage reporting tolerance"),
        (export_tolerance_kw, "S0 export tolerance"),
        (ac_voltage_tolerance_pu, "S0 AC voltage tolerance"),
        (ac_power_tolerance_kw, "S0 AC power tolerance"),
    )
        _check_finite_nonnegative(value, label)
    end

    return S0BaselineConfig(
        roots,
        Float64(vmin_pu),
        Float64(vmax_pu),
        Float64(diagnostic_vmin_pu),
        Float64(diagnostic_vmax_pu),
        Float64(dt_hours),
        Int(expected_intervals),
        Float64(balance_tolerance_kw),
        Float64(voltage_drop_tolerance_pu2),
        Float64(soc_gap_tolerance_pu2),
        Float64(root_voltage_tolerance_pu2),
        Float64(ell_tolerance_pu2),
        Float64(voltage_tolerance_pu),
        Float64(export_tolerance_kw),
        Float64(ac_voltage_tolerance_pu),
        Float64(ac_power_tolerance_kw),
        0.0,
        0.0,
        0.0,
        0.0,
        false,
        false,
    )
end

struct S0LoadProfile
    timestamps::Vector{Dates.DateTime}
    load_multipliers::Vector{Float64}
    dt_hours::Float64
    source_path::String
    source_sha256::String
end

s0_root_voltage_squared(root_voltage_pu::Real) = Float64(root_voltage_pu)^2
s0_scaled_bus_load(bus::Bus, multiplier::Real) =
    (active_power_kw=bus.pd_kw * Float64(multiplier), reactive_power_kvar=bus.qd_kvar * Float64(multiplier))
s0_apparent_power(active_power::Real, reactive_power::Real) = hypot(Float64(active_power), Float64(reactive_power))

function s0_voltage_violation_counts(
    voltages_pu::AbstractVector{<:Real},
    vmin_pu::Real,
    vmax_pu::Real;
    tolerance_pu::Real=0.0,
)
    undervoltage = count(v -> v < vmin_pu - tolerance_pu, voltages_pu)
    overvoltage = count(v -> v > vmax_pu + tolerance_pu, voltages_pu)
    return (undervoltage=undervoltage, overvoltage=overvoltage, total=undervoltage + overvoltage)
end

function s0_branch_peak(values::AbstractVector{<:Real}, timestamps::AbstractVector)
    _require(!isempty(values), "branch peak input must not be empty")
    _require(length(values) == length(timestamps), "branch peak values and timestamps must have equal length")
    index = argmax(values)
    return (index=index, value=Float64(values[index]), timestamp=timestamps[index])
end

function s0_assert_full_interval_coverage(expected::Integer, written::Integer, failed::Integer=0)
    _require(expected > 0, "expected S0 interval count must be positive")
    _require(written == expected, "S0 interval output coverage mismatch: expected $expected, wrote $written")
    _require(0 <= failed <= written, "S0 failed-interval count is inconsistent")
    return true
end
