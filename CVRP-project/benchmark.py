"""Protocoles reproductibles de benchmark pour le projet CVRP.

Les instances VRPLIB sont des instances de référence, pas des données
opérationnelles garanties. Les fonctions renvoient des DataFrames pandas,
prêts à afficher et interpréter dans ``main.ipynb``.
"""

from __future__ import annotations

from pathlib import Path
import importlib.metadata as package_metadata
import platform

import numpy as np
import pandas as pd

import algorithms.genetic_algorithm as ga
from algorithms.plne import branch_and_bound
from common import check_solution, gap, load_instance, sub_instance

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DEFAULT_INSTANCE_NAMES = [
    "A-n32-k5", "A-n33-k5", "A-n37-k6", "A-n39-k5", "A-n45-k6",
    "A-n48-k7", "A-n55-k9", "A-n60-k9", "A-n80-k10",
    "B-n31-k5", "B-n35-k5", "B-n39-k5", "B-n45-k6", "B-n50-k7",
    "E-n13-k4", "E-n22-k4", "E-n30-k3", "E-n51-k5",
    "P-n16-k8", "P-n19-k2", "P-n20-k2", "P-n22-k8", "P-n50-k10",
]
EXPERIMENT_SEEDS = (42, 123, 456, 789, 1024)
GA_MAX_GENERATIONS = 1000
GA_POPULATION_SIZE = 30
GA_MUTATION_PROBABILITY = 0.25
GA_CROSSOVER_PROBABILITY = 0.90
GA_STAGNATION_GENERATIONS = 40
GA_TIME_LIMITS_BY_SIZE = ((35, 5.0), (55, 8.0), (float("inf"), 12.0))
GA_MULTI_SEED_TIME_LIMIT = 3.0
PLNE_GA_COMPARISON_MAX_CLIENTS = 30
PLNE_GA_COMPARISON_TIME_LIMIT = 5.0


def load_benchmark_instances(names=DEFAULT_INSTANCE_NAMES, data_dir=DATA_DIR):
    """Charge les instances VRPLIB listées, avec leurs références .sol éventuelles."""
    return [load_instance(Path(data_dir) / f"{name}.vrp") for name in names]


def software_versions():
    """Retourne les versions utiles pour documenter une expérience."""
    versions = {"python": platform.python_version()}
    for package in ("numpy", "pandas", "highspy", "pulp", "vrplib", "matplotlib"):
        try:
            versions[package] = package_metadata.version(package)
        except package_metadata.PackageNotFoundError:
            versions[package] = "non installé"
    return versions


def ga_time_limit_for_instance(instance):
    """Budget GA selon la taille, suivant le protocole du notebook."""
    return next(seconds for max_clients, seconds in GA_TIME_LIMITS_BY_SIZE
                if instance.n_customers <= max_clients)


def run_ga(instance, max_time=None, max_gen=GA_MAX_GENERATIONS, seed=42,
           pop_size=GA_POPULATION_SIZE, mut_prob=GA_MUTATION_PROBABILITY,
           cx_prob=GA_CROSSOVER_PROBABILITY, stagnation=GA_STAGNATION_GENERATIONS):
    """Exécute le GA mémétique avec paramètres explicites et renvoie une ligne de résultats."""
    params = (ga.MAX_TIME_SECONDS, ga.RANDOM_SEED, ga.MAX_GENERATIONS,
              ga.POPULATION_SIZE, ga.MUTATION_PROBABILITY,
              ga.CROSSOVER_PROBABILITY, ga.STAGNATION_GENERATIONS)
    try:
        ga.MAX_TIME_SECONDS = ga_time_limit_for_instance(instance) if max_time is None else max_time
        ga.RANDOM_SEED = seed
        ga.MAX_GENERATIONS = max_gen
        ga.POPULATION_SIZE = pop_size
        ga.MUTATION_PROBABILITY = mut_prob
        ga.CROSSOVER_PROBABILITY = cx_prob
        ga.STAGNATION_GENERATIONS = stagnation
        best, stats = ga.solve(instance)
    finally:
        (ga.MAX_TIME_SECONDS, ga.RANDOM_SEED, ga.MAX_GENERATIONS,
         ga.POPULATION_SIZE, ga.MUTATION_PROBABILITY,
         ga.CROSSOVER_PROBABILITY, ga.STAGNATION_GENERATIONS) = params
    cost = best.cost if best else float("inf")
    feasible = best is not None and not check_solution(instance, best.routes)
    reference = instance.best_known
    rel_gap = gap(cost, reference) if reference and reference > 0 and best else None
    return {
        "instance": instance.name, "n_clients": instance.n_customers,
        "n_vehicles": instance.n_vehicles, "capacity": instance.capacity,
        "best_known": reference, "ga_cost": cost,
        "gap_reference_percent": round(rel_gap, 2) if rel_gap is not None else None,
        "elapsed_seconds": round(stats["search_seconds"], 3),
        "generations": stats["completed_generations"],
        "local_search_calls": stats["local_search_calls"],
        "stop_reason": stats["stop_reason"], "feasible": feasible, "seed": seed,
    }


