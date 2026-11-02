"""Fonctions communes du projet CVRP.
# Fonctions communes : parsing, calcul de distances, validation des solutions (À implémenter ultérieurement)
# Fonctions communes pour les instances CVRP au format CVRPLIB/TSPLIB.

Ce module est partagé par toutes les méthodes de résolution (PLNE, Hill Climbing,
algorithme génétique, recherche tabou). Il fixe une représentation commune :

* les sommets sont numérotés de 0 à n et le dépôt est toujours le sommet 0 ;
* une solution est une liste de tournées ; chaque tournée est la liste des
  clients visités dans l'ordre, SANS le dépôt. Exemple : [[3, 1, 2], [4, 5]]
  signifie 0 -> 3 -> 1 -> 2 -> 0 puis 0 -> 4 -> 5 -> 0.
  C'est aussi le format des fichiers .sol lus par vrplib.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import vrplib

DEPOT = 0


@dataclass
class Instance:
    """Données d'une instance CVRP."""

    name: str
    distances: np.ndarray  # matrice (n+1) x (n+1) des coûts c_ij
    demands: np.ndarray  # demandes q_i, avec demands[0] = 0 (dépôt)
    capacity: int  # capacité Q identique pour tous les véhicules
    n_vehicles: int  # nombre m de véhicules disponibles (borne supérieure)
    coords: np.ndarray | None = None  # coordonnées (utiles pour les graphiques)
    best_known: float | None = None  # coût de référence (fichier .sol)

    @property
    def n_customers(self) -> int:
        return len(self.demands) - 1

    @property
    def customers(self) -> range:
        return range(1, self.n_customers + 1)

    def __repr__(self) -> str:
        return (
            f"Instance({self.name!r}, clients={self.n_customers}, "
            f"Q={self.capacity}, m={self.n_vehicles}, best_known={self.best_known})"
        )


# --------------------------------------------------------------------------
# Chargement des données
# --------------------------------------------------------------------------


def _vehicles_from_text(name: str, comment: str) -> int | None:
    """Lit le nombre de camions dans le nom (A-n32-k5) ou le commentaire."""
    match = re.search(r"-k(\d+)", name) or re.search(r"trucks:\s*(\d+)", comment)
    return int(match.group(1)) if match else None


def load_instance(
    path: str | Path,
    n_vehicles: int | None = None,
    round_distances: bool = True,
) -> Instance:
    """Charge une instance .vrp avec vrplib.

    Les distances EUC_2D sont arrondies à l'entier le plus proche, comme dans
    CVRPLIB : c'est cette convention qui donne les coûts des fichiers .sol.
    Si `n_vehicles` n'est pas donné, il est lu dans le nom (« -k5 ») ou le
    commentaire de l'instance ; à défaut, la flotte n'est pas limitée.
    """
    path = Path(path)
    data = vrplib.read_instance(path)

    distances = np.asarray(data["edge_weight"], dtype=float)
    if round_distances and data.get("edge_weight_type") == "EUC_2D":
        distances = np.floor(distances + 0.5)
    demands = np.asarray(data["demand"], dtype=int)
    coords = data.get("node_coord")
    coords = None if coords is None else np.asarray(coords, dtype=float)

    # On place le dépôt en position 0 s'il ne l'est pas déjà.
    depot = int(np.atleast_1d(data.get("depot", [0]))[0])
    if depot != DEPOT:
        order = [depot] + [i for i in range(len(demands)) if i != depot]
        distances = distances[np.ix_(order, order)]
        demands = demands[order]
        coords = None if coords is None else coords[order]

    n_customers = len(demands) - 1
    name = str(data.get("name", path.stem))
    if n_vehicles is None:
        n_vehicles = _vehicles_from_text(name, str(data.get("comment", "")))
    if n_vehicles is None:
        n_vehicles = n_customers

    solution_path = path.with_suffix(".sol")
    best_known = None
    if solution_path.exists():
        best_known = float(vrplib.read_solution(solution_path)["cost"])

    return Instance(
        name=name,
        distances=distances,
        demands=demands,
        capacity=int(data["capacity"]),
        n_vehicles=int(n_vehicles),
        coords=coords,
        best_known=best_known,
    )


def load_solution(path: str | Path) -> list[list[int]]:
    """Lit les tournées d'un fichier .sol (même numérotation que load_instance)."""
    return [list(route) for route in vrplib.read_solution(path)["routes"]]


