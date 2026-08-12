module DSOVPPProductionProbeContract

"Pure, deterministic contract for the preregistered production boundary search."

const CONVERGED_FEASIBLE = "CONVERGED_FEASIBLE"
const CONVERGED_INFEASIBLE = "CONVERGED_INFEASIBLE"
const NONCONVERGED_FIRST_ATTEMPT = "NONCONVERGED_FIRST_ATTEMPT"
const NONCONVERGED_AFTER_RETRY = "NONCONVERGED_AFTER_RETRY"
const UNRESOLVED = "UNRESOLVED"

const FINITE_VALID_AXIS_STATUSES = Set(["AXIS_CERTIFIED_BOUNDARY"])

Base.@kwdef struct BoundaryEndpoint
    coordinate::Float64
    radius::Union{Nothing,Float64} = nothing
    p13_abs_kw::Float64
    p30_abs_kw::Float64
    vmin_pu::Float64
    vmin_bus::Union{Nothing,Int}
    vmax_pu::Float64
    vmax_bus::Union{Nothing,Int}
    solver_status::String
end

Base.@kwdef struct RetryAttempt
    attempt::Int
    initialization::String
    maximum_iterations::Int = 2_000
    damping::Float64 = 0.70
    convergence_tolerance::Float64 = 1e-11
end

"Only a certified finite voltage boundary can enter the Tier-1 midpoint."
finite_valid_axis_status(status::AbstractString) = status in FINITE_VALID_AXIS_STATUSES

function voltage_class(endpoint::BoundaryEndpoint; vmin_pu=0.90, vmax_pu=1.05)
    endpoint.solver_status == CONVERGED_FEASIBLE &&
        vmin_pu <= endpoint.vmin_pu <= endpoint.vmax_pu <= vmax_pu && return :safe
    endpoint.solver_status == CONVERGED_INFEASIBLE &&
        (endpoint.vmin_pu < vmin_pu || endpoint.vmax_pu > vmax_pu) && return :violating
    endpoint.solver_status in (
        NONCONVERGED_FIRST_ATTEMPT, NONCONVERGED_AFTER_RETRY, UNRESOLVED,
    ) && return :unresolved
    return :invalid
end

function valid_voltage_bracket(
    lower::BoundaryEndpoint, upper::BoundaryEndpoint; vmin_pu=0.90, vmax_pu=1.05,
)
    return lower.coordinate < upper.coordinate &&
           voltage_class(lower; vmin_pu=vmin_pu, vmax_pu=vmax_pu) == :safe &&
           voltage_class(upper; vmin_pu=vmin_pu, vmax_pu=vmax_pu) == :violating
end

function transition_outcome(
    kind::Symbol, lower::BoundaryEndpoint, upper::BoundaryEndpoint;
    vmin_pu=0.90, vmax_pu=1.05,
)
    kind in (:axis, :ray) || throw(ArgumentError("kind must be :axis or :ray"))
    valid_voltage_bracket(lower, upper; vmin_pu=vmin_pu, vmax_pu=vmax_pu) &&
        return kind == :axis ? "AXIS_BRACKET_CERTIFIED" : "RAY_BRACKET_CERTIFIED"
    if voltage_class(lower; vmin_pu=vmin_pu, vmax_pu=vmax_pu) == :safe &&
       voltage_class(upper; vmin_pu=vmin_pu, vmax_pu=vmax_pu) == :unresolved
        return kind == :axis ? "AXIS_UNRESOLVED" : "RAY_UNRESOLVED"
    end
    return kind == :axis ? "AXIS_INVALID_BRACKET" : "RAY_INVALID_BRACKET"
end

"The retry changes initialization. With no accepted neighbor, no identical retry is run."
function retry_plan(; nearest_accepted_neighbor_available::Bool)
    attempts = RetryAttempt[
        RetryAttempt(attempt=1, initialization="FLAT_START"),
    ]
    if nearest_accepted_neighbor_available
        push!(attempts, RetryAttempt(
            attempt=2, initialization="NEAREST_ACCEPTED_NEIGHBOR_START",
        ))
    end
    return attempts
end

function binding_invariant(
    mechanism::AbstractString, violating::BoundaryEndpoint; vmin_pu=0.90, vmax_pu=1.05,
)
    voltage_class(violating; vmin_pu=vmin_pu, vmax_pu=vmax_pu) == :violating ||
        return false
    if mechanism == "BINDING_VMIN"
        return violating.vmin_pu < vmin_pu && violating.vmin_bus !== nothing
    elseif mechanism == "BINDING_VMAX"
        return violating.vmax_pu > vmax_pu && violating.vmax_bus !== nothing
    end
    return false
end

function official_boundary_coordinate(
    safe::BoundaryEndpoint, violating::BoundaryEndpoint; vmin_pu=0.90, vmax_pu=1.05,
)
    valid_voltage_bracket(safe, violating; vmin_pu=vmin_pu, vmax_pu=vmax_pu) ||
        throw(ArgumentError("official boundary requires a converged safe/violating bracket"))
    return safe.coordinate
end

export BoundaryEndpoint,
       RetryAttempt,
       finite_valid_axis_status,
       voltage_class,
       valid_voltage_bracket,
       transition_outcome,
       retry_plan,
       binding_invariant,
       official_boundary_coordinate

end
