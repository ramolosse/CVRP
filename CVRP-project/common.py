# Fonctions communes : parsing, calcul de distances, validation des solutions (À implémenter ultérieurement)
# Fonctions communes pour les instances CVRP au format CVRPLIB/TSPLIB.

from __future__ import annotations

from pathlib import Path
from typing import Any

import vrplib


def parse_vrp(source: str | Path) -> dict[str, Any]:
    """Lit un fichier .vrp avec vrplib et retourne nom, dimension, capacité, coordonnées,
    demandes, dépôt et nombre de véhicules (quand le nom le précise).

    Les identifiants de nœuds sont conservés tels qu'écrits dans le fichier.
    """
    path = Path(source)
    raw = vrplib.read_instance(path, instance_format="vrplib", compute_edge_weights=True)
    # vrplib transforme les tableaux de nœuds en tableaux indexés à partir de 0.
    # L'algorithme expose, lui, les identifiants classiques du fichier (à partir de 1).
    dimension = int(raw.get("dimension", len(raw["demand"])))
    ids = list(range(1, dimension + 1))
    coords_array = raw.get("node_coord")
    coords = ({node: tuple(map(float, coords_array[node - 1])) for node in ids}
              if coords_array is not None else {})
    demands = {node: int(raw["demand"][node - 1]) for node in ids}
    depot = int(raw.get("depot", [0])[0]) + 1
    name = str(raw.get("name", path.stem))
    vehicle_count = raw.get("vehicles")
    if vehicle_count is None:
        import re
        match = re.search(r"-k(\d+)", name, re.IGNORECASE) or re.search(r"-k(\d+)", path.stem, re.IGNORECASE)
        vehicle_count = int(match.group(1)) if match else None
    weights = raw.get("edge_weight")
    return {
        "name": name,
        "dimension": dimension,
        "capacity": int(raw["capacity"]),
        "vehicles": int(vehicle_count) if vehicle_count is not None else None,
        "coordinates": coords,
        "demands": demands,
        "depot": depot,
        "edge_weight": weights,
    }


def distance(a: tuple[float, float], b: tuple[float, float]) -> int:
    """Distance EUC_2D TSPLIB (arrondi à l'entier le plus proche)."""
    return int(math.hypot(a[0] - b[0], a[1] - b[1]) + 0.5)


def distance_matrix(instance: dict[str, Any]) -> dict[tuple[int, int], int]:
    if instance.get("edge_weight") is not None:
        weights = instance["edge_weight"]
        return {(i, j): int(weights[i - 1, j - 1])
                for i in instance["demands"] for j in instance["demands"]}
    coords = instance["coordinates"]
    return {(i, j): distance(coords[i], coords[j]) for i in coords for j in coords}


def route_cost(route: list[int], depot: int, distances: dict[tuple[int, int], int]) -> int:
    if not route:
        return 0
    path = [depot, *route, depot]
    return sum(distances[a, b] for a, b in zip(path, path[1:]))


def solution_cost(routes: list[list[int]], depot: int, distances: dict[tuple[int, int], int]) -> int:
    return sum(route_cost(route, depot, distances) for route in routes)


def validate_solution(routes: list[list[int]], instance: dict[str, Any]) -> bool:
    clients = set(instance["demands"]) - {instance["depot"]}
    visited = [client for route in routes for client in route]
    return (
        set(visited) == clients
        and len(visited) == len(clients)
        and (instance["vehicles"] is None or len(routes) == instance["vehicles"])
        and all(sum(instance["demands"][c] for c in route) <= instance["capacity"] for route in routes)
    )
