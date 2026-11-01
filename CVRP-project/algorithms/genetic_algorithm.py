"""Algorithme génétique pour le CVRP, compatible avec Python 3.9+.
Installation : pip install numpy vrplib
Modifier les paramètres ci-dessous, puis lancer python cvrp_genetic_algorithm.py.
Un dépôt, une capacité homogène et des demandes positives ou nulles.
Les fenêtres de temps et les contraintes de durée ne sont pas prises en charge.
Le décodage utilise un Split glouton séquentiel, sans programmation dynamique.
Le coût du fichier .sol sert de référence ; son optimalité n’est pas démontrée ici.
"""

# ======================== PARAMÈTRES UTILISATEUR ========================
INSTANCE_PATH = "../data/A-n60-k9.vrp"
SOLUTION_PATH = "../data/A-n60-k9.sol"
OUTPUT_PATH = "../results/cvrp_ga_result2.csv"
POPULATION_SIZE = 120
MAX_GENERATIONS = 1000
MAX_TIME_SECONDS = 30.0           # Recherche seule, initialisation de la population comprise.
STAGNATION_GENERATIONS = 150      # Générations complètes consécutives sans amélioration.
IMPROVEMENT_TOLERANCE = 1e-9
CROSSOVER_PROBABILITY = 0.90
MUTATION_PROBABILITY = 0.25
TOURNAMENT_SIZE = 3
ELITE_SIZE = 4
RANDOM_SEED = 42
MAX_VEHICLES = None              # None : champ VEHICLES, sinon flotte non limitée.
# Le suffixe '-k' du nom de fichier ne définit pas automatiquement la flotte.
ROUND_EUC_2D = True              # Convention CVRPLIB : floor(distance + 0.5).
# Choisir False si l’objectif utilise les distances euclidiennes non arrondies.
# =================================================================

import csv
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import vrplib


@dataclass
class Problem:
    name: str
    distance: np.ndarray
    demand: np.ndarray
    capacity: float
    depot: int
    customers: List[int]
    max_vehicles: int


@dataclass
class Individual:
    order: List[int]
    cost: float
    routes: List[List[int]]


class SearchTimeout(Exception):
    pass


def check_time(deadline):
    """Vérifie la limite de temps, y compris pendant le décodage des routes."""
    if time.perf_counter() >= deadline:
        raise SearchTimeout


def validate_parameters():
    """Vérifie la cohérence des paramètres de l’algorithme génétique."""
    for name, value, minimum in [
        ("POPULATION_SIZE", POPULATION_SIZE, 2),
        ("MAX_GENERATIONS", MAX_GENERATIONS, 0),
        ("STAGNATION_GENERATIONS", STAGNATION_GENERATIONS, 1),
        ("TOURNAMENT_SIZE", TOURNAMENT_SIZE, 1),
        ("ELITE_SIZE", ELITE_SIZE, 1),
    ]:
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}.")
    if ELITE_SIZE >= POPULATION_SIZE:
        raise ValueError("ELITE_SIZE must be smaller than POPULATION_SIZE.")
    if not math.isfinite(MAX_TIME_SECONDS) or MAX_TIME_SECONDS <= 0:
        raise ValueError("MAX_TIME_SECONDS must be finite and positive.")
    if not math.isfinite(IMPROVEMENT_TOLERANCE) or IMPROVEMENT_TOLERANCE < 0:
        raise ValueError("IMPROVEMENT_TOLERANCE must be finite and nonnegative.")
    if not all(0 <= p <= 1 for p in (CROSSOVER_PROBABILITY, MUTATION_PROBABILITY)):
        raise ValueError("Operator probabilities must be in [0, 1].")


