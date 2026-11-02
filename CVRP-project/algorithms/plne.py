"""Résolution exacte du CVRP : PLNE résolu par Branch and Bound.

Contenu du module
-----------------
1. Construction du PLNE, au choix :
   - ``"two_index"`` (par défaut) : un modèle compact sans indice de véhicule
     (variables x_ij, u_i). Il n'a pas la symétrie entre camions, donc l'arbre
     de recherche est beaucoup plus petit ;
   - ``"vehicle_index"`` : le modèle du Livrable 1 (variables x_ijk, y_ik, z_k,
     u_ik), avec la contrainte de charge corrigée (voir build_vehicle_index_model).
2. Notre algorithme de Branch and Bound :
   - borne inférieure : relaxation linéaire du nœud, résolue par HiGHS ;
   - borne supérieure : meilleure solution entière connue, initialisée par
     l'heuristique de Clarke & Wright ;
   - séparation : sur la variable binaire la plus fractionnaire (x = 0 / x = 1) ;
   - élagage : relaxation infaisable, ou borne >= meilleure solution ;
   - exploration : meilleur d'abord (par défaut) ou en profondeur d'abord ;
   - option ``cuts=True`` : ajout de coupes de capacité arrondies qui renforcent
     la borne inférieure (on parle alors de « Branch and Cut »).
3. Une résolution de référence par PuLP/CBC sur exactement le même modèle,
   pour valider les résultats du Branch and Bound.

Utilisation rapide
------------------
>>> from common import load_instance
>>> from algorithms.plne import solve
>>> result = solve(load_instance("data/E-n13-k4.vrp"), time_limit=60)
>>> result.cost, result.status, result.routes
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field

import highspy
import numpy as np

from common import DEPOT, Instance, is_feasible, min_vehicles, route_cost, solution_cost

INT_TOL = 1e-6  # une valeur à moins de 1e-6 d'un entier est considérée entière
FORMULATIONS = ("two_index", "vehicle_index")


# ==========================================================================
# 1. Écriture du PLNE
# ==========================================================================


class LinearModel:
    """PLNE écrit contrainte par contrainte.

    Chaque variable a une clé lisible, par exemple ("x", i, j) ou ("y", i, k).
    Une contrainte est un dictionnaire {indice de variable: coefficient},
    un sens ("<=", ">=", "==") et un second membre.
    """

    def __init__(self, name: str):
        self.name = name
        self.keys: list[tuple] = []
        self.index: dict[tuple, int] = {}
        self.cost: list[float] = []
        self.lower: list[float] = []
        self.upper: list[float] = []
        self.integer: list[bool] = []
        self.rows: list[tuple[dict[int, float], str, float]] = []
        # arcs[i, j] = variables qui valent 1 quand un camion va de i à j
        # (une seule en 2 indices, une par camion dans le modèle du Livrable 1)
        self.arcs: dict[tuple[int, int], list[int]] = {}
        self.decode = None  # fonction : valeurs des variables -> tournées

    @property
    def n_vars(self) -> int:
        return len(self.keys)

    @property
    def n_constraints(self) -> int:
        return len(self.rows)

    def add_var(self, key, cost=0.0, lower=0.0, upper=1.0, integer=True) -> int:
        idx = len(self.keys)
        self.keys.append(key)
        self.index[key] = idx
        self.cost.append(float(cost))
        self.lower.append(float(lower))
        self.upper.append(float(upper))
        self.integer.append(integer)
        return idx

    def add_arc_var(self, i: int, j: int, key, cost: float) -> int:
        idx = self.add_var(key, cost=cost)
        self.arcs.setdefault((i, j), []).append(idx)
        return idx

    def add_constraint(self, coefs: dict[int, float], sense: str, rhs: float) -> None:
        if sense not in ("<=", ">=", "=="):
            raise ValueError(f"sens inconnu : {sense}")
        self.rows.append((coefs, sense, float(rhs)))

    def to_pulp(self):
        """Même modèle écrit avec PuLP (utilisé pour la résolution de référence)."""
        import pulp

        prob = pulp.LpProblem("CVRP", pulp.LpMinimize)
        variables = []
        for i in range(self.n_vars):
            if not self.integer[i]:
                category = pulp.LpContinuous
            elif self.lower[i] == 0 and self.upper[i] == 1:
                category = pulp.LpBinary
            else:
                category = pulp.LpInteger
            variables.append(prob.add_variable(f"v{i}", self.lower[i], self.upper[i], cat=category))
        prob += pulp.lpSum(c * variables[i] for i, c in enumerate(self.cost) if c)
        for coefs, sense, rhs in self.rows:
            expr = pulp.lpSum(v * variables[i] for i, v in coefs.items())
            if sense == "<=":
                prob += expr <= rhs
            elif sense == ">=":
                prob += expr >= rhs
            else:
                prob += expr == rhs
        return prob, variables


def _routes_from_arcs(used_arcs: list[tuple[int, int]]) -> list[list[int]]:
    """Reconstruit les tournées à partir des arcs utilisés par un même camion."""
    successor = {i: j for i, j in used_arcs if i != DEPOT}
    routes = []
    for i, first in used_arcs:
        if i != DEPOT:
            continue
        route, node = [], first
        while node != DEPOT and len(route) <= len(successor):
            route.append(node)
            node = successor.get(node, DEPOT)
        routes.append(route)
    return routes


def build_two_index_model(instance: Instance) -> LinearModel:
    """Modèle compact à deux indices (formulation de Miller-Tucker-Zemlin relevée).

    Variables
        x_ij ∈ {0,1} : un véhicule va directement de i à j ;
        u_i ∈ [q_i, Q] : charge cumulée du véhicule en quittant le client i.
    Objectif
        min Σ c_ij x_ij
    Contraintes
        (1) Σ_j x_ij = 1 et Σ_j x_ji = 1          pour tout client i
        (2) ⌈Σ q_i / Q⌉ <= Σ_j x_0j <= m           (nombre de camions)
        (3) u_i - u_j + Q x_ij + (Q - q_i - q_j) x_ji <= Q - q_j   (i ≠ j clients)
            -> capacité + élimination des sous-tours (MTZ relevé, Desrochers &
               Laporte 1991 ; Kara, Laporte & Bektas 2004)
        (4) q_i + Σ_j q_j x_ji <= u_i <= Q - Σ_j q_j x_ij  et  u_i <= Q - (Q - q_i) x_0i
            -> inégalités valides qui renforcent la relaxation linéaire
    Les arcs i -> j entre clients avec q_i + q_j > Q sont supprimés (impossibles).
    """
    q, Q, d = instance.demands, instance.capacity, instance.distances
    V, C = range(instance.n_customers + 1), instance.customers
    model = LinearModel(f"{instance.name} — 2 indices")

    x = {}
    for i in V:
        for j in V:
            if i != j and not (i != DEPOT and j != DEPOT and q[i] + q[j] > Q):
                x[i, j] = model.add_arc_var(i, j, ("x", i, j), cost=d[i, j])
    u = {i: model.add_var(("u", i), lower=q[i], upper=Q, integer=False) for i in C}

    for i in C:  # (1)
        model.add_constraint({x[i, j]: 1 for j in V if (i, j) in x}, "==", 1)
        model.add_constraint({x[j, i]: 1 for j in V if (j, i) in x}, "==", 1)

    departures = {x[DEPOT, j]: 1 for j in C}  # (2)
    model.add_constraint(departures, "<=", instance.n_vehicles)
    model.add_constraint(departures, ">=", min_vehicles(instance))

    for i in C:  # (3)
        for j in C:
            if (i, j) in x:
                coefs = {u[i]: 1, u[j]: -1, x[i, j]: Q, x[j, i]: Q - q[i] - q[j]}
                model.add_constraint(coefs, "<=", Q - q[j])

    for i in C:  # (4)
        model.add_constraint({u[i]: 1, **{x[j, i]: -q[j] for j in C if (j, i) in x}}, ">=", q[i])
        model.add_constraint({u[i]: 1, **{x[i, j]: q[j] for j in C if (i, j) in x}}, "<=", Q)
        model.add_constraint({u[i]: 1, x[DEPOT, i]: Q - q[i]}, "<=", Q)

    def decode(values: np.ndarray) -> list[list[int]]:
        return _routes_from_arcs([arc for arc, idx in x.items() if values[idx] > 0.5])

    model.decode = decode
    return model


def build_vehicle_index_model(instance: Instance, original_livrable1: bool = False) -> LinearModel:
    """Modèle du Livrable 1, indexé par véhicule (contraintes A à G du notebook).

    Variables : x_ijk (arc i->j par le camion k), y_ik (client i affecté à k),
    z_k (camion k utilisé), u_ik >= 0 (charge cumulée de k chez i).

    Correction de la contrainte F. Le Livrable 1 écrit
        u_jk >= u_ik + q_j - Q (1 - x_ijk).
    Si j n'est pas dans le camion k (u_jk = 0), elle impose u_ik <= Q - q_j :
    un camion dont la charge cumulée dépasse Q - q_j devient interdit, donc un
    camion plein n'est jamais accepté et l'optimum peut être éliminé. La version
    corrigée multiplie q_j par y_jk :
        u_jk >= u_ik + q_j y_jk - Q (1 - x_ijk).
    `original_livrable1=True` reconstruit la version d'origine (pour comparer).
    """
    q, Q, d = instance.demands, instance.capacity, instance.distances
    V, C = range(instance.n_customers + 1), instance.customers
    K = range(instance.n_vehicles)
    model = LinearModel(f"{instance.name} — indexé par véhicule")

    x = {(i, j, k): model.add_arc_var(i, j, ("x", i, j, k), cost=d[i, j])
         for k in K for i in V for j in V if i != j}
    y = {(i, k): model.add_var(("y", i, k)) for k in K for i in C}
    z = {k: model.add_var(("z", k)) for k in K}
    u = {(i, k): model.add_var(("u", i, k), upper=Q, integer=False) for k in K for i in C}

    for i in C:  # A. chaque client est affecté à un seul véhicule
        model.add_constraint({y[i, k]: 1 for k in K}, "==", 1)
    for k in K:
        for i in C:  # B. un client affecté a une entrée et une sortie
            model.add_constraint({**{x[i, j, k]: 1 for j in V if j != i}, y[i, k]: -1}, "==", 0)
            model.add_constraint({**{x[j, i, k]: 1 for j in V if j != i}, y[i, k]: -1}, "==", 0)
        # C. un véhicule utilisé part du dépôt et y revient
        model.add_constraint({**{x[DEPOT, j, k]: 1 for j in C}, z[k]: -1}, "==", 0)
        model.add_constraint({**{x[i, DEPOT, k]: 1 for i in C}, z[k]: -1}, "==", 0)
        for i in C:  # D. pas de client sur un véhicule inutilisé
            model.add_constraint({y[i, k]: 1, z[k]: -1}, "<=", 0)
        # E. capacité
        model.add_constraint({**{y[i, k]: q[i] for i in C}, z[k]: -Q}, "<=", 0)
        for i in C:  # F. bornes de la charge cumulée
            model.add_constraint({u[i, k]: 1, y[i, k]: -q[i]}, ">=", 0)
            model.add_constraint({u[i, k]: 1, y[i, k]: -Q}, "<=", 0)
        for i in C:  # F. progression de la charge (élimine les sous-tours)
            for j in C:
                if i != j:
                    # corrigée : u_jk - u_ik - q_j y_jk - Q x_ijk >= -Q
                    coefs = {u[j, k]: 1, u[i, k]: -1, x[i, j, k]: -Q}
                    if original_livrable1:
                        model.add_constraint(coefs, ">=", q[j] - Q)
                    else:
                        coefs[y[j, k]] = -q[j]
                        model.add_constraint(coefs, ">=", -Q)

    def decode(values: np.ndarray) -> list[list[int]]:
        routes = []
        for k in K:
            used = [(i, j) for (i, j, kk), idx in x.items() if kk == k and values[idx] > 0.5]
            routes += _routes_from_arcs(used)
        return routes

    model.decode = decode
    return model


def build_model(instance: Instance, formulation: str = "two_index") -> LinearModel:
    if formulation == "two_index":
        return build_two_index_model(instance)
    if formulation == "vehicle_index":
        return build_vehicle_index_model(instance)
    if formulation == "vehicle_index_original":
        return build_vehicle_index_model(instance, original_livrable1=True)
    raise ValueError(f"formulation inconnue : {formulation} (choix : {FORMULATIONS})")


# ==========================================================================
# 2. Relaxation linéaire et coupes de capacité
# ==========================================================================


class LPRelaxation:
    """Relaxation linéaire du PLNE (variables entières rendues continues).

    Elle est résolue par HiGHS. Le même objet sert pour tous les nœuds de
    l'arbre : on change seulement les bornes des variables et HiGHS repart de
    la base optimale précédente (démarrage à chaud), ce qui est environ dix
    fois plus rapide qu'une résolution depuis zéro.
    """

    def __init__(self, model: LinearModel):
        starts, indices, values, row_lower, row_upper = [0], [], [], [], []
        for coefs, sense, rhs in model.rows:  # contrainte : row_lower <= a.x <= row_upper
            indices += coefs.keys()
            values += coefs.values()
            starts.append(len(indices))
            row_lower.append(-highspy.kHighsInf if sense == "<=" else rhs)
            row_upper.append(highspy.kHighsInf if sense == ">=" else rhs)

        lp = highspy.HighsLp()
        lp.num_col_ = model.n_vars
        lp.num_row_ = model.n_constraints
        lp.col_cost_ = np.array(model.cost)
        lp.col_lower_ = np.array(model.lower)
        lp.col_upper_ = np.array(model.upper)
        lp.row_lower_ = np.array(row_lower, dtype=float)
        lp.row_upper_ = np.array(row_upper, dtype=float)
        lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
        lp.a_matrix_.start_ = np.array(starts, dtype=np.int32)
        lp.a_matrix_.index_ = np.array(indices, dtype=np.int32)
        lp.a_matrix_.value_ = np.array(values, dtype=float)

        self.highs = highspy.Highs()
        self.highs.setOptionValue("output_flag", False)
        self.highs.passModel(lp)
        self.columns = np.arange(model.n_vars, dtype=np.int32)

    def solve(self, lower: np.ndarray, upper: np.ndarray):
        """Renvoie (valeur, solution), ou (None, None) si la relaxation est infaisable."""
        self.highs.changeColsBounds(len(self.columns), self.columns, lower, upper)
        self.highs.run()
        status = self.highs.getModelStatus()
        if status not in (highspy.HighsModelStatus.kOptimal, highspy.HighsModelStatus.kInfeasible):
            self.highs.clearSolver()  # rare souci numérique : on repart de zéro
            self.highs.run()
            status = self.highs.getModelStatus()
        if status == highspy.HighsModelStatus.kInfeasible:
            return None, None
        if status != highspy.HighsModelStatus.kOptimal:
            raise RuntimeError(f"HiGHS n'a pas résolu la relaxation : {status}")
        return self.highs.getInfo().objective_function_value, np.array(self.highs.getSolution().col_value)

    def add_row(self, indices: list[int], upper: float) -> None:
        """Ajoute la contrainte Σ_{v ∈ indices} x_v <= upper."""
        self.highs.addRow(-highspy.kHighsInf, upper, len(indices),
                          np.array(indices, dtype=np.int32), np.ones(len(indices)))


def separate_capacity_cuts(instance: Instance, model: LinearModel, values: np.ndarray,
                           max_cuts: int = 20, tol: float = 1e-3) -> list[list[int]]:
    """Cherche des coupes de capacité arrondies violées par la solution `values`.

    Pour un ensemble S de clients, il faut au moins r(S) = ⌈q(S) / Q⌉ camions
    pour les servir, donc au plus |S| - r(S) arcs relient deux clients de S :
        Σ_{i, j ∈ S} x_ij <= |S| - r(S).
    Toute solution entière respecte cette inégalité, mais pas forcément la
    solution fractionnaire de la relaxation : l'ajouter relève la borne.

    Heuristique gloutonne : depuis chaque client, on fait grossir S en ajoutant
    le client le plus relié à S (selon les valeurs x_ij de la relaxation) et on
    garde les ensembles S pour lesquels l'inégalité est violée.
    Renvoie au plus `max_cuts` ensembles S, les plus violés d'abord.
    """
    n, q, Q = instance.n_customers, instance.demands, instance.capacity
    flow = np.zeros((n + 1, n + 1))
    for (i, j), idx in model.arcs.items():
        flow[i, j] = values[idx].sum()
    link = (flow + flow.T)[1:, 1:]  # liaison entre deux clients (dans les deux sens)
    demand = q[1:]

    violated: dict[frozenset, float] = {}
    for seed in range(n):
        in_s = np.zeros(n, dtype=bool)
        in_s[seed] = True
        to_s = link[seed].copy()  # liaison de chaque client avec S
        inside, load = 0.0, demand[seed]  # Σ x_ij dans S, demande de S
        for size in range(2, n + 1):
            j = int(np.argmax(np.where(in_s, -1.0, to_s)))
            inside += to_s[j]
            load += demand[j]
            in_s[j] = True
            to_s += link[j]
            violation = inside - (size - math.ceil(load / Q - INT_TOL))
            if violation > tol:
                key = frozenset((np.flatnonzero(in_s) + 1).tolist())
                violated[key] = max(violated.get(key, 0.0), violation)
    best = sorted(violated.items(), key=lambda item: -item[1])[:max_cuts]
    return [sorted(s) for s, _ in best]


def _capacity_cut_row(instance: Instance, model: LinearModel, s: list[int]) -> tuple[list[int], float]:
    """Variables et second membre de la coupe Σ_{i,j ∈ S} x_ij <= |S| - r(S)."""
    indices = [idx for i in s for j in s if (i, j) in model.arcs for idx in model.arcs[i, j]]
    r = math.ceil(instance.demands[s].sum() / instance.capacity - INT_TOL)
    return indices, len(s) - r


# ==========================================================================
# 3. Borne supérieure initiale : Clarke & Wright + 2-opt
# ==========================================================================


def two_opt(instance: Instance, route: list[int]) -> list[int]:
    """Améliore une tournée en inversant des segments tant que le coût baisse."""
    best, best_cost = list(route), route_cost(instance, route)
    improved = True
    while improved:
        improved = False
        for a in range(len(best) - 1):
            for b in range(a + 1, len(best)):
                candidate = best[:a] + best[a:b + 1][::-1] + best[b + 1:]
                cost = route_cost(instance, candidate)
                if cost < best_cost - 1e-9:
                    best, best_cost, improved = candidate, cost, True
    return best


def clarke_wright(instance: Instance) -> list[list[int]]:
    """Heuristique des économies (Clarke & Wright, 1964), puis 2-opt.

    On part d'une tournée par client, puis on fusionne les tournées deux à deux
    dans l'ordre des économies s_ij = c_i0 + c_0j - c_ij décroissantes, tant que
    la capacité est respectée (et tant qu'il reste trop de camions).
    La capacité est toujours respectée, mais le nombre de tournées peut dépasser
    la flotte quand les demandes se rangent mal (ex. P-n16-k8) : le Branch and
    Bound démarre alors sans borne supérieure.
    """
    d, q, Q = instance.distances, instance.demands, instance.capacity
    C = instance.customers
    symmetric = np.allclose(d, d.T)
    routes = {c: [c] for c in C}
    route_of = {c: c for c in C}
    load = {c: int(q[c]) for c in C}
    savings = sorted(((d[i, DEPOT] + d[DEPOT, j] - d[i, j], i, j)
                      for i in C for j in C if i != j), reverse=True)
    for saving, i, j in savings:
        if saving <= 0 and len(routes) <= instance.n_vehicles:
            break
        ri, rj = route_of[i], route_of[j]
        if ri == rj or load[ri] + load[rj] > Q:
            continue
        first, second = routes[ri], routes[rj]
        # On relie la fin de la première tournée (i) au début de la seconde (j).
        if first[-1] != i:
            if not (symmetric and first[0] == i):
                continue
            first.reverse()
        if second[0] != j:
            if not (symmetric and second[-1] == j):
                continue
            second.reverse()
        routes[ri] = first + second
        load[ri] += load.pop(rj)
        del routes[rj]
        for c in second:
            route_of[c] = ri
    return [two_opt(instance, route) for route in routes.values()]


# ==========================================================================
# 4. Branch and Bound
# ==========================================================================


@dataclass
class BranchAndBoundResult:
    """Résultat d'une résolution exacte (Branch and Bound ou CBC)."""

    instance: str
    method: str
    formulation: str
    status: str  # "optimal", "time_limit", "node_limit", "infeasible"
    routes: list[list[int]]
    cost: float  # borne supérieure : coût de la meilleure solution trouvée
    lower_bound: float  # borne inférieure prouvée sur le coût optimal
    root_bound: float  # borne à la racine (après les coupes s'il y en a)
    nodes: int  # nombre de nœuds évalués
    time: float  # secondes
    root_lp_bound: float = math.nan  # relaxation linéaire seule, à la racine
    cuts: int = 0  # nombre de coupes de capacité ajoutées
    n_vars: int = 0
    n_constraints: int = 0
    history: list[tuple[float, int, float, float]] = field(default_factory=list)
    # history : (temps, nœuds, borne inférieure, borne supérieure)

    @property
    def gap(self) -> float:
        """Écart d'optimalité (%) : 100 (UB - LB) / LB.

        C'est un majorant du gap par rapport à l'optimum : 0 % = optimalité prouvée.
        """
        if not math.isfinite(self.cost) or not self.lower_bound:
            return math.inf
        return 100.0 * (self.cost - self.lower_bound) / self.lower_bound

    def summary(self) -> str:
        return (f"{self.instance} | {self.method} ({self.formulation}) | {self.status} | "
                f"coût {self.cost:g} | borne inf. {self.lower_bound:g} | gap {self.gap:.2f} % | "
                f"{self.nodes} nœuds | {self.time:.2f} s")


def _most_fractional(values: np.ndarray, integer_idx: np.ndarray) -> int | None:
    """Variable entière la plus fractionnaire (valeur la plus proche de 0,5)."""
    frac = np.abs(values[integer_idx] - np.round(values[integer_idx]))
    if frac.max() <= INT_TOL:
        return None
    return int(integer_idx[np.argmax(frac)])


def branch_and_bound(
    instance: Instance,
    formulation: str = "two_index",
    time_limit: float = 60.0,
    node_limit: int | None = None,
    initial_routes: list[list[int]] | None = None,
    strategy: str = "best_first",
    cuts: bool = True,
    root_cut_rounds: int = 50,
    node_cut_rounds: int = 2,
    verbose: bool = False,
) -> BranchAndBoundResult:
    """Résout le PLNE du CVRP par Branch and Bound.

    Paramètres
        formulation     : "two_index" (défaut) ou "vehicle_index" (Livrable 1 corrigé)
        time_limit      : temps maximal en secondes
        node_limit      : nombre maximal de nœuds évalués (None = illimité)
        initial_routes  : solution de départ (par ex. issue d'une métaheuristique) ;
                          par défaut, Clarke & Wright
        strategy        : "best_first" (nœud de plus petite borne d'abord) ou
                          "depth_first" (plongée en profondeur)
        cuts            : ajoute des coupes de capacité pour relever les bornes
                          (False = Branch and Bound pur sur la relaxation linéaire)
        root_cut_rounds : nombre maximal de tours de coupes à la racine
        node_cut_rounds : nombre maximal de tours de coupes dans les autres nœuds
    Renvoie la meilleure solution trouvée et les bornes inférieure/supérieure.
    Si le statut est "optimal", la solution est prouvée optimale.
    """
    if strategy not in ("best_first", "depth_first"):
        raise ValueError("strategy doit valoir 'best_first' ou 'depth_first'")
    start = time.perf_counter()
    model = build_model(instance, formulation)
    lp = LPRelaxation(model)
    base_lower, base_upper = np.array(model.lower), np.array(model.upper)
    integer = np.array(model.integer)
    integer_idx = np.flatnonzero(integer)
    cost = np.array(model.cost)
    # Coûts entiers sur les seules variables entières -> l'optimum est entier,
    # on peut donc arrondir toute borne inférieure à l'entier supérieur.
    integral_costs = np.allclose(cost, np.round(cost)) and not np.any(cost[~integer])

    def rounded(bound: float) -> float:
        return math.ceil(bound - INT_TOL) if integral_costs else bound

    # Borne supérieure initiale
    best_routes, best_cost = [], math.inf
    if initial_routes is None:
        initial_routes = clarke_wright(instance)
    if is_feasible(instance, initial_routes):
        best_routes = [list(r) for r in initial_routes]
        best_cost = solution_cost(instance, initial_routes)

    history = []
    nodes = n_cuts = 0
    counter = 0  # départage les nœuds de même priorité dans le tas
    heap: list[tuple] = []

    def elapsed() -> float:
        return time.perf_counter() - start

    def evaluate(fixings: tuple, cut_rounds: int):
        """Résout la relaxation d'un nœud (défini par ses variables fixées),
        en ajoutant éventuellement des coupes de capacité."""
        nonlocal nodes, n_cuts
        lower, upper = base_lower.copy(), base_upper.copy()
        for var, value in fixings:
            lower[var] = upper[var] = value
        nodes += 1
        bound, values = lp.solve(lower, upper)
        for _ in range(cut_rounds if cuts else 0):
            if bound is None or rounded(bound) >= best_cost - INT_TOL:
                break  # nœud déjà élagué
            if elapsed() > time_limit:
                break
            if _most_fractional(values, integer_idx) is None:
                break  # solution entière : rien à couper
            sets = separate_capacity_cuts(instance, model, values)
            if not sets:
                break
            for s in sets:  # les coupes sont valides partout : on les garde
                lp.add_row(*_capacity_cut_row(instance, model, s))
            n_cuts += len(sets)
            bound, values = lp.solve(lower, upper)
        return bound, values

    def push(bound: float, values: np.ndarray, fixings: tuple) -> None:
        """Traite un nœud évalué : élagage, nouvelle solution, ou mise en attente."""
        nonlocal best_cost, best_routes, counter
        if rounded(bound) >= best_cost - INT_TOL:
            return  # élagage par la borne : ce nœud ne peut pas faire mieux
        var = _most_fractional(values, integer_idx)
        if var is None:  # solution entière : nouvelle meilleure solution
            routes = model.decode(values)
            if is_feasible(instance, routes):
                best_cost, best_routes = solution_cost(instance, routes), routes
                history.append((elapsed(), nodes, current_lower_bound(bound), best_cost))
            return
        counter += 1
        key = (bound, counter) if strategy == "best_first" else (-len(fixings), bound, counter)
        heapq.heappush(heap, (key, bound, var, values[var], fixings))

    def current_lower_bound(extra: float = math.inf) -> float:
        return rounded(min([extra, best_cost, *(item[1] for item in heap)]))

    root_lp_bound, _ = lp.solve(base_lower, base_upper)  # avant toute coupe
    root_bound, root_values = evaluate((), root_cut_rounds)
    if root_bound is None:
        return BranchAndBoundResult(instance.name, "branch_and_bound", formulation, "infeasible",
                                    [], math.inf, math.inf, math.inf, nodes, elapsed(),
                                    n_vars=model.n_vars, n_constraints=model.n_constraints)
    history.append((elapsed(), nodes, rounded(root_bound), best_cost))
    push(root_bound, root_values, ())

    status = "optimal"
    last_log = 0.0
    while heap:
        if elapsed() > time_limit:
            status = "time_limit"
            break
        if node_limit is not None and nodes >= node_limit:
            status = "node_limit"
            break
        _, bound, var, value, fixings = heapq.heappop(heap)
        if rounded(bound) >= best_cost - INT_TOL:
            continue  # la borne supérieure s'est améliorée depuis la mise en attente

        # Séparation : x_var = 1 d'un côté, x_var = 0 de l'autre.
        # La branche la plus proche de la valeur fractionnaire est traitée en premier.
        for fixed in ((1.0, 0.0) if value >= 0.5 else (0.0, 1.0)):
            child = fixings + ((var, fixed),)
            child_bound, child_values = evaluate(child, node_cut_rounds)
            if child_bound is not None:  # sinon : élagage par infaisabilité
                push(max(child_bound, bound), child_values, child)

        if elapsed() - last_log > 0.5:  # suivi des bornes toutes les 0,5 s
            last_log = elapsed()
            lb = current_lower_bound(bound)
            history.append((last_log, nodes, lb, best_cost))
            if verbose and len(history) % 4 == 0:
                print(f"  {last_log:6.1f} s | {nodes:6d} nœuds | {len(heap):5d} ouverts | "
                      f"{n_cuts:4d} coupes | LB {lb:g} | UB {best_cost:g}")

    if not math.isfinite(best_cost) and status == "optimal":
        status = "infeasible"
    lower_bound = best_cost if status in ("optimal", "infeasible") else current_lower_bound()
    history.append((elapsed(), nodes, lower_bound, best_cost))
    result = BranchAndBoundResult(
        instance=instance.name, method="branch_and_bound", formulation=formulation,
        status=status, routes=best_routes, cost=best_cost, lower_bound=lower_bound,
        root_bound=rounded(root_bound), nodes=nodes, time=elapsed(),
        root_lp_bound=root_lp_bound if root_lp_bound is not None else math.inf,
        cuts=n_cuts, n_vars=model.n_vars, n_constraints=model.n_constraints, history=history,
    )
    if verbose:
        print(result.summary())
    return result


# ==========================================================================
# 5. Résolution de référence par PuLP / CBC
# ==========================================================================


def solve_with_cbc(
    instance: Instance,
    formulation: str = "two_index",
    time_limit: float = 60.0,
    verbose: bool = False,
) -> BranchAndBoundResult:
    """Résout exactement le même PLNE avec le solveur CBC (via PuLP).

    CBC utilise lui aussi un Branch and Bound, enrichi de coupes et
    d'heuristiques : il sert de référence pour valider notre implémentation.
    Avec PuLP >= 4, CBC s'installe avec l'extra : pip install "pulp[cbc]".
    """
    import pulp

    start = time.perf_counter()
    model = build_model(instance, formulation)
    prob, variables = model.to_pulp()
    stats = prob.solve(pulp.COIN_CMD(msg=verbose, timeLimit=time_limit))
    elapsed = time.perf_counter() - start
    nodes = stats.nodes or 0

    if not stats.has_solution:
        status = "infeasible" if stats.status == pulp.LpSolveStatus.Infeasible else "time_limit"
        return BranchAndBoundResult(instance.name, "cbc", formulation, status, [], math.inf,
                                    math.inf if status == "infeasible" else math.nan,
                                    math.nan, nodes, elapsed,
                                    n_vars=model.n_vars, n_constraints=model.n_constraints)
    values = np.array([v.value() or 0.0 for v in variables])
    routes = model.decode(values)
    cost = solution_cost(instance, routes)
    lower_bound = stats.best_bound if stats.best_bound is not None else math.nan
    # CBC s'arrête avec le statut GapLimit quand l'écart restant est nul.
    optimal = stats.status == pulp.LpSolveStatus.Optimal or (
        stats.status == pulp.LpSolveStatus.GapLimit and cost - lower_bound < 1 - INT_TOL)
    return BranchAndBoundResult(
        instance=instance.name, method="cbc", formulation=formulation,
        status="optimal" if optimal else "time_limit", routes=routes, cost=cost,
        lower_bound=cost if optimal else lower_bound, root_bound=math.nan, nodes=nodes,
        time=elapsed, n_vars=model.n_vars, n_constraints=model.n_constraints,
    )


# ==========================================================================
# Point d'entrée commun (utilisé par benchmark.py)
# ==========================================================================


def solve(instance: Instance, time_limit: float = 60.0, **kwargs) -> BranchAndBoundResult:
    """Interface commune : résout l'instance par Branch and Bound sur le PLNE.

    À réserver aux petites instances (quelques dizaines de clients) : le modèle
    a environ n² variables et n² contraintes, et l'arbre croît exponentiellement.
    """
    return branch_and_bound(instance, time_limit=time_limit, **kwargs)
