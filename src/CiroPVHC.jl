module CiroPVHC

using Dates

include("data/types.jl")
include("data/ieee33.jl")
include("data/profiles.jl")
include("data/resources.jl")
include("data/scenarios.jl")
include("data/s0_types.jl")

const _CIROPVHC_SRC_DIR = @__DIR__
const _SOCP_NETWORK_LOADED = Ref(false)
const _S0_SOLVER_LOADED = Ref(false)
const _S1_SOLVER_LOADED = Ref(false)
const _S2_SOLVER_LOADED = Ref(false)
const S1_LOCKED_STAGE2_ACCEPTED_HC_KW = 2766.9654
const DEFAULT_S2_UNMANAGED_EV_SENSITIVITY_SCALES =
    (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0)

struct S1PVOnlyResult
    termination_status::String
    objective_value::Float64
    pv_capacity_by_unit::Dict{Int,Float64}
    voltage_min::Float64
    voltage_max::Float64
    max_line_loading::Float64
    total_pv_capacity_kw::Float64
end

struct S2UnmanagedEVConfig
    scenario_name::Symbol
    selected_time_index::Int
    ev_penetration_scale::Float64
    pv_limit_kw::Float64
    synthetic_smax_kva::Float64
    vmin_pu::Float64
    vmax_pu::Float64
    alpha_cur::Float64
    beta_loss::Float64
    hc_tol_kw::Float64
    hc_search_tol_kw::Float64
    no_export_tol_kw::Float64
    binding_tol::Float64
    s1_hc_baseline_kw::Float64
end

function S2UnmanagedEVConfig(;
    scenario_name::Symbol=:S2,
    selected_time_index::Integer=argmax(build_case33_data().timeseries.pv_profile),
    ev_penetration_scale::Real=1.0,
    pv_limit_kw::Real=20000.0,
    synthetic_smax_kva::Real=4000.0,
    vmin_pu::Real=0.95,
    vmax_pu::Real=1.05,
    alpha_cur::Real=0.05,
    beta_loss::Real=0.10,
    hc_tol_kw::Real=1e-2,
    hc_search_tol_kw::Real=0.10,
    no_export_tol_kw::Real=1e-3,
    binding_tol::Real=1e-4,
    s1_hc_baseline_kw::Real=S1_LOCKED_STAGE2_ACCEPTED_HC_KW,
)
    _require(Int(selected_time_index) > 0, "selected_time_index must be positive")
    _check_finite_nonnegative(Float64(ev_penetration_scale), "EV penetration scale")
    _check_positive(Float64(pv_limit_kw), "PV candidate limit")
    _check_positive(Float64(synthetic_smax_kva), "synthetic branch rating")
    _require(0.0 < Float64(vmin_pu) <= Float64(vmax_pu), "voltage bounds are inconsistent")
    _require(0.0 <= Float64(alpha_cur) <= 1.0, "alpha_cur must be in [0, 1]")
    _require(0.0 <= Float64(beta_loss) <= 1.0, "beta_loss must be in [0, 1]")
    _check_positive(Float64(hc_tol_kw), "hosting-capacity tolerance")
    _check_positive(Float64(hc_search_tol_kw), "hosting-capacity search tolerance")
    _check_finite_nonnegative(Float64(no_export_tol_kw), "no-export tolerance")
    _check_finite_nonnegative(Float64(binding_tol), "binding tolerance")
    _check_positive(Float64(s1_hc_baseline_kw), "S1 hosting-capacity baseline")

    return S2UnmanagedEVConfig(
        scenario_name,
        Int(selected_time_index),
        Float64(ev_penetration_scale),
        Float64(pv_limit_kw),
        Float64(synthetic_smax_kva),
        Float64(vmin_pu),
        Float64(vmax_pu),
        Float64(alpha_cur),
        Float64(beta_loss),
        Float64(hc_tol_kw),
        Float64(hc_search_tol_kw),
        Float64(no_export_tol_kw),
        Float64(binding_tol),
        Float64(s1_hc_baseline_kw),
    )
end

struct S1ComparisonBaseline
    hc_kw::Float64
    network_losses_kw::Float64
    voltage_min::Float64
    max_line_loading::Float64
end