def read_problem(path):
    """Lit une instance CVRP ; vrplib utilise un indice de dépôt commençant à zéro."""
    data = vrplib.read_instance(str(path))
    if str(data.get("type", "CVRP")).upper() != "CVRP":
        raise ValueError("Only CVRP instances are supported.")
    if any(key in data for key in ("time_window", "backhaul", "pickup", "distance")):
        raise ValueError("Extra routing constraints are not supported by this solver.")
    depots = np.asarray(data["depot"], dtype=int)
    if len(depots) != 1:
        raise ValueError("Exactly one depot is required.")
    demand = np.asarray(data["demand"], dtype=float)
    distance = np.asarray(data["edge_weight"], dtype=float)
    n = len(demand)
    depot = int(depots[0])
    capacity = float(data["capacity"])
    if n < 2 or not 0 <= depot < n or distance.shape != (n, n):
        raise ValueError("Invalid dimensions or depot index.")
    if not np.all(np.isfinite(distance)) or np.any(distance < 0):
        raise ValueError("Distances must be finite and nonnegative.")
    if not np.all(np.isfinite(demand)) or np.any(demand < 0):
        raise ValueError("Demands must be finite and nonnegative.")
    if not math.isfinite(capacity) or capacity <= 0 or demand[depot] != 0:
        raise ValueError("Capacity must be positive and depot demand must be zero.")
    if np.any(demand > capacity):
        raise ValueError("A customer's demand exceeds vehicle capacity.")
    if ROUND_EUC_2D and data.get("edge_weight_type") == "EUC_2D":
        distance = np.floor(distance + 0.5)
    customers = [i for i in range(n) if i != depot]
    limit = MAX_VEHICLES if MAX_VEHICLES is not None else data.get("vehicles", n - 1)
    if isinstance(limit, bool) or int(limit) != limit or limit < 1:
        raise ValueError("The vehicle limit must be a positive integer.")
    limit = min(int(limit), n - 1)
    if demand.sum() > limit * capacity + 1e-9:
        raise ValueError("Total demand exceeds total fleet capacity.")
    return Problem(str(data.get("name", Path(path).stem)), distance, demand,
                   capacity, depot, customers, limit)


# ==================== INITIALISATION ET ÉVALUATION ====================

@dataclass
class SearchState:
    best: Optional[Individual] = None
    completed_generations: int = 0
    stagnant_generations: int = 0
    evaluations: int = 0
    history: List[dict] = field(default_factory=list)


def greedy_split(order, problem, deadline):
    """Remplit chaque véhicule dans l’ordre donné, puis ouvre la route suivante.

    Le client suivant est ajouté si sa demande tient dans la capacité restante.
    Sinon, la route est fermée et ce client commence une nouvelle route.
    Aucun réordonnancement ni recherche du découpage de distance minimale.
    None indique un dépassement du nombre de véhicules autorisé.
    """
    routes, route, load = [], [], 0.0
    for customer in order:
        check_time(deadline)
        demand = float(problem.demand[customer])
        if demand > problem.capacity + 1e-9:
            return None
        if route and load + demand > problem.capacity + 1e-9:
            routes.append(route)
            if len(routes) >= problem.max_vehicles:
                return None
            route, load = [], 0.0
        route.append(customer)
        load += demand
    if route:
        routes.append(route)
    return routes if len(routes) <= problem.max_vehicles else None


def calculate_route_cost(route, problem, deadline):
    """Calcule la distance d’une route, départ et retour au dépôt compris."""
    total, previous = 0.0, problem.depot
    for customer in route:
        check_time(deadline)
        total += problem.distance[previous, customer]
        previous = customer
    return float(total + problem.distance[previous, problem.depot])


def calculate_fitness(order, problem, deadline):
    """Évalue l’adaptation par le coût à minimiser : une valeur faible est meilleure.

    Une permutation invalide ou un Split irréalisable reçoit un coût infini.
    Les routes décodées sont retournées avec le coût pour éviter un second Split.
    """
    check_time(deadline)
    if len(order) != len(problem.customers) or set(order) != set(problem.customers):
        return math.inf, []
    routes = greedy_split(order, problem, deadline)
    if routes is None:
        return math.inf, []
    cost = sum(calculate_route_cost(route, problem, deadline) for route in routes)
    return cost, routes


def evaluate_individual(order, problem, deadline):
    """Construit un individu évalué à partir de son ordre de visite."""
    cost, routes = calculate_fitness(order, problem, deadline)
    return Individual(order[:], cost, routes)


