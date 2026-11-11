"""Briques de l'algorithme mémétique : Split optimal et recherche locale CVRP.

Les fonctions prennent un ``SearchContext`` qui met en cache, pour une
instance, la matrice de distances en listes Python (accès plus rapide qu'un
tableau numpy élément par élément), les demandes et les plus proches voisins.

Représentation : une solution est une liste de tournées sans le dépôt, comme
dans le reste du projet. Toutes les fonctions respectent la capacité et la
limite du nombre de véhicules.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import List, Optional

from common import DEPOT, Instance

EPSILON = 1e-9


class SearchTimeout(Exception):
    pass


def check_time(deadline):
    """Vérifie la limite de temps, y compris pendant le Split et la recherche locale."""
    if time.perf_counter() >= deadline:
        raise SearchTimeout


@dataclass
class SearchContext:
    """Données d'instance préparées une seule fois pour la recherche."""

    distances: List[List[float]]
    demands: List[int]
    capacity: int
    n_vehicles: int
    neighbors: List[List[int]]
    symmetric: bool


def build_context(problem: Instance, granularity: int = 15) -> SearchContext:
    """Prépare les distances, demandes et listes de voisins granulaires.

    ``granularity`` est le nombre de plus proches clients examinés pour chaque
    client par la recherche locale (voisinage granulaire de Toth et Vigo).
    """
    distances = problem.distances.tolist()
    demands = [int(q) for q in problem.demands]
    customers = list(problem.customers)
    neighbors = [[] for _ in range(len(demands))]
    for u in customers:
        others = sorted((c for c in customers if c != u),
                        key=lambda c: (distances[u][c] + distances[c][u], c))
        neighbors[u] = others[:granularity]
    symmetric = bool((problem.distances == problem.distances.T).all())
    return SearchContext(distances, demands, int(problem.capacity),
                         int(problem.n_vehicles), neighbors, symmetric)


# ============================ SPLIT OPTIMAL ============================

def optimal_split(order, ctx: SearchContext, deadline) -> Optional[List[List[int]]]:
    """Découpe un tour géant en tournées de coût total minimal (Split de Prins).

    Programmation dynamique sur un graphe auxiliaire : l'arc (i, j) représente
    la tournée qui sert les clients order[i:j]. Une première passe sans limite
    de flotte suffit si elle utilise au plus ``n_vehicles`` tournées ; sinon une
    passe par couches (nombre de tournées) impose la limite. Retourne None si
    aucun découpage ne respecte la flotte.
    """
    d, q, capacity = ctx.distances, ctx.demands, ctx.capacity
    n = len(order)
    if n == 0:
        return []
    # arcs[i] : liste des (j, coût) des tournées réalisables order[i:j].
    arcs = []
    for i in range(n):
        check_time(deadline)
        first = order[i]
        if q[first] > capacity:
            return None
        load, cost, previous = q[first], d[DEPOT][first], first
        row = [(i + 1, cost + d[first][DEPOT])]
        for j in range(i + 1, n):
            customer = order[j]
            load += q[customer]
            if load > capacity:
                break
            cost += d[previous][customer]
            previous = customer
            row.append((j + 1, cost + d[customer][DEPOT]))
        arcs.append(row)

    # Passe sans limite de flotte (cas le plus fréquent).
    best = [0.0] + [math.inf] * n
    parent = [0] * (n + 1)
    for i in range(n):
        base = best[i]
        for j, cost in arcs[i]:
            if base + cost < best[j]:
                best[j], parent[j] = base + cost, i
    routes = _routes_from_parents(order, parent)
    if len(routes) <= ctx.n_vehicles:
        return routes

    # Passe par couches : layer[k][j] = coût minimal de order[:j] en k tournées.
    previous_layer = [0.0] + [math.inf] * n
    parents_by_layer = []
    best_cost, best_layer = math.inf, None
    for k in range(1, ctx.n_vehicles + 1):
        check_time(deadline)
        layer = [math.inf] * (n + 1)
        layer_parent = [-1] * (n + 1)
        for i in range(n):
            base = previous_layer[i]
            if base == math.inf:
                continue
            for j, cost in arcs[i]:
                if base + cost < layer[j]:
                    layer[j], layer_parent[j] = base + cost, i
        parents_by_layer.append(layer_parent)
        if layer[n] < best_cost:
            best_cost, best_layer = layer[n], k
        previous_layer = layer
    if best_layer is None:
        return None
    routes, j = [], n
    for k in range(best_layer, 0, -1):
        i = parents_by_layer[k - 1][j]
        routes.append(list(order[i:j]))
        j = i
    routes.reverse()
    return routes


