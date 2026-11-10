"""Algorithme génétique mémétique pour le CVRP, compatible avec Python 3.9+.
L’instance est chargée par le code appelant puis transmise à ``solve(instance)``.
Un dépôt, une capacité homogène et des demandes positives ou nulles.
Les fenêtres de temps et les contraintes de durée ne sont pas prises en charge.

Mémétique = génétique + recherche locale. Chaque enfant est :
1. décodé par un Split optimal (programmation dynamique de Prins, flotte limitée) ;
2. amélioré par une recherche locale (relocate/or-opt, swap, 2-opt, 2-opt*) ;
3. réécrit dans le chromosome (apprentissage lamarckien : l’ordre de visite
   devient la concaténation des tournées améliorées).
Les clones (même coût qu’un individu déjà présent) sont refusés pour garder
de la diversité dans la population.
"""

# ======================== PARAMÈTRES UTILISATEUR ========================
POPULATION_SIZE = 30
MAX_GENERATIONS = 1000
MAX_TIME_SECONDS = 30.0           # Recherche seule, initialisation de la population comprise.
STAGNATION_GENERATIONS = 40       # Générations complètes consécutives sans amélioration.
IMPROVEMENT_TOLERANCE = 1e-9
CROSSOVER_PROBABILITY = 0.90
MUTATION_PROBABILITY = 0.25
LOCAL_SEARCH_PROBABILITY = 1.0    # Part des individus améliorés par recherche locale.
GRANULAR_NEIGHBORS = 15           # Plus proches clients examinés par la recherche locale.
TOURNAMENT_SIZE = 3
ELITE_SIZE = 4
RANDOM_SEED = 42
# =================================================================

import csv
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


from common import (
    DEPOT, Instance, check_solution, gap as common_gap, route_cost, route_load,
    solution_cost,
)
from algorithms.local_search import (
    SearchTimeout, build_context, check_time, local_search, optimal_split,
)


@dataclass
class Individual:
    order: List[int]
    cost: float
    routes: List[List[int]]


def validate_parameters():
    """Vérifie la cohérence des paramètres de l’algorithme génétique."""
    for name, value, minimum in [
        ("POPULATION_SIZE", POPULATION_SIZE, 2),
        ("MAX_GENERATIONS", MAX_GENERATIONS, 0),
        ("STAGNATION_GENERATIONS", STAGNATION_GENERATIONS, 1),
        ("TOURNAMENT_SIZE", TOURNAMENT_SIZE, 1),
        ("ELITE_SIZE", ELITE_SIZE, 1),
        ("GRANULAR_NEIGHBORS", GRANULAR_NEIGHBORS, 1),
    ]:
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ValueError(f"{name} must be an integer >= {minimum}.")
    if ELITE_SIZE >= POPULATION_SIZE:
        raise ValueError("ELITE_SIZE must be smaller than POPULATION_SIZE.")
    if not math.isfinite(MAX_TIME_SECONDS) or MAX_TIME_SECONDS <= 0:
        raise ValueError("MAX_TIME_SECONDS must be finite and positive.")
    if not math.isfinite(IMPROVEMENT_TOLERANCE) or IMPROVEMENT_TOLERANCE < 0:
        raise ValueError("IMPROVEMENT_TOLERANCE must be finite and nonnegative.")
    probabilities = (CROSSOVER_PROBABILITY, MUTATION_PROBABILITY, LOCAL_SEARCH_PROBABILITY)
    if not all(0 <= p <= 1 for p in probabilities):
        raise ValueError("Operator probabilities must be in [0, 1].")




# ==================== INITIALISATION ET ÉVALUATION ====================

@dataclass
class SearchState:
    best: Optional[Individual] = None
    completed_generations: int = 0
    stagnant_generations: int = 0
    evaluations: int = 0
    local_search_calls: int = 0
    started: float = field(default_factory=time.perf_counter)
    history: List[dict] = field(default_factory=list)


def calculate_route_cost(route, ctx):
    """Calcule la distance d’une route, départ et retour au dépôt compris."""
    d = ctx.distances
    total, previous = 0.0, DEPOT
    for customer in route:
        total += d[previous][customer]
        previous = customer
    return float(total + d[previous][DEPOT])


def evaluate_individual(order, ctx, rng, deadline, state):
    """Décode, améliore puis évalue un ordre de visite (coût à minimiser).

    Un Split irréalisable (trop de véhicules) reçoit un coût infini. Après la
    recherche locale, le chromosome est remplacé par la concaténation des
    tournées améliorées : l’amélioration est transmise aux générations suivantes.
    """
    check_time(deadline)
    routes = optimal_split(order, ctx, deadline)
    if routes is None:
        return Individual(list(order), math.inf, [])
    if rng.random() < LOCAL_SEARCH_PROBABILITY:
        routes = local_search(routes, ctx, rng, deadline)
        state.local_search_calls += 1
        order = [customer for route in routes for customer in route]
    cost = sum(calculate_route_cost(route, ctx) for route in routes)
    return Individual(list(order), cost, routes)


def create_initial_order(problem, rng, deadline, nearest_neighbor=False):
    """Crée une permutation aléatoire ou une permutation par plus proche voisin."""
    order = list(problem.customers)
    if nearest_neighbor:
        order, remaining, previous = [], set(order), DEPOT
        while remaining:
            check_time(deadline)
            customer = min(remaining, key=lambda x: (problem.distances[previous, x], x))
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