def create_initial_order(problem, rng, deadline, nearest_neighbor=False):
    """Crée une permutation aléatoire ou une permutation par plus proche voisin."""
    order = problem.customers[:]
    if nearest_neighbor:
        order, remaining, previous = [], set(order), problem.depot
        while remaining:
            check_time(deadline)
            customer = min(remaining, key=lambda x: (problem.distance[previous, x], x))
            order.append(customer)
            remaining.remove(customer)
            previous = customer
    else:
        check_time(deadline)
        rng.shuffle(order)
    return order


def update_best_solution(individual, state):
    """Compte l’évaluation et mémorise immédiatement toute meilleure solution réalisable."""
    state.evaluations += 1
    if math.isfinite(individual.cost) and (state.best is None or individual.cost < state.best.cost):
        state.best = individual


def initialize_population(problem, rng, deadline, state):
    """Crée et évalue la population initiale, avec un premier ordre par plus proche voisin."""
    population = []
    for index in range(POPULATION_SIZE):
        check_time(deadline)
        order = create_initial_order(problem, rng, deadline, nearest_neighbor=(index == 0))
        individual = evaluate_individual(order, problem, deadline)
        population.append(individual)
        update_best_solution(individual, state)
    return population


# ==================== SÉLECTION, CROISEMENT ET MUTATION ====================

def select_parent(population, rng):
    """Sélectionne un parent par tournoi avec remise en minimisant le coût."""
    return min((rng.choice(population) for _ in range(TOURNAMENT_SIZE)),
               key=lambda individual: individual.cost)


def crossover(parent_a, parent_b, rng):
    """Effectue un croisement ordonné OX sans perdre ni dupliquer de client."""
    n = len(parent_a)
    if n < 2:
        return parent_a[:], parent_b[:]
    left, right = sorted(rng.sample(range(n + 1), 2))

    def make_child(a, b):
        """Construit un enfant en conservant un segment du premier parent."""
        child = [None] * n
        child[left:right] = a[left:right]
        kept = set(a[left:right])
        values = [b[(right + i) % n] for i in range(n)
                  if b[(right + i) % n] not in kept]
        positions = list(range(right, n)) + list(range(left))
        for position, value in zip(positions, values):
            child[position] = value
        return child

    return make_child(parent_a, parent_b), make_child(parent_b, parent_a)


def mutate(order, rng):
    """Applique une mutation par échange, inversion ou insertion."""
    child = order[:]
    if len(child) < 2:
        return child
    i, j = sorted(rng.sample(range(len(child)), 2))
    operation = rng.randrange(3)
    if operation == 0:
        child[i], child[j] = child[j], child[i]
    elif operation == 1:
        child[i:j + 1] = reversed(child[i:j + 1])
    else:
        child.insert(j, child.pop(i))
    return child


def select_elites(population):
    """Conserve les meilleurs individus, qui ne sont jamais modifiés sur place."""
    return sorted(population, key=lambda individual: individual.cost)[:ELITE_SIZE]


def select_parents(population, rng):
    """Sélectionne indépendamment deux parents par tournoi avec remise."""
    return select_parent(population, rng), select_parent(population, rng)


def create_offspring_orders(parent_a, parent_b, rng):
    """Applique les probabilités de croisement et de mutation aux deux enfants."""
    if rng.random() < CROSSOVER_PROBABILITY:
        orders = crossover(parent_a.order, parent_b.order, rng)
    else:
        orders = (parent_a.order[:], parent_b.order[:])
    return [mutate(order, rng) if rng.random() < MUTATION_PROBABILITY else order
            for order in orders]


# ==================== FORMATION DE LA NOUVELLE GÉNÉRATION ====================


def create_next_generation(population, problem, rng, deadline, state):
    """Conserve les élites et complète la population avec des enfants évalués.

    Chaque amélioration est mémorisée avant de poursuivre : elle reste disponible
    si le temps expire au milieu de cette génération.
    """
    next_population = select_elites(population)
    while len(next_population) < POPULATION_SIZE:
        check_time(deadline)
        parent_a, parent_b = select_parents(population, rng)
        for order in create_offspring_orders(parent_a, parent_b, rng):
            if len(next_population) >= POPULATION_SIZE:
                break
            check_time(deadline)
            individual = evaluate_individual(order, problem, deadline)
            next_population.append(individual)
            update_best_solution(individual, state)
    return next_population