def _routes_from_parents(order, parent):
    """Reconstruit les tournées depuis les prédécesseurs du plus court chemin."""
    routes, j = [], len(order)
    while j > 0:
        i = parent[j]
        routes.append(list(order[i:j]))
        j = i
    routes.reverse()
    return routes


# ============================ RECHERCHE LOCALE ============================

def local_search(routes, ctx: SearchContext, rng, deadline) -> List[List[int]]:
    """Améliore une solution réalisable jusqu'à un optimum local.

    Voisinages (premier mouvement améliorant, restreints aux plus proches
    voisins) :

    * relocate / or-opt : déplacer 1, 2 ou 3 clients consécutifs avant ou
      après un client voisin, éventuellement en inversant le segment ;
    * swap : échanger deux clients ;
    * 2-opt : inverser une portion de tournée ;
    * 2-opt* : échanger les fins (ou débuts) de deux tournées.

    Chaque mouvement est évalué en O(1) par différence de coût. La capacité est
    vérifiée avant d'appliquer un mouvement ; aucun mouvement ne crée de
    tournée, donc la limite de flotte reste respectée. Si la limite de temps
    est atteinte, la solution améliorée jusque-là est retournée.
    """
    d, q, capacity, symmetric = ctx.distances, ctx.demands, ctx.capacity, ctx.symmetric
    routes = [list(route) for route in routes if route]
    size = len(q)
    route_of = [-1] * size
    position = [0] * size
    prefix = [0] * size          # charge cumulée de la tournée jusqu'au client inclus
    loads = [0] * len(routes)
    modified = [0] * len(routes)  # numéro du dernier mouvement ayant touché la tournée
    tested = [-1] * size          # numéro du mouvement lors du dernier test du client

    def rebuild(r):
        acc = 0
        for index, customer in enumerate(routes[r]):
            route_of[customer] = r
            position[customer] = index
            acc += q[customer]
            prefix[customer] = acc
        loads[r] = acc

    for r in range(len(routes)):
        rebuild(r)

    def pred(c):
        p = position[c]
        return routes[route_of[c]][p - 1] if p > 0 else DEPOT

    def succ(c):
        route = routes[route_of[c]]
        p = position[c] + 1
        return route[p] if p < len(route) else DEPOT

    def try_relocate(u, v):
        """Déplace le segment qui commence en u avant ou après v."""
        ru, rv = route_of[u], route_of[v]
        route_u = routes[ru]
        p = position[u]
        a = pred(u)
        for length in (1, 2, 3):
            if p + length > len(route_u):
                return False
            segment_last = route_u[p + length - 1]
            if ru == rv and p <= position[v] < p + length:
                return False
            b = route_u[p + length] if p + length < len(route_u) else DEPOT
            segment_load = prefix[segment_last] - prefix[u] + q[u]
            if ru != rv and loads[rv] + segment_load > capacity:
                return False
            removal_gain = d[a][u] + d[segment_last][b] - d[a][b]
            for after in (True, False):
                c, e = (v, succ(v)) if after else (pred(v), v)
                if ru == rv and ((c != DEPOT and route_of[c] == ru and p <= position[c] < p + length)
                                 or (e != DEPOT and route_of[e] == ru and p <= position[e] < p + length)):
                    continue
                for reverse in ((False, True) if length > 1 and symmetric else (False,)):
                    head, tail = (segment_last, u) if reverse else (u, segment_last)
                    delta = d[c][head] + d[tail][e] - d[c][e] - removal_gain
                    if delta < -EPSILON:
                        segment = route_u[p:p + length]
                        if reverse:
                            segment.reverse()
                        del route_u[p:p + length]
                        target = routes[rv]
                        index = target.index(v) + (1 if after else 0)
                        target[index:index] = segment
                        rebuild(ru)
                        if rv != ru:
                            rebuild(rv)
                        return True
        return False

    def try_swap(u, v):
        """Échange deux clients non consécutifs."""
        ru, rv = route_of[u], route_of[v]
        pu, xu, pv, xv = pred(u), succ(u), pred(v), succ(v)
        if ru == rv and (xu == v or xv == u):
            return False
        if ru != rv and (loads[ru] - q[u] + q[v] > capacity or loads[rv] - q[v] + q[u] > capacity):
            return False
        delta = (d[pu][v] + d[v][xu] - d[pu][u] - d[u][xu]
                 + d[pv][u] + d[u][xv] - d[pv][v] - d[v][xv])
        if delta < -EPSILON:
            routes[ru][position[u]], routes[rv][position[v]] = v, u
            rebuild(ru)
            if rv != ru:
                rebuild(rv)
            return True
        return False

    def try_two_opt(u, v):
        """2-opt dans une tournée, pour rendre u et v consécutifs."""
        if not symmetric:
            return False
        r = route_of[u]
        route = routes[r]
        i, j = position[u], position[v]
        if i > j:
            u, v, i, j = v, u, j, i
        if j - i < 2:
            return False
        x, y, pu, w = route[i + 1], succ(v), pred(u), route[j - 1]
        # Variante 1 : inverser route[i+1..j] -> arêtes (u, v) et (x, y).
        if d[u][v] + d[x][y] - d[u][x] - d[v][y] < -EPSILON:
            route[i + 1:j + 1] = reversed(route[i + 1:j + 1])
            rebuild(r)
            return True
        # Variante 2 : inverser route[i..j-1] -> arêtes (pred(u), w) et (u, v).
        if d[pu][w] + d[u][v] - d[pu][u] - d[w][v] < -EPSILON:
            route[i:j] = reversed(route[i:j])
            rebuild(r)
            return True
        return False

    def try_two_opt_star(u, v):
        """2-opt* entre deux tournées : échange des fins ou des débuts."""
        ru, rv = route_of[u], route_of[v]
        route_u, route_v = routes[ru], routes[rv]
        x, y = succ(u), succ(v)
        head_u, head_v = prefix[u], prefix[v]
        tail_u, tail_v = loads[ru] - head_u, loads[rv] - head_v
        i, j = position[u], position[v]
        # Variante A : ...u -> y...  et  ...v -> x...
        if (x != DEPOT or y != DEPOT) and head_u + tail_v <= capacity and head_v + tail_u <= capacity:
            if d[u][y] + d[v][x] - d[u][x] - d[v][y] < -EPSILON:
                routes[ru] = route_u[:i + 1] + route_v[j + 1:]
                routes[rv] = route_v[:j + 1] + route_u[i + 1:]
                rebuild(ru)
                rebuild(rv)
                return True
        # Variante B : ...u -> v... (début de v inversé)  et  ...x -> y...
        if symmetric and head_u + head_v <= capacity and tail_u + tail_v <= capacity:
            if d[u][v] + d[x][y] - d[u][x] - d[v][y] < -EPSILON:
                routes[ru] = route_u[:i + 1] + route_v[j::-1]
                routes[rv] = route_u[:i:-1] + route_v[j + 1:]
                rebuild(ru)
                rebuild(rv)
                return True
        return False

    customers = [c for route in routes for c in route]
    moves, loop = 0, 0
    improved = True
    while improved:
        improved = False
        rng.shuffle(customers)
        for u in customers:
            # À l'échéance, la solution courante (toujours réalisable) est rendue
            # pour que l'appelant puisse la mémoriser avant l'arrêt.
            if time.perf_counter() >= deadline:
                return [route for route in routes if route]
            last_test = tested[u]
            tested[u] = moves
            for v in ctx.neighbors[u]:
                ru, rv = route_of[u], route_of[v]
                if loop > 0 and max(modified[ru], modified[rv]) <= last_test:
                    continue
                applied = try_relocate(u, v) or try_swap(u, v)
                if not applied:
                    applied = try_two_opt(u, v) if ru == rv else try_two_opt_star(u, v)
                if applied:
                    moves += 1
                    modified[ru] = modified[rv] = moves
                    improved = True
        loop += 1
    return [route for route in routes if route]