def cost_key(individual):
    """Clé de détection des clones : deux individus de même coût sont jugés identiques."""
    return round(individual.cost, 6) if math.isfinite(individual.cost) else math.inf


def initialize_population(problem, ctx, rng, deadline, state):
    """Crée et évalue la population initiale, avec un premier ordre par plus proche voisin."""
    population, seen = [], set()
    attempts, max_attempts = 0, 3 * POPULATION_SIZE
    while len(population) < POPULATION_SIZE:
        check_time(deadline)
        order = create_initial_order(problem, rng, deadline, nearest_neighbor=(attempts == 0))
        individual = evaluate_individual(order, ctx, rng, deadline, state)
        update_best_solution(individual, state)
        attempts += 1
        if cost_key(individual) in seen and attempts <= max_attempts:
            continue
        seen.add(cost_key(individual))
        population.append(individual)
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


def create_next_generation(population, ctx, rng, deadline, state):
    """Conserve les élites et complète la population avec des enfants améliorés.

    Un enfant de même coût qu’un individu déjà retenu est refusé (clone), sauf
    si trop de tentatives ont échoué. Chaque amélioration est mémorisée avant
    de poursuivre : elle reste disponible si le temps expire en cours de génération.
    """
    next_population = select_elites(population)
    seen = {cost_key(individual) for individual in next_population}
    attempts, max_attempts = 0, 3 * POPULATION_SIZE
    while len(next_population) < POPULATION_SIZE:
        check_time(deadline)
        parent_a, parent_b = select_parents(population, rng)
        for order in create_offspring_orders(parent_a, parent_b, rng):
            if len(next_population) >= POPULATION_SIZE:
                break
            individual = evaluate_individual(order, ctx, rng, deadline, state)
            update_best_solution(individual, state)
            attempts += 1
            if cost_key(individual) in seen and attempts <= max_attempts:
                continue
            seen.add(cost_key(individual))
            next_population.append(individual)
    return next_population


def record_history(state):
    """Enregistre le meilleur coût après l’initialisation ou une génération complète."""
    state.history.append({"generation": state.completed_generations,
                          "seconds": time.perf_counter() - state.started,
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
    """Coordonne les étapes de l’algorithme mémétique (Split optimal + recherche locale)."""
    validate_parameters()
    rng = random.Random(RANDOM_SEED)
    started = time.perf_counter()
    deadline = started + MAX_TIME_SECONDS
    state = SearchState(started=started)
    try:
        ctx = build_context(problem, GRANULAR_NEIGHBORS)
        population = initialize_population(problem, ctx, rng, deadline, state)
        record_history(state)
        while True:
            reason = check_termination_conditions(state, deadline)
            if reason is not None:
                break
            previous_best = math.inf if state.best is None else state.best.cost
            population = create_next_generation(population, ctx, rng, deadline, state)
            update_generation_statistics(state, previous_best)
    except SearchTimeout:
        reason = "max_time"
    return state.best, {
        "stop_reason": reason,
        "completed_generations": state.completed_generations,
        "stagnant_generations": state.stagnant_generations,
        "evaluations": state.evaluations,
        "local_search_calls": state.local_search_calls,
        "search_seconds": time.perf_counter() - started,
        "history": state.history,
    }


def validate_solution(best, problem):
    """Valide la solution avec les fonctions communes du projet."""
    errors = check_solution(problem, best.routes)
    if errors:
        raise RuntimeError("Invalid solution: " + "; ".join(errors))
    total = solution_cost(problem, best.routes)
    if not math.isclose(total, best.cost, rel_tol=1e-9, abs_tol=1e-7):
        raise RuntimeError("Objective mismatch.")




def calculate_gap(best_cost, reference_cost):
    """Calcule le Gap en pourcentage ; renvoie None si le ratio est indéfini."""
    if best_cost is None or reference_cost is None or reference_cost == 0:
        return None
    return common_gap(best_cost, reference_cost)


def write_and_print_result(best, stats, problem, reference_cost, output_path):
    """Enregistre les résultats au format CSV, puis affiche le bilan et les routes."""
    gap = calculate_gap(None if best is None else best.cost, reference_cost)
    parameters = {key: value for key, value in globals().items() if key.isupper()}
    result = {
        "instance": problem.name,
        "status": "feasible" if best is not None else "no_feasible_solution_found",
        "best_cost": None if best is None else best.cost,
        "reference_cost": reference_cost,
        "gap_percent": gap,
        "vehicle_limit": problem.n_vehicles,
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
            closed = [DEPOT] + route + [DEPOT]
            result["routes"].append({
                "vehicle": index,
                "nodes": [x + 1 for x in closed],
                "load": float(route_load(problem, route)),
                "distance": float(route_cost(problem, route)),
            })
    output = Path(output_path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Un tableau rectangulaire unique regroupe bilan, routes, historique et paramètres.
    fields = ["record_type", "instance", "status", "best_cost", "reference_cost",
              "gap_percent", "vehicle_limit", "vehicles_used", "capacity",
              "stop_reason", "completed_generations", "stagnant_generations",
              "evaluations", "local_search_calls", "search_seconds", "vehicle",
              "nodes", "load", "distance", "generation", "parameter", "value"]
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
    print(f"Reference cost: {reference_cost if reference_cost is not None else 'N/A'}")
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
