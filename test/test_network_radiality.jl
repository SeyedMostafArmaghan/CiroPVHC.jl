@testset "IEEE 33 radial network" begin
    buses, branches = build_ieee33_network()

    @test length(buses) == 33
    @test length(branches) == length(buses) - 1
    @test check_radial_network(buses, branches)
end

@testset "radiality validation catches structural errors" begin
    buses = [Bus(1, 0.0, 0.0, 12.66), Bus(2, 0.0, 0.0, 12.66), Bus(3, 0.0, 0.0, 12.66)]

    connected_tree = [
        Branch(1, 1, 2, 0.1, 0.1, 1000.0),
        Branch(2, 2, 3, 0.1, 0.1, 1000.0),
    ]
    @test check_radial_network(buses, connected_tree)

    too_few_branches = [Branch(1, 1, 2, 0.1, 0.1, 1000.0)]
    @test_throws ArgumentError check_radial_network(buses, too_few_branches)

    duplicate_branch_ids = [
        Branch(1, 1, 2, 0.1, 0.1, 1000.0),
        Branch(1, 2, 3, 0.1, 0.1, 1000.0),
    ]
    @test_throws ArgumentError check_radial_network(buses, duplicate_branch_ids)

    bad_endpoint = [
        Branch(1, 1, 2, 0.1, 0.1, 1000.0),
        Branch(2, 2, 99, 0.1, 0.1, 1000.0),
    ]
    @test_throws ArgumentError check_radial_network(buses, bad_endpoint)

    repeated_edge = [
        Branch(1, 1, 2, 0.1, 0.1, 1000.0),
        Branch(2, 1, 2, 0.1, 0.1, 1000.0),
    ]
    @test_throws ArgumentError check_radial_network(buses, repeated_edge)
end