def random_instance(
    n_customers: int,
    capacity: int = 100,
    demand_range: tuple[int, int] = (5, 30),
    n_vehicles: int | None = None,
    grid_size: int = 100,
    seed: int | None = None,
) -> Instance:
    """Génère une instance aléatoire : clients uniformes, dépôt au centre."""
    rng = np.random.default_rng(seed)
    coords = rng.integers(0, grid_size + 1, size=(n_customers + 1, 2)).astype(float)
    coords[DEPOT] = grid_size / 2
    demands = rng.integers(demand_range[0], demand_range[1] + 1, size=n_customers + 1)
    demands[DEPOT] = 0
    diff = coords[:, None, :] - coords[None, :, :]
    distances = np.floor(np.sqrt((diff**2).sum(axis=2)) + 0.5)
    return Instance(
        name=f"random-n{n_customers}-s{seed}",
        distances=distances,
        demands=demands,
        capacity=capacity,
        n_vehicles=n_vehicles or n_customers,
        coords=coords,
    )


def sub_instance(instance: Instance, n_customers: int) -> Instance:
    """Garde le dépôt et les `n_customers` premiers clients d'une instance.

    Pratique pour étudier l'évolution du temps de calcul avec la taille.
    """
    keep = list(range(n_customers + 1))
    coords = None if instance.coords is None else instance.coords[keep]
    return Instance(
        name=f"{instance.name}[:{n_customers}]",
        distances=instance.distances[np.ix_(keep, keep)],
        demands=instance.demands[keep],
        capacity=instance.capacity,
        n_vehicles=min(instance.n_vehicles, n_customers),
        coords=coords,
    )


# --------------------------------------------------------------------------
# Évaluation et validation d'une solution
# --------------------------------------------------------------------------


def route_cost(instance: Instance, route: list[int]) -> float:
    """Coût d'une tournée 0 -> route[0] -> ... -> route[-1] -> 0."""
    if not route:
        return 0.0
    d = instance.distances
    path = [DEPOT, *route, DEPOT]
    return float(sum(d[a, b] for a, b in zip(path, path[1:])))


def solution_cost(instance: Instance, routes: list[list[int]]) -> float:
    """Coût total (somme des coûts des tournées)."""
    return sum(route_cost(instance, route) for route in routes)


def route_load(instance: Instance, route: list[int]) -> int:
    return int(sum(instance.demands[c] for c in route))


def check_solution(instance: Instance, routes: list[list[int]]) -> list[str]:
    """Liste les contraintes violées par une solution (liste vide = réalisable).

    Vérifie : clients valides, chaque client visité exactement une fois,
    capacité de chaque véhicule, nombre de véhicules utilisés. Le départ et le
    retour au dépôt sont garantis par la représentation choisie.
    """
    errors = []
    used = [route for route in routes if route]
    if len(used) > instance.n_vehicles:
        errors.append(f"{len(used)} véhicules utilisés > {instance.n_vehicles} disponibles")

    seen: dict[int, int] = {}
    for k, route in enumerate(used):
        for c in route:
            if c not in instance.customers:
                errors.append(f"tournée {k} : sommet {c} n'est pas un client")
            seen[c] = seen.get(c, 0) + 1
        load = route_load(instance, [c for c in route if c in instance.customers])
        if load > instance.capacity:
            errors.append(f"tournée {k} : charge {load} > capacité {instance.capacity}")

    missing = [c for c in instance.customers if c not in seen]
    duplicated = [c for c, count in seen.items() if count > 1]
    if missing:
        errors.append(f"clients non desservis : {missing}")
    if duplicated:
        errors.append(f"clients desservis plusieurs fois : {duplicated}")
    return errors


def is_feasible(instance: Instance, routes: list[list[int]]) -> bool:
    return not check_solution(instance, routes)


def gap(cost: float, reference: float) -> float:
    """Écart relatif en % : 100 * (coût - référence) / référence."""
    return 100.0 * (cost - reference) / reference


def min_vehicles(instance: Instance) -> int:
    """Borne inférieure triviale sur le nombre de véhicules : ceil(somme q / Q)."""
    return math.ceil(instance.demands.sum() / instance.capacity)


# --------------------------------------------------------------------------
# Visualisation
# --------------------------------------------------------------------------


def plot_solution(instance: Instance, routes: list[list[int]], ax=None, title: str | None = None):
    """Trace le dépôt, les clients et les tournées (si l'instance a des coordonnées)."""
    import matplotlib.pyplot as plt

    if instance.coords is None:
        raise ValueError("Cette instance n'a pas de coordonnées à tracer.")
    if ax is None:
        _, ax = plt.subplots(figsize=(6, 6))
    xy = instance.coords
    for k, route in enumerate(routes):
        path = xy[[DEPOT, *route, DEPOT]]
        ax.plot(path[:, 0], path[:, 1], "-o", ms=4, lw=1.5, label=f"camion {k + 1}")
    ax.scatter(*xy[DEPOT], marker="s", s=120, c="black", zorder=3, label="dépôt")
    for c in instance.customers:
        ax.annotate(str(c), xy[c], textcoords="offset points", xytext=(3, 3), fontsize=7)
    cost = solution_cost(instance, routes)
    ax.set_title(title or f"{instance.name} — coût {cost:g}")
    ax.set_aspect("equal")
    ax.legend(fontsize=7, loc="best")
    return ax

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