def record_history(state):
    """Enregistre le meilleur coût après l’initialisation ou une génération complète."""
    state.history.append({"generation": state.completed_generations,
                          "best_cost": None if state.best is None else state.best.cost})


def update_generation_statistics(state, previous_best):
    """Incrémente la génération et actualise le compteur de stagnation."""
    state.completed_generations += 1
    improved = state.best is not None and state.best.cost < previous_best - IMPROVEMENT_TOLERANCE
    state.stagnant_generations = 0 if improved else state.stagnant_generations + 1
    record_history(state)


# ==================== CONDITIONS D’ARRÊT ET BOUCLE PRINCIPALE ====================


def check_termination_conditions(state, deadline):
    """Retourne la raison d’arrêt, ou None si la recherche doit continuer.

    En cas de simultanéité, priorité au temps, puis aux générations, puis à la stagnation.
    check_time assure aussi un arrêt à l’intérieur des opérations longues.
    """
    if time.perf_counter() >= deadline:
        return "max_time"
    if state.completed_generations >= MAX_GENERATIONS:
        return "max_generations"
    if state.stagnant_generations >= STAGNATION_GENERATIONS:
        return "stagnation"
    return None


def solve(problem):
    """Coordonne les étapes de l’algorithme génétique avec Split glouton."""
    validate_parameters()
    rng = random.Random(RANDOM_SEED)
    started = time.perf_counter()
    deadline = started + MAX_TIME_SECONDS
    state = SearchState()
    try:
        population = initialize_population(problem, rng, deadline, state)
        record_history(state)
        while True:
            reason = check_termination_conditions(state, deadline)
            if reason is not None:
                break
            previous_best = math.inf if state.best is None else state.best.cost
            population = create_next_generation(population, problem, rng, deadline, state)
            update_generation_statistics(state, previous_best)
    except SearchTimeout:
        reason = "max_time"
    return state.best, {
        "stop_reason": reason,
        "completed_generations": state.completed_generations,
        "stagnant_generations": state.stagnant_generations,
        "evaluations": state.evaluations,
        "search_seconds": time.perf_counter() - started,
        "history": state.history,
    }


def validate_solution(best, problem):
    """Vérifie les visites, les capacités, le nombre de véhicules et le coût total."""
    flat = [customer for route in best.routes for customer in route]
    if sorted(flat) != sorted(problem.customers):
        raise RuntimeError("Each customer must occur exactly once, without depot visits.")
    if len(best.routes) > problem.max_vehicles:
        raise RuntimeError("Vehicle limit exceeded.")
    total = 0.0
    for route in best.routes:
        if not route or sum(problem.demand[x] for x in route) > problem.capacity + 1e-9:
            raise RuntimeError("Empty or overloaded route.")
        closed = [problem.depot] + route + [problem.depot]
        total += sum(problem.distance[a, b] for a, b in zip(closed, closed[1:]))
    if not math.isclose(total, best.cost, rel_tol=1e-9, abs_tol=1e-7):
        raise RuntimeError("Objective mismatch.")


def read_reference_cost(path):
    """Lit le champ Cost du fichier .sol sans utiliser ses routes pour guider la recherche."""
    solution = vrplib.read_solution(str(path))
    if "cost" not in solution:
        raise ValueError("The .sol file must contain a Cost field.")
    try:
        cost = float(solution["cost"])
    except (TypeError, ValueError) as error:
        raise ValueError("The reference cost must be numeric.") from error
    if not math.isfinite(cost) or cost < 0:
        raise ValueError("The reference cost must be finite and nonnegative.")
    return cost


def calculate_gap(best_cost, reference_cost):
    """Calcule le Gap en pourcentage ; renvoie None si le ratio est indéfini."""
    if best_cost is None or reference_cost == 0:
        return None
    return 100.0 * (best_cost - reference_cost) / reference_cost


