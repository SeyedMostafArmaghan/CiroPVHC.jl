struct Bus
    id::Int
    pd_kw::Float64
    qd_kvar::Float64
    base_kv::Float64
end

struct Branch
    id::Int
    from_bus::Int
    to_bus::Int
    r_ohm::Float64
    x_ohm::Float64
    smax_kva::Float64
end

struct PVUnit
    id::Int
    bus::Int
    pmax_kw::Float64
    smax_kva::Float64
end

struct EVCS
    id::Int
    bus::Int
    pmax_kw::Float64
    eta::Float64
    required_energy_kwh::Float64
    charger_count::Int
    charging_power_factor::Float64
    reactive_power_convention::Symbol
    unmanaged_profile_scale::Float64
    ev_penetration_scale::Float64
end

function EVCS(
    id::Integer,
    bus::Integer,
    pmax_kw::Real,
    eta::Real,
    required_energy_kwh::Real,
)
    return EVCS(
        Int(id),
        Int(bus),
        Float64(pmax_kw),
        Float64(eta),
        Float64(required_energy_kwh),
        1,
        0.95,
        :lagging,
        1.0,
        1.0,
    )
end

function EVCS(;
    id::Integer,
    bus::Integer,
    pmax_kw::Real,
    eta::Real=1.0,
    required_energy_kwh::Real=0.0,
    charger_count::Integer=1,
    charging_power_factor::Real=0.95,
    reactive_power_convention::Symbol=:lagging,
    unmanaged_profile_scale::Real=1.0,
    ev_penetration_scale::Real=1.0,
)
    return EVCS(
        Int(id),
        Int(bus),
        Float64(pmax_kw),
        Float64(eta),
        Float64(required_energy_kwh),
        Int(charger_count),
        Float64(charging_power_factor),
        reactive_power_convention,
        Float64(unmanaged_profile_scale),
        Float64(ev_penetration_scale),
    )
end

struct BESS
    id::Int
    bus::Int
    pch_max_kw::Float64
    pdis_max_kw::Float64
    e_min_kwh::Float64
    e_max_kwh::Float64
    e0_kwh::Float64
    eta_ch::Float64
    eta_dis::Float64
    smax_kva::Float64
end

struct DOE
    pcc_bus::Int
    p_import_max_kw::Vector{Float64}
    p_export_max_kw::Vector{Float64}
end

struct TimeSeries
    T::Int
    dt_hours::Float64
    load_multiplier::Vector{Float64}
    pv_profile::Vector{Float64}
    ev_availability::Vector{Float64}
    unmanaged_ev_profile::Vector{Float64}
end

struct CaseData
    buses::Vector{Bus}
    branches::Vector{Branch}
    pv_units::Vector{PVUnit}
    evcs_units::Vector{EVCS}
    bess_units::Vector{BESS}
    doe::Union{Nothing,DOE}
    timeseries::TimeSeries
    base_mva::Float64
    vmin_pu::Float64
    vmax_pu::Float64
end

struct ScenarioConfig
    name::Symbol
    description::String
    enable_pv::Bool
    enable_unmanaged_ev::Bool
    enable_smart_ev::Bool
    enable_bess::Bool
    enable_doe::Bool
    enable_robust::Bool
    uncertainty_level::Symbol
end

function _require(condition::Bool, message::AbstractString)
    condition || throw(ArgumentError(String(message)))
    return true
end

function _check_unique(values, label::AbstractString)
    return _require(length(unique(values)) == length(values), "$(label) must be unique")
end

function _check_finite_nonnegative(value::Real, label::AbstractString)
    _require(isfinite(Float64(value)), "$(label) must be finite")
    return _require(value >= 0, "$(label) must be nonnegative")
end

function _check_positive(value::Real, label::AbstractString)
    _require(isfinite(Float64(value)), "$(label) must be finite")
    return _require(value > 0, "$(label) must be positive")
end

function _check_probability_vector(values::Vector{Float64}, label::AbstractString)
    _require(all(isfinite, values), "$(label) must contain only finite values")
    return _require(all(x -> 0.0 <= x <= 1.0, values), "$(label) entries must be in [0, 1]")
end

function _check_nonnegative_vector(values::Vector{Float64}, label::AbstractString)
    _require(all(isfinite, values), "$(label) must contain only finite values")
    return _require(all(x -> x >= 0.0, values), "$(label) entries must be nonnegative")
end

