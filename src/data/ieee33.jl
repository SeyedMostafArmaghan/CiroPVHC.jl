function build_ieee33_network()
    base_kv = 12.66

    load_data = [
        (1, 0.0, 0.0),
        (2, 100.0, 60.0),
        (3, 90.0, 40.0),
        (4, 120.0, 80.0),
        (5, 60.0, 30.0),
        (6, 60.0, 20.0),
        (7, 200.0, 100.0),
        (8, 200.0, 100.0),
        (9, 60.0, 20.0),
        (10, 60.0, 20.0),
        (11, 45.0, 30.0),
        (12, 60.0, 35.0),
        (13, 60.0, 35.0),
        (14, 120.0, 80.0),
        (15, 60.0, 10.0),
        (16, 60.0, 20.0),
        (17, 60.0, 20.0),
        (18, 90.0, 40.0),
        (19, 90.0, 40.0),
        (20, 90.0, 40.0),
        (21, 90.0, 40.0),
        (22, 90.0, 40.0),
        (23, 90.0, 50.0),
        (24, 420.0, 200.0),
        (25, 420.0, 200.0),
        (26, 60.0, 25.0),
        (27, 60.0, 25.0),
        (28, 60.0, 20.0),
        (29, 120.0, 70.0),
        (30, 200.0, 600.0),
        (31, 150.0, 70.0),
        (32, 210.0, 100.0),
        (33, 60.0, 40.0),
    ]

    branch_data = [
        (1, 1, 2, 0.0922, 0.0470),
        (2, 2, 3, 0.4930, 0.2511),
        (3, 3, 4, 0.3660, 0.1864),
        (4, 4, 5, 0.3811, 0.1941),
        (5, 5, 6, 0.8190, 0.7070),
        (6, 6, 7, 0.1872, 0.6188),
        (7, 7, 8, 0.7114, 0.2351),
        (8, 8, 9, 1.0300, 0.7400),
        (9, 9, 10, 1.0440, 0.7400),
        (10, 10, 11, 0.1966, 0.0650),
        (11, 11, 12, 0.3744, 0.1238),
        (12, 12, 13, 1.4680, 1.1550),
        (13, 13, 14, 0.5416, 0.7129),
        (14, 14, 15, 0.5910, 0.5260),
        (15, 15, 16, 0.7463, 0.5450),
        (16, 16, 17, 1.2890, 1.7210),
        (17, 17, 18, 0.7320, 0.5740),
        (18, 2, 19, 0.1640, 0.1565),
        (19, 19, 20, 1.5042, 1.3554),
        (20, 20, 21, 0.4095, 0.4784),
        (21, 21, 22, 0.7089, 0.9373),
        (22, 3, 23, 0.4512, 0.3083),
        (23, 23, 24, 0.8980, 0.7091),
        (24, 24, 25, 0.8960, 0.7011),
        (25, 6, 26, 0.2030, 0.1034),
        (26, 26, 27, 0.2842, 0.1447),
        (27, 27, 28, 1.0590, 0.9337),
        (28, 28, 29, 0.8042, 0.7006),
        (29, 29, 30, 0.5075, 0.2585),
        (30, 30, 31, 0.9744, 0.9630),
        (31, 31, 32, 0.3105, 0.3619),
        (32, 32, 33, 0.3410, 0.5302),
    ]

    buses = [Bus(id, pd_kw, qd_kvar, base_kv) for (id, pd_kw, qd_kvar) in load_data]
    branches = [
        # MATPOWER case33bw uses rateA = 0 to mean no thermal limit is specified.
        # Keep that missing-rate value in the data; optimization models must not
        # interpret it as zero line capacity.
        Branch(id, from_bus, to_bus, r_ohm, x_ohm, 0.0)
        for (id, from_bus, to_bus, r_ohm, x_ohm) in branch_data
    ]

    return buses, branches
end

function check_radial_network(buses, branches)
    _require(!isempty(buses), "at least one bus is required")

    bus_ids = [bus.id for bus in buses]
    branch_ids = [branch.id for branch in branches]
    _check_unique(bus_ids, "bus ids")
    _check_unique(branch_ids, "branch ids")
    _require(length(branches) == length(buses) - 1, "radial network must have branches = buses - 1")

    bus_id_set = Set(bus_ids)
    for branch in branches
        _require(branch.from_bus in bus_id_set, "branch $(branch.id) from_bus must exist")
        _require(branch.to_bus in bus_id_set, "branch $(branch.id) to_bus must exist")
        _require(branch.from_bus != branch.to_bus, "branch $(branch.id) cannot connect a bus to itself")
    end

    parent = Dict(id => id for id in bus_ids)

    function root(id)
        current = id
        while parent[current] != current
            parent[current] = parent[parent[current]]
            current = parent[current]
        end
        return current
    end

    function union!(a, b)
        ra = root(a)
        rb = root(b)
        if ra == rb
            return false
        end
        parent[rb] = ra
        return true
    end

    for branch in branches
        _require(union!(branch.from_bus, branch.to_bus), "network contains a cycle")
    end

    reference_root = root(first(bus_ids))
    _require(all(id -> root(id) == reference_root, bus_ids), "network must be connected")

    return true
end
