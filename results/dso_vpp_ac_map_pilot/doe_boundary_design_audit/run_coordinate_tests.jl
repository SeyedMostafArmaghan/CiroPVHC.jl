using Test
using CiroPVHC

repository_root = normpath(joinpath(@__DIR__, "..", "..", ".."))
include(joinpath(repository_root, "test", "test_interface_coordinates.jl"))
