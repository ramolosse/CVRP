"""Hill climbing pour CVRP : départ Clarke-Wright puis mouvements locaux."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

try:  # fonctionne aussi bien comme module du projet que depuis un notebook
    from common import distance_matrix, parse_vrp, solution_cost, validate_solution
except ImportError:  # pragma: no cover
    from ..common import distance_matrix, parse_vrp, solution_cost, validate_solution


def _initial_solution(instance: dict[str, Any], distances: dict[tuple[int, int], int]) -> list[list[int]]:
    """Construire une solution faisable avec les économies de Clarke-Wright."""
    depot = instance["depot"]
    clients = [c for c in instance["demands"] if c != depot]
    capacity = instance["capacity"]
    k = instance["vehicles"] or len(clients)
    routes = [[c] for c in clients]
    owner = {c: i for i, c in enumerate(clients)}
    savings = sorted(
        ((distances[depot, i] + distances[depot, j] - distances[i, j], i, j)
         for p, i in enumerate(clients) for j in clients[p + 1:]), reverse=True
    )
    loads = [instance["demands"][c] for c in clients]
    for _, i, j in savings:
        ri, rj = owner[i], owner[j]
        if ri == rj or not routes[ri] or not routes[rj]:
            continue
        a, b = routes[ri], routes[rj]
        if loads[ri] + loads[rj] > capacity:
            continue
        # Fusion possible seulement aux extrémités; orientation optimisée.
        if a[-1] == i and b[0] == j:
            merged = a + b
        elif a[0] == i and b[-1] == j:
            merged = b + a
        elif a[0] == i and b[0] == j:
            merged = list(reversed(a)) + b
        elif a[-1] == i and b[-1] == j:
            merged = a + list(reversed(b))
        else:
            continue
        routes[ri] = merged
        routes[rj] = []
        loads[ri] += loads[rj]
        for c in merged:
            owner[c] = ri
    active = [r for r in routes if r]
    if len(active) > k:
        raise ValueError(f"Impossible de ramener les clients à {k} véhicules avec ces capacités.")
    return active + [[] for _ in range(k - len(active))]


def hill_climbing(
    instance: dict[str, Any] | str | Path,
    max_iterations: int = 10_000,
    first_improvement: bool = False,
) -> dict[str, Any]:
    """Résout une instance CVRP.

    Voisinages utilisés : 2-opt intra-tournée, déplacement d'un client,
    échange de deux clients entre tournées. Retourne tournées, distance et
    nombre d'itérations. Une instance peut être un dictionnaire ou un chemin .vrp.
    """
    if isinstance(instance, (str, Path)):
        instance = parse_vrp(instance)
    distances = distance_matrix(instance)
    routes = _initial_solution(instance, distances)
    depot, demands, capacity = instance["depot"], instance["demands"], instance["capacity"]
    current = solution_cost(routes, depot, distances)

    for iteration in range(1, max_iterations + 1):
        best_routes, best_cost = None, current
        # Explore les permutations intra-route et inter-routes, et garde le meilleur gain.
        for r, route in enumerate(routes):
            for i in range(len(route) - 1):
                for j in range(i + 1, len(route)):
                    candidate = deepcopy(routes)
                    candidate[r][i:j + 1] = reversed(candidate[r][i:j + 1])
                    cost = solution_cost(candidate, depot, distances)
                    if cost < best_cost:
                        best_routes, best_cost = candidate, cost
                        if first_improvement:
                            break
                if first_improvement and best_routes is not None:
                    break
            if first_improvement and best_routes is not None:
                break
        if not (first_improvement and best_routes is not None):
            for r1 in range(len(routes)):
                for r2 in range(r1 + 1, len(routes)):
                    a, b = routes[r1], routes[r2]
                    load_a = sum(demands[c] for c in a)
                    load_b = sum(demands[c] for c in b)
                    for i, client in enumerate(a):
                        for j, other in enumerate(b):
                            if load_a - demands[client] + demands[other] > capacity:
                                continue
                            if load_b - demands[other] + demands[client] > capacity:
                                continue
                            candidate = deepcopy(routes)
                            candidate[r1][i], candidate[r2][j] = other, client
                            cost = solution_cost(candidate, depot, distances)
                            if cost < best_cost:
                                best_routes, best_cost = candidate, cost
                                if first_improvement:
                                    break
                        if first_improvement and best_routes is not None:
                            break
                    if first_improvement and best_routes is not None:
                        break
                    # Déplacer client depuis r1 vers r2 (réciproque examiné au tour suivant).
                    for i, client in enumerate(a):
                        if load_b + demands[client] > capacity:
                            continue
                        for pos in range(len(b) + 1):
                            candidate = deepcopy(routes)
                            candidate[r1].pop(i)
                            candidate[r2].insert(pos, client)
                            cost = solution_cost(candidate, depot, distances)
                            if cost < best_cost:
                                best_routes, best_cost = candidate, cost
                                if first_improvement:
                                    break
                        if first_improvement and best_routes is not None:
                            break
                    if first_improvement and best_routes is not None:
                        break
                if first_improvement and best_routes is not None:
                    break
        if best_routes is None:
            break
        routes, current = best_routes, best_cost

    if not validate_solution(routes, instance):
        raise RuntimeError("La solution calculée ne respecte pas les contraintes CVRP.")
    return {"routes": routes, "cost": current, "iterations": iteration if max_iterations else 0,
            "name": instance.get("name", "instance")}


run_hill_climbing = hill_climbing