def write_and_print_result(best, stats, problem, reference_cost):
    """Enregistre les résultats au format CSV, puis affiche le bilan et les routes."""
    gap = calculate_gap(None if best is None else best.cost, reference_cost)
    parameters = {key: value for key, value in globals().items() if key.isupper()}
    result = {
        "instance": problem.name,
        "status": "feasible" if best is not None else "no_feasible_solution_found",
        "best_cost": None if best is None else best.cost,
        "reference_cost": reference_cost,
        "gap_percent": gap,
        "vehicle_limit": problem.max_vehicles,
        "vehicles_used": None if best is None else len(best.routes),
        "capacity": problem.capacity,
        "node_numbering": "1-based VRPLIB node IDs; depot included at both ends",
        "parameters": parameters,
        **stats,
        "routes": [],
    }
    if best is not None:
        validate_solution(best, problem)
        for index, route in enumerate(best.routes, 1):
            closed = [problem.depot] + route + [problem.depot]
            result["routes"].append({
                "vehicle": index,
                "nodes": [x + 1 for x in closed],
                "load": float(sum(problem.demand[x] for x in route)),
                "distance": float(sum(problem.distance[a, b]
                                      for a, b in zip(closed, closed[1:]))),
            })
    output = Path(OUTPUT_PATH).expanduser()
    input_paths = [Path(INSTANCE_PATH).expanduser(), Path(SOLUTION_PATH).expanduser()]
    if any(output.resolve() == path.resolve() for path in input_paths):
        raise ValueError("Output must not overwrite an input file.")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Un tableau rectangulaire unique regroupe bilan, routes, historique et paramètres.
    fields = ["record_type", "instance", "status", "best_cost", "reference_cost",
              "gap_percent", "vehicle_limit", "vehicles_used", "capacity",
              "stop_reason", "completed_generations", "stagnant_generations",
              "evaluations", "search_seconds", "vehicle", "nodes", "load",
              "distance", "generation", "parameter", "value"]
    # utf-8-sig facilite l’ouverture des accents dans Excel ; newline évite les lignes vides.
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        summary = {key: result[key] for key in fields if key in result}
        writer.writerow({"record_type": "summary", **summary})
        for route in result["routes"]:
            writer.writerow({"record_type": "route", "instance": problem.name,
                             **route, "nodes": " -> ".join(map(str, route["nodes"]))})
        for entry in stats["history"]:
            writer.writerow({"record_type": "history", "instance": problem.name,
                             **entry, "reference_cost": reference_cost,
                             "gap_percent": calculate_gap(entry["best_cost"], reference_cost)})
        for key, value in parameters.items():
            writer.writerow({"record_type": "parameter", "parameter": key, "value": value})
        writer.writerow({"record_type": "parameter", "parameter": "node_numbering",
                         "value": result["node_numbering"]})
    print(f"Instance: {problem.name}\nStatus: {result['status']}")
    print(f"Stop reason: {stats['stop_reason']}")
    print(f"Completed generations: {stats['completed_generations']}")
    print(f"Search time: {stats['search_seconds']:.3f} s")
    print(f"Reference cost (.sol): {reference_cost:.6f}")
    if gap is None:
        print("Gap: N/A (no feasible solution or zero reference cost)")
    else:
        print(f"Gap: {gap:.6f}%")
        if gap < -1e-7:
            print("Negative Gap: check the instance, fleet limit, rounding convention, "
                  "and whether the reference is proven optimal.")
    if best is None:
        print("No feasible solution found within the search budget; this does not prove infeasibility.")
    else:
        print(f"Best cost: {best.cost:.6f}\nVehicles: {len(best.routes)}")
        for route in result["routes"]:
            print(f"Route {route['vehicle']}: {' -> '.join(map(str, route['nodes']))}"
                  f" | load={route['load']:g} | distance={route['distance']:.6f}")
    print(f"Result saved to: {output.resolve()}")
    return result


def main():
    """Charge les fichiers, lance la recherche et enregistre les résultats comparatifs."""
    validate_parameters()
    problem = read_problem(Path(INSTANCE_PATH).expanduser())
    reference_cost = read_reference_cost(Path(SOLUTION_PATH).expanduser())
    best, stats = solve(problem)
    write_and_print_result(best, stats, problem, reference_cost)


if __name__ == "__main__":
    main()
