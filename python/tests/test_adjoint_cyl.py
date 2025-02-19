import meep as mp
try:
    import meep.adjoint as mpa
except:
    import adjoint as mpa
import numpy as np
from autograd import numpy as npa
from autograd import tensor_jacobian_product
import unittest
from enum import Enum
from utils import ApproxComparisonTestCase

rng = np.random.RandomState(2)
resolution = 20
dimensions = mp.CYLINDRICAL
m=0
Si = mp.Medium(index=3.4)
SiO2 = mp.Medium(index=1.44)

sr = 6
sz = 6
cell_size = mp.Vector3(sr, 0, sz)
dpml = 1.0
boundary_layers = [mp.PML(thickness=dpml)]

design_region_resolution = int(2*resolution)
design_r = 4.8
design_z = 2
Nr = int(design_region_resolution*design_r) + 1
Nz = int(design_region_resolution*design_z) + 1

fcen = 1/1.55
width = 0.2
fwidth = width * fcen
source_center  = [0.1+design_r/2,0,(sz/2-dpml+design_z/2)/2]
source_size    = mp.Vector3(design_r,0,0)
src = mp.GaussianSource(frequency=fcen,fwidth=fwidth)
source = [mp.Source(src,component=mp.Er,
                    center=source_center,
                    size=source_size)]

## random design region
p = 0.5*rng.rand(Nr*Nz)
## random epsilon perturbation for design region
deps = 1e-5
dp = deps*rng.rand(Nr*Nz)


def forward_simulation(design_params):
    matgrid = mp.MaterialGrid(mp.Vector3(Nr,0,Nz),
                              SiO2,
                              Si,
                              weights=design_params.reshape(Nr,1,Nz))

    geometry = [mp.Block(center=mp.Vector3(0.1+design_r/2,0,0),
                                 size=mp.Vector3(design_r,0,design_z),
                                 material=matgrid)]

    sim = mp.Simulation(resolution=resolution,
                        cell_size=cell_size,
                        boundary_layers=boundary_layers,
                        sources=source,
                        geometry=geometry,
                        dimensions=dimensions,
                        m=m)

    frequencies = [fcen]
    far_x = [mp.Vector3(5,0,20)]
    mode = sim.add_near2far(
        frequencies,
        mp.Near2FarRegion(center=mp.Vector3(0.1+design_r/2,0,(sz/2-dpml+design_z/2)/2),
                          size=mp.Vector3(design_r,0,0),weight=+1))

    sim.run(until_after_sources=1200)
    Er = sim.get_farfield(mode, far_x[0])
    sim.reset_meep()

    return abs(Er[0])**2


def adjoint_solver(design_params):

    design_variables = mp.MaterialGrid(mp.Vector3(Nr,0,Nz),SiO2,Si)
    design_region = mpa.DesignRegion(design_variables,
                                     volume=mp.Volume(center=mp.Vector3(0.1+design_r/2,0,0),
                                                      size=mp.Vector3(design_r,0,design_z)))
    geometry = [mp.Block(center=design_region.center,
                         size=design_region.size,
                         material=design_variables)]

    sim = mp.Simulation(cell_size=cell_size,
        boundary_layers=boundary_layers,
        geometry=geometry,
        sources=source,
        resolution=resolution,
        dimensions=dimensions,
        m=m)

    far_x = [mp.Vector3(5,0,20)]
    NearRegions = [mp.Near2FarRegion(center=mp.Vector3(0.1+design_r/2,0,(sz/2-dpml+design_z/2)/2),
                                     size=mp.Vector3(design_r,0,0),
                                     weight=+1)]
    FarFields = mpa.Near2FarFields(sim, NearRegions ,far_x)
    ob_list = [FarFields]

    def J(alpha):
        return npa.abs(alpha[0,0,0])**2

    opt = mpa.OptimizationProblem(
        simulation=sim,
        objective_functions=J,
        objective_arguments=ob_list,
        design_regions=[design_region],
        fcen=fcen,
        df = 0,
        nf = 1,
        maximum_run_time=1200)

    f, dJ_du = opt([design_params])
    sim.reset_meep()

    return f, dJ_du


class TestAdjointSolver(ApproxComparisonTestCase):

    def test_adjoint_solver_cyl_n2f_fields(self):
        print("*** TESTING CYLINDRICAL Near2Far ADJOINT FEATURES ***")
        adjsol_obj, adjsol_grad = adjoint_solver(p)

        ## compute unperturbed S12
        S12_unperturbed = forward_simulation(p)

        ## compare objective results
        print("|Er|^2 -- adjoint solver: {}, traditional simulation: {}".format(adjsol_obj,S12_unperturbed))
        self.assertClose(adjsol_obj,S12_unperturbed,epsilon=1e-3)

        ## compute perturbed S12
        S12_perturbed = forward_simulation(p+dp)

        ## compare gradients
        if adjsol_grad.ndim < 2:
            adjsol_grad = np.expand_dims(adjsol_grad,axis=1)
        adj_scale = (dp[None,:]@adjsol_grad).flatten()
        fd_grad = S12_perturbed-S12_unperturbed
        print("Directional derivative -- adjoint solver: {}, FD: {}".format(adj_scale,fd_grad))
        tol = 0.1 if mp.is_single_precision() else 0.01
        self.assertClose(adj_scale,fd_grad,epsilon=tol)




if __name__ == '__main__':
    unittest.main()
