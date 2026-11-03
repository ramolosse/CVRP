# CVRP — tournées de livraison

Projet CesiCDP / ADEME : modélisation et résolution du problème de tournées de véhicules avec capacité (CVRP).

## Périmètre actuel

Le code traite un dépôt, une flotte homogène limitée, des demandes clients et des coûts d’arcs fixes. Il fournit deux approches :

- **Algorithme génétique** : métaheuristique destinée aux instances moyennes et grandes.
- **PLNE** : formulations exactes avec Branch and Bound et résolution de référence par CBC, utiles surtout sur les petites instances.

Le trafic dépendant de l’heure, les fenêtres de livraison et l’attente ne sont pas implémentés. Le contexte de l’énoncé les mentionne, mais le niveau B CVRP est le périmètre de base attendu. Les résultats actuels ne doivent donc pas être présentés comme tenant compte du trafic.

## Structure

```text
algorithms/
  genetic_algorithm.py   # Algorithme génétique et opérateurs
  plne.py                # PLNE, Branch and Bound, interface CBC
common.py                # Chargement, coûts et validation CVRP
main.ipynb               # Démonstration génétique et PLNE
plne_branch_and_bound.ipynb # Étude du PLNE
livrables/               # Modélisation formelle
results/                 # Résultats expérimentaux
 tests/                  # Vérifications du PLNE
```

## Lancer les méthodes depuis le notebook

Ouvrir `main.ipynb` dans Jupyter. Le notebook choisit les instances avec `load_instance`, puis les transmet aux solveurs. Pour lancer le génétique séparément :

```python
from common import load_instance
from algorithms.genetic_algorithm import solve

instance = load_instance("data/A-n60-k9.vrp")
best, stats = solve(instance)
```

Le module génétique ne choisit ni ne charge les fichiers d’instance. Les paramètres de recherche sont définis au début de `algorithms/genetic_algorithm.py` ; les chemins d’instances et de résultats restent dans le notebook ou le script appelant.

## Représentation des solutions

Les instances sont chargées dans `common.Instance`. Le dépôt a l’identifiant interne `0`. Une solution est une liste de tournées contenant chacune les clients dans leur ordre de visite, sans le dépôt, par exemple `[[3, 1, 2], [4, 5]]`. Le coût inclut le départ et le retour au dépôt. Les distances `EUC_2D` suivent l’arrondi CVRPLIB.

Fonctions communes principales : `load_instance`, `load_solution`, `solution_cost`, `check_solution`, `is_feasible` et `gap`.

## PLNE

`algorithms/plne.py` contient une formulation compacte à deux indices et la formulation indexée par véhicule présentée dans le livrable. Le Branch and Bound utilise les relaxations linéaires HiGHS et peut ajouter des coupes de capacité. `solve_with_cbc` résout le même modèle avec CBC. Ces méthodes exactes ne sont pas adaptées aux instances de plusieurs milliers de clients ; l’algorithme génétique constitue la méthode heuristique retenue pour les instances de taille réaliste.

## Modélisation et limites

Le notebook `livrables/Livrable_1_Modelisation_CVRP_ameliore.ipynb` définit les données, la version décisionnelle, la réduction du TSP et le PLNE. La contrainte de progression de charge utilise le terme d’affectation du client suivant afin de désactiver correctement la demande lorsqu’il n’appartient pas au véhicule considéré.

Pour étendre le modèle au CVRPTW, il faudra ajouter les heures d’arrivée, les fenêtres temporelles, l’interdiction de servir hors fenêtre et l’attente autorisée. Pour le trafic dépendant de l’heure, les durées d’arc devront dépendre de l’heure de départ et respecter les unités et hypothèses des données routières.

## Validation expérimentale à compléter

Le livrable final doit présenter au moins 20 instances variées, les gaps par rapport aux solutions de référence, les temps, plusieurs répétitions avec des graines distinctes, des statistiques et une interprétation des limites. Les résultats préexistants du dépôt ne constituent pas à eux seuls ce protocole complet.