struct S2UnmanagedEVResult
    scenario_name::Symbol
    selected_time_index::Int
    base_load_kw::Float64
    unmanaged_ev_load_kw::Float64
    total_load_kw::Float64
    total_ev_reactive_power_kvar::Float64
    evcs_buses::Vector{Int}
    ev_penetration_scale::Float64
    stage1_termination_status::String
    stage2_termination_status::String
    stage1_hc_kw::Float64
    stage2_accepted_hc_kw::Float64
    total_pv_available_kw::Float64
    total_pv_injected_kw::Float64
    total_pv_curtailed_kw::Float64
    pv_curtailment_percentage::Float64
    substation_active_power_kw::Float64
    substation_reactive_power_kvar::Float64
    network_losses_kw::Float64
    loss_percentage::Float64
    voltage_min::Float64
    voltage_max::Float64
    voltage_min_bus::Int
    voltage_max_bus::Int
    max_line_loading::Float64
    max_line_loading_branch::Int
    max_current_loading::Float64
    max_current_loading_branch::Int
    active_limiting_constraints::Vector{String}
    result_classification::String
    physical_validity_flag::Bool
    s1_baseline_hc_kw::Float64
    s1_baseline_losses_kw::Float64
    s1_baseline_voltage_min::Float64
    s1_baseline_max_line_loading::Float64
    delta_HC_kw::Float64
    delta_HC_percent::Float64
    delta_losses_kw::Float64
    delta_voltage_min::Float64
    delta_max_line_loading::Float64
end

function _load_socp_network!()
    if !_SOCP_NETWORK_LOADED[]
        Base.include(@__MODULE__, joinpath(_CIROPVHC_SRC_DIR, "models", "socp_network.jl"))
        _SOCP_NETWORK_LOADED[] = true
    end
    return true
end

function _load_s0_solver!()
    if !_S0_SOLVER_LOADED[]
        try
            _load_socp_network!()
            Base.include(@__MODULE__, joinpath(_CIROPVHC_SRC_DIR, "validation", "s0_baseline.jl"))
            _S0_SOLVER_LOADED[] = true
        catch err
            throw(ArgumentError(
                "The S0 baseline validator requires JuMP and Clarabel. " *
                "Run Julia with this project instantiated, then try again. Original error: $(err)",
            ))
        end
    end
    return true
end

function _load_s1_solver!()
    if !_S1_SOLVER_LOADED[]
        try
            _load_socp_network!()
            Base.include(@__MODULE__, joinpath(_CIROPVHC_SRC_DIR, "models", "pv_model.jl"))
            Base.include(@__MODULE__, joinpath(_CIROPVHC_SRC_DIR, "solve", "solve_s1_pv_only.jl"))
            _S1_SOLVER_LOADED[] = true
        catch err
            throw(ArgumentError(
                "The S1 PV-only solver requires JuMP and Clarabel. " *
                "Run Julia with this project instantiated, then try again. Original error: $(err)",
            ))
        end
    end
    return true
end

function read_ausgrid_s0_load_profile(args...; kwargs...)
    _load_s0_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_read_ausgrid_s0_load_profile)
    return Base.invokelatest(impl, args...; kwargs...)
end

function build_s0_baseline_model(args...; kwargs...)
    _load_s0_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_build_s0_baseline_model)
    return Base.invokelatest(impl, args...; kwargs...)
end

function solve_s0_load_state(args...; kwargs...)
    _load_s0_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_solve_s0_load_state)
    return Base.invokelatest(impl, args...; kwargs...)
end

function run_s0_full_period_baseline(args...; kwargs...)
    _load_s0_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_run_s0_full_period_baseline)
    return Base.invokelatest(impl, args...; kwargs...)
end

function _load_s2_solver!()
    _load_s1_solver!()
    if !_S2_SOLVER_LOADED[]
        try
            Base.include(@__MODULE__, joinpath(_CIROPVHC_SRC_DIR, "models", "ev_model.jl"))
            Base.include(@__MODULE__, joinpath(_CIROPVHC_SRC_DIR, "solve", "solve_s2_unmanaged_ev.jl"))
            _S2_SOLVER_LOADED[] = true
        catch err
            throw(ArgumentError(
                "The S2 unmanaged-EV solver requires JuMP and Clarabel. " *
                "Run Julia with this project instantiated, then try again. Original error: $(err)",
            ))
        end
    end
    return true
end

function build_s1_pv_only_model(args...; kwargs...)
    _load_s1_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_build_s1_pv_only_model)
    return Base.invokelatest(impl, args...; kwargs...)
