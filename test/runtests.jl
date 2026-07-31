using Test
using CiroPVHC

include("test_data.jl")
include("test_profiles.jl")
include("test_scenarios.jl")
include("test_network_radiality.jl")
include("test_s0_baseline.jl")
include("test_s0_unconstrained_baseline.jl")
include("test_s1_pv_only.jl")
include("test_s1b_central.jl")
include("test_s1b_method_benchmark.jl")
include("test_s1b_ac_constraint_generation.jl")
include("test_dso_vpp_ac_map_stage0.jl")
include("test_dso_vpp_ac_map_stage0_physical_inputs.jl")
include("test_dso_vpp_ac_map_stage0_timestamp_vectors.jl")
include("test_dso_vpp_export_side_axis_scan.jl")
include("test_s2_unmanaged_ev.jl")
