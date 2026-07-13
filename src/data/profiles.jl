function build_default_timeseries(T::Integer=24)
    _require(T > 0, "T must be positive")

    n_steps = Int(T)
    dt_hours = 24.0 / Float64(n_steps)
    hours = [dt_hours * (t - 1) for t in 1:n_steps]

    load_multiplier = [
        clamp(
            0.58 +
            0.22 * exp(-((hour - 8.0) / 4.0)^2) +
            0.42 * exp(-((hour - 19.0) / 4.5)^2),
            0.45,
            1.25,
        )
        for hour in hours
    ]

    pv_profile = [
        (6.0 <= hour <= 18.0) ? clamp(sin(pi * (hour - 6.0) / 12.0)^1.35, 0.0, 1.0) : 0.0
        for hour in hours
    ]

    ev_availability = [
        clamp(
            0.15 +
            0.70 * exp(-((hour - 2.0) / 4.0)^2) +
            0.65 * exp(-((hour - 21.0) / 3.2)^2),
            0.0,
            1.0,
        )
        for hour in hours
    ]

    unmanaged_ev_profile = [
        clamp(
            0.03 +
            0.92 * exp(-((hour - 19.5) / 3.0)^2) +
            0.18 * exp(-((hour - 7.0) / 2.4)^2),
            0.0,
            1.0,
        )
        for hour in hours
    ]

    return TimeSeries(
        n_steps,
        dt_hours,
        Float64.(load_multiplier),
        Float64.(pv_profile),
        Float64.(ev_availability),
        Float64.(unmanaged_ev_profile),
    )
end