def run_single_seed_ga_benchmark(instances=None, seed=EXPERIMENT_SEEDS[0], **ga_kwargs):
    """Une exécution GA par instance; renvoie un DataFrame de résultats."""
    instances = load_benchmark_instances() if instances is None else instances
    return pd.DataFrame([run_ga(instance, seed=seed, **ga_kwargs) for instance in instances])


def run_multi_seed_ga_benchmark(instances=None, seeds=EXPERIMENT_SEEDS,
                                max_time=GA_MULTI_SEED_TIME_LIMIT, **ga_kwargs):
    """Répète le GA par instance et graine, avec statistiques agrégées."""
    instances = load_benchmark_instances() if instances is None else instances
    rows = [run_ga(instance, max_time=max_time, seed=seed, **ga_kwargs)
            for instance in instances for seed in seeds]
    results = pd.DataFrame(rows)
    results["gap_num"] = pd.to_numeric(results["gap_reference_percent"], errors="coerce")
    summary = results.groupby("instance").agg(
        n_clients=("n_clients", "first"), gap_mean=("gap_num", "mean"),
        gap_median=("gap_num", "median"), gap_stdev=("gap_num", "std"),
        cost_mean=("ga_cost", "mean"), cost_median=("ga_cost", "median"),
        cost_stdev=("ga_cost", "std"), time_mean_seconds=("elapsed_seconds", "mean"),
        time_median_seconds=("elapsed_seconds", "median"),
        time_stdev_seconds=("elapsed_seconds", "std"),
    ).round(2)
    return results, summary


def compare_plne_vs_ga(instances=None, max_clients=PLNE_GA_COMPARISON_MAX_CLIENTS,
                       time_limit=PLNE_GA_COMPARISON_TIME_LIMIT, seed=EXPERIMENT_SEEDS[0]):
    """Compare GA et Branch and Bound sur les petites instances, sous limite égale."""
    instances = load_benchmark_instances() if instances is None else instances
    rows = []
    for instance in instances:
        if instance.n_customers > max_clients:
            continue
        heuristic = run_ga(instance, max_time=time_limit, seed=seed)
        exact = branch_and_bound(instance, time_limit=time_limit, cuts=True)
        rows.append({
            "instance": instance.name, "n_clients": instance.n_customers,
            "time_limit_seconds_per_method": time_limit,
            "reference_cost": instance.best_known, "ga_cost": heuristic["ga_cost"],
            "ga_gap_reference_percent": heuristic["gap_reference_percent"],
            "ga_elapsed_seconds": heuristic["elapsed_seconds"],
            "plne_status": exact.status, "plne_cost": exact.cost,
            "plne_lower_bound": exact.lower_bound,
            "plne_gap_bound_percent": exact.gap,
            "plne_elapsed_seconds": round(exact.time, 3),
        })
    return pd.DataFrame(rows)


def run_scalability_benchmark(instance=None, sizes=(50, 100, 200, 300, 500),
                              max_time=3.0, seed=42):
    """Teste la faisabilité et le temps sur des préfixes d'une instance donnée."""
    instance = load_instance(DATA_DIR / "Leuven1.vrp") if instance is None else instance
    rows = []
    for size in sizes:
        scaled = sub_instance(instance, size)
        needed = int(np.ceil(scaled.demands.sum() / scaled.capacity)) + 2
        scaled.n_vehicles = max(needed, scaled.n_vehicles)
        result = run_ga(scaled, max_time=max_time, seed=seed)
        # run_ga encapsule la solution; le coût, la faisabilité, le temps et le
        # nombre de générations sont renvoyés dans sa ligne de résultats.
        rows.append({
            "n_clients": size, "n_vehicles": scaled.n_vehicles,
            "cost": result["ga_cost"], "feasible": result["feasible"],
            "elapsed_seconds": result["elapsed_seconds"],
            "generations": result["generations"],
        })
    return pd.DataFrame(rows)


def run_mutation_sensitivity(instance=None, mutation_rates=(0.05, 0.10, 0.20, 0.30, 0.40, 0.50),
                             seeds=EXPERIMENT_SEEDS, max_time=2.0):
    """Mesure les gaps et leur dispersion selon le taux de mutation."""
    instance = load_instance(DATA_DIR / "A-n33-k5.vrp") if instance is None else instance
    rows = []
    for rate in mutation_rates:
        runs = [run_ga(instance, max_time=max_time, seed=seed, mut_prob=rate) for seed in seeds]
        gaps = np.array([r["gap_reference_percent"] for r in runs], dtype=float)
        times = np.array([r["elapsed_seconds"] for r in runs], dtype=float)
        rows.append({
            "mutation_rate": rate, "gap_mean_percent": round(float(np.mean(gaps)), 2),
            "gap_std_percent": round(float(np.std(gaps)), 2),
            "gap_min_percent": round(float(np.min(gaps)), 2),
            "gap_max_percent": round(float(np.max(gaps)), 2),
            "time_mean_seconds": round(float(np.mean(times)), 2),
        })
    return pd.DataFrame(rows)
