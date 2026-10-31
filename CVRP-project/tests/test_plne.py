"""Tests du PLNE et du Branch and Bound.

Lancement depuis le dossier CVRP-project :
    python tests/test_plne.py        (ou : pytest tests)
"""

import itertools
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from algorithms.plne import (  # noqa: E402
    branch_and_bound,
    build_model,
    clarke_wright,
    solve_with_cbc,
)
from common import Instance, check_solution, load_instance, random_instance, route_cost  # noqa: E402

DATA = ROOT / "data"


def brute_force(instance: Instance) -> float:
    """Optimum par énumération : chaque ordre des clients, découpé au mieux en tournées.

    Indépendant du PLNE : sert à vérifier le Branch and Bound sur de très petites
    instances (6 clients = 720 ordres).
    """
    q, Q, m = instance.demands, instance.capacity, instance.n_vehicles
    best = math.inf
    for order in itertools.permutations(instance.customers):
        n = len(order)
        # cost[r][i] : coût minimal pour servir order[:i] avec r tournées
        cost = [[math.inf] * (n + 1) for _ in range(m + 1)]
        cost[0][0] = 0.0
        for r in range(1, m + 1):
            for i in range(n):
                if cost[r - 1][i] == math.inf:
                    continue
                load = 0
                for j in range(i + 1, n + 1):
                    load += q[order[j - 1]]
                    if load > Q:
                        break
                    value = cost[r - 1][i] + route_cost(instance, list(order[i:j]))
                    cost[r][j] = min(cost[r][j], value)
        best = min(best, min(cost[r][n] for r in range(m + 1)))
    return best


def test_check_solution_detects_errors():
    inst = random_instance(5, capacity=50, demand_range=(10, 20), seed=1)
    assert check_solution(inst, [[1, 2], [3, 4], [5]]) == []
    assert any("non desservis" in e for e in check_solution(inst, [[1, 2], [3, 4]]))
    assert any("plusieurs fois" in e for e in check_solution(inst, [[1, 2], [2, 3, 4], [5]]))
    assert any("capacité" in e for e in check_solution(inst, [[1, 2, 3, 4, 5]]))


def test_load_instance_and_known_costs():
    for name in ["E-n13-k4", "P-n16-k8", "A-n32-k5"]:
        inst = load_instance(DATA / f"{name}.vrp")
        from common import load_solution, solution_cost
        routes = load_solution(DATA / f"{name}.sol")
        assert check_solution(inst, routes) == [], name
        assert solution_cost(inst, routes) == inst.best_known, name


def test_clarke_wright_respects_capacity():
    # Clarke & Wright respecte la capacité et dessert tout le monde, mais peut
    # utiliser plus de camions que la flotte (P-n16-k8 : 9 tournées pour 8 camions).
    for path in sorted(DATA.glob("*.vrp")):
        inst = load_instance(path)
        errors = check_solution(inst, clarke_wright(inst))
        assert [e for e in errors if "véhicules" not in e] == [], path.name


def test_branch_and_bound_matches_brute_force():
    for seed in range(5):
        inst = random_instance(6, capacity=50, demand_range=(8, 25), seed=seed)
        optimum = brute_force(inst)
        for cuts in (True, False):  # Branch and Cut, puis Branch and Bound pur
            result = branch_and_bound(inst, time_limit=60, cuts=cuts)
            assert result.status == "optimal"
            assert check_solution(inst, result.routes) == []
            assert math.isclose(result.cost, optimum), (seed, cuts)


def test_branch_and_bound_matches_cbc():
    for seed in range(3):
        inst = random_instance(9, capacity=60, demand_range=(5, 25), seed=100 + seed)
        ours = branch_and_bound(inst, time_limit=60)
        cbc = solve_with_cbc(inst, time_limit=60)
        assert ours.status == cbc.status == "optimal"
        assert math.isclose(ours.cost, cbc.cost), seed


def test_depth_first_finds_same_optimum():
    inst = random_instance(8, capacity=50, demand_range=(5, 25), seed=7)
    best = branch_and_bound(inst, strategy="best_first")
    depth = branch_and_bound(inst, strategy="depth_first")
    assert best.status == depth.status == "optimal"
    assert math.isclose(best.cost, depth.cost)


def test_vehicle_index_model_matches_two_index():
    inst = random_instance(5, capacity=40, demand_range=(8, 20), n_vehicles=3, seed=3)
    two = branch_and_bound(inst, formulation="two_index")
    veh = branch_and_bound(inst, formulation="vehicle_index", time_limit=120)
    assert two.status == veh.status == "optimal"
    assert math.isclose(two.cost, veh.cost)


def test_original_livrable1_constraint_rejects_full_trucks():
    # 3 clients de demande 5, camions de capacité 10, 2 camions :
    # toute solution a un camion plein (charge 10). La contrainte F d'origine
    # impose u_ik <= Q - q_j = 5 dès qu'un client j est dans un autre camion,
    # donc le modèle d'origine n'a aucune solution ; le modèle corrigé, si.
    coords = np.array([[0, 0], [10, 0], [0, 10], [10, 10]], dtype=float)
    diff = coords[:, None] - coords[None, :]
    inst = Instance(
        name="camion-plein",
        distances=np.floor(np.sqrt((diff**2).sum(axis=2)) + 0.5),
        demands=np.array([0, 5, 5, 5]),
        capacity=10,
        n_vehicles=2,
        coords=coords,
    )
    # initial_routes=[] : pas de solution de départ (sinon Clarke & Wright, qui
    # ne vient pas du modèle, servirait de solution).
    assert branch_and_bound(inst, "vehicle_index", initial_routes=[]).status == "optimal"
    original = branch_and_bound(inst, "vehicle_index_original", initial_routes=[])
    assert original.status == "infeasible"
    assert solve_with_cbc(inst, formulation="vehicle_index_original").status == "infeasible"


def test_model_sizes():
    inst = load_instance(DATA / "E-n13-k4.vrp")
    two, veh = build_model(inst, "two_index"), build_model(inst, "vehicle_index")
    assert two.n_vars < veh.n_vars


def test_known_optimum_E_n13_k4():
    inst = load_instance(DATA / "E-n13-k4.vrp")
    for cuts in (True, False):
        result = branch_and_bound(inst, time_limit=120, cuts=cuts)
        assert result.status == "optimal"
        assert result.cost == inst.best_known == 247


def test_known_optimum_P_n16_k8():
    inst = load_instance(DATA / "P-n16-k8.vrp")
    result = branch_and_bound(inst, time_limit=120)
    assert result.status == "optimal"
    assert result.cost == inst.best_known == 450


if __name__ == "__main__":
    import time

    for name, test in list(globals().items()):
        if name.startswith("test_") and callable(test):
            start = time.perf_counter()
            test()
            print(f"OK  {name}  ({time.perf_counter() - start:.1f} s)")
    print("Tous les tests passent.")