end

function solve_s1_pv_only(args...; kwargs...)
    _load_s1_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_solve_s1_pv_only)
    return Base.invokelatest(impl, args...; kwargs...)
end

function build_s1_pv_only_paper_case(args...; kwargs...)
    _load_s1_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_build_s1_pv_only_paper_case)
    return Base.invokelatest(impl, args...; kwargs...)
end

function build_s1_pv_only_paper_model(args...; kwargs...)
    _load_s1_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_build_s1_pv_only_paper_model)
    return Base.invokelatest(impl, args...; kwargs...)
end

function solve_s1_pv_only_paper_model(args...; kwargs...)
    _load_s1_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_solve_s1_pv_only_paper_model)
    return Base.invokelatest(impl, args...; kwargs...)
end

function build_s2_unmanaged_ev_paper_case(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_build_s2_unmanaged_ev_paper_case)
    return Base.invokelatest(impl, args...; kwargs...)
end

function build_s2_unmanaged_ev_model(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_build_s2_unmanaged_ev_model)
    return Base.invokelatest(impl, args...; kwargs...)
end

function solve_s2_unmanaged_ev(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_solve_s2_unmanaged_ev)
    return Base.invokelatest(impl, args...; kwargs...)
end

function solve_s2_unmanaged_ev_sensitivity(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_solve_s2_unmanaged_ev_sensitivity)
    return Base.invokelatest(impl, args...; kwargs...)
end

function write_s2_unmanaged_ev_sensitivity_csv(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_write_s2_unmanaged_ev_sensitivity_csv)
    return Base.invokelatest(impl, args...; kwargs...)
end

function unmanaged_ev_load_by_bus(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_unmanaged_ev_load_by_bus)
    return Base.invokelatest(impl, args...; kwargs...)
end

function unmanaged_ev_active_power_kw(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_unmanaged_ev_active_power_kw)
    return Base.invokelatest(impl, args...; kwargs...)
end

function unmanaged_ev_reactive_power_kvar(args...; kwargs...)
    _load_s2_solver!()
    impl = Base.invokelatest(getfield, @__MODULE__, :_unmanaged_ev_reactive_power_kvar)
    return Base.invokelatest(impl, args...; kwargs...)
end

export Bus,
    Branch,
    PVUnit,
    EVCS,
    BESS,
    DOE,
    TimeSeries,
    CaseData,
    ScenarioConfig,
    S0BaselineConfig,
    S0LoadProfile,
    S0_INTERVAL_METRIC_COLUMNS,
    S0_SUMMARY_COLUMNS,
    S0_BRANCH_PEAK_COLUMNS,
    S0_VOLTAGE_VIOLATION_COLUMNS,
    S0_SOLVER_FAILURE_COLUMNS,
    S0_CRITICAL_INTERVAL_COLUMNS,
    S1_LOCKED_STAGE2_ACCEPTED_HC_KW,
    DEFAULT_S2_UNMANAGED_EV_SENSITIVITY_SCALES,
    build_ieee33_network,
    build_default_timeseries,
    build_default_pv_units,
    build_default_evcs_units,
    build_default_bess_units,
    build_default_doe,
    build_core_scenarios,
    build_case33_data,
    check_data_consistency,
    check_radial_network,
    s0_root_voltage_squared,
    s0_scaled_bus_load,
    s0_apparent_power,
    s0_voltage_violation_counts,
    s0_branch_peak,
    s0_assert_full_interval_coverage,
    read_ausgrid_s0_load_profile,
    build_s0_baseline_model,
    solve_s0_load_state,
    run_s0_full_period_baseline,
    S1PVOnlyResult,
    S2UnmanagedEVConfig,
    S1ComparisonBaseline,
    S2UnmanagedEVResult,
    build_s1_pv_only_model,
    solve_s1_pv_only,
    build_s1_pv_only_paper_case,
    build_s1_pv_only_paper_model,
    solve_s1_pv_only_paper_model,
    build_s2_unmanaged_ev_paper_case,
    build_s2_unmanaged_ev_model,
    solve_s2_unmanaged_ev,
    solve_s2_unmanaged_ev_sensitivity,
    write_s2_unmanaged_ev_sensitivity_csv,
    unmanaged_ev_load_by_bus,
    unmanaged_ev_active_power_kw,
    unmanaged_ev_reactive_power_kvar

end