function check_data_consistency(data::CaseData)
    _require(!isempty(data.buses), "at least one bus is required")
    _check_unique([bus.id for bus in data.buses], "bus ids")
    _check_unique([branch.id for branch in data.branches], "branch ids")

    bus_ids = Set(bus.id for bus in data.buses)

    for bus in data.buses
        _check_finite_nonnegative(bus.pd_kw, "bus $(bus.id) active load")
        _check_finite_nonnegative(bus.qd_kvar, "bus $(bus.id) reactive load")
        _check_positive(bus.base_kv, "bus $(bus.id) base voltage")
    end

    for branch in data.branches
        _require(branch.from_bus in bus_ids, "branch $(branch.id) from_bus must exist")
        _require(branch.to_bus in bus_ids, "branch $(branch.id) to_bus must exist")
        _check_finite_nonnegative(branch.r_ohm, "branch $(branch.id) resistance")
        _check_finite_nonnegative(branch.x_ohm, "branch $(branch.id) reactance")
        _check_finite_nonnegative(branch.smax_kva, "branch $(branch.id) capacity")
    end

    check_radial_network(data.buses, data.branches)

    for pv in data.pv_units
        _require(pv.bus in bus_ids, "PV unit $(pv.id) bus must exist")
        _check_finite_nonnegative(pv.pmax_kw, "PV unit $(pv.id) active capacity")
        _check_finite_nonnegative(pv.smax_kva, "PV unit $(pv.id) apparent capacity")
    end

    for evcs in data.evcs_units
        _require(evcs.bus in bus_ids, "EVCS $(evcs.id) bus must exist")
        _check_finite_nonnegative(evcs.pmax_kw, "EVCS $(evcs.id) capacity")
        _check_finite_nonnegative(evcs.required_energy_kwh, "EVCS $(evcs.id) required energy")
        _require(evcs.charger_count > 0, "EVCS $(evcs.id) charger count must be positive")
        _require(isfinite(evcs.charging_power_factor), "EVCS $(evcs.id) charging power factor must be finite")
        _require(0.0 < evcs.charging_power_factor <= 1.0, "EVCS $(evcs.id) charging power factor must be in (0, 1]")
        _require(
            evcs.reactive_power_convention in (:lagging, :leading, :unity),
            "EVCS $(evcs.id) reactive power convention must be :lagging, :leading, or :unity",
        )
        _check_finite_nonnegative(evcs.unmanaged_profile_scale, "EVCS $(evcs.id) unmanaged profile scale")
        _check_finite_nonnegative(evcs.ev_penetration_scale, "EVCS $(evcs.id) EV penetration scale")
        _require(isfinite(evcs.eta), "EVCS $(evcs.id) efficiency must be finite")
        _require(0.0 < evcs.eta <= 1.0, "EVCS $(evcs.id) efficiency must be in (0, 1]")
    end

    for bess in data.bess_units
        _require(bess.bus in bus_ids, "BESS $(bess.id) bus must exist")
        _check_finite_nonnegative(bess.pch_max_kw, "BESS $(bess.id) charge capacity")
        _check_finite_nonnegative(bess.pdis_max_kw, "BESS $(bess.id) discharge capacity")
        _check_finite_nonnegative(bess.e_min_kwh, "BESS $(bess.id) minimum energy")
        _check_finite_nonnegative(bess.e_max_kwh, "BESS $(bess.id) maximum energy")
        _check_finite_nonnegative(bess.e0_kwh, "BESS $(bess.id) initial energy")
        _require(bess.e_min_kwh <= bess.e_max_kwh, "BESS $(bess.id) energy bounds are inconsistent")
        _require(bess.e_min_kwh <= bess.e0_kwh <= bess.e_max_kwh, "BESS $(bess.id) e0 must be inside bounds")
        _require(isfinite(bess.eta_ch), "BESS $(bess.id) charge efficiency must be finite")
        _require(isfinite(bess.eta_dis), "BESS $(bess.id) discharge efficiency must be finite")
        _require(0.0 < bess.eta_ch <= 1.0, "BESS $(bess.id) charge efficiency must be in (0, 1]")
        _require(0.0 < bess.eta_dis <= 1.0, "BESS $(bess.id) discharge efficiency must be in (0, 1]")
        _check_finite_nonnegative(bess.smax_kva, "BESS $(bess.id) apparent capacity")
    end

    ts = data.timeseries
    _require(ts.T > 0, "time-series horizon T must be positive")
    _check_positive(ts.dt_hours, "time-step duration")
    _require(length(ts.load_multiplier) == ts.T, "load_multiplier length must match T")
    _require(length(ts.pv_profile) == ts.T, "pv_profile length must match T")
    _require(length(ts.ev_availability) == ts.T, "ev_availability length must match T")
    _require(length(ts.unmanaged_ev_profile) == ts.T, "unmanaged_ev_profile length must match T")
    _check_nonnegative_vector(ts.load_multiplier, "load_multiplier")
    _check_probability_vector(ts.pv_profile, "pv_profile")
    _check_probability_vector(ts.ev_availability, "ev_availability")
    _check_nonnegative_vector(ts.unmanaged_ev_profile, "unmanaged_ev_profile")

    if data.doe !== nothing
        _require(data.doe.pcc_bus in bus_ids, "DOE PCC bus must exist")
        _require(length(data.doe.p_import_max_kw) == ts.T, "DOE import envelope length must match T")
        _require(length(data.doe.p_export_max_kw) == ts.T, "DOE export envelope length must match T")
        _check_nonnegative_vector(data.doe.p_import_max_kw, "DOE import envelope")
        _check_nonnegative_vector(data.doe.p_export_max_kw, "DOE export envelope")
    end

    _check_positive(data.base_mva, "base MVA")
    _require(isfinite(data.vmin_pu), "minimum voltage must be finite")
    _require(isfinite(data.vmax_pu), "maximum voltage must be finite")
    _require(0.0 < data.vmin_pu <= data.vmax_pu, "voltage bounds are inconsistent")

    return true
end
