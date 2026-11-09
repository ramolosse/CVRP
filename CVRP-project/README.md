# CVRP — tournées de livraison

Projet CesiCDP / ADEME : modélisation et résolution du problème de tournées de véhicules avec capacité (CVRP).

## Périmètre

Le projet traite un dépôt, une flotte homogène limitée, des demandes connues et des coûts d’arcs fixes. Le solveur retenu pour les grandes instances est l’algorithme génétique (GA). Le PLNE avec Branch and Bound sert de référence sur les petites instances, lorsque le solveur peut certifier l’optimalité.

Les fenêtres de livraison, l’attente et le trafic dépendant de l’heure ne sont pas implémentés. Les résultats décrivent donc le CVRP classique et ne doivent pas être présentés comme tenant compte du trafic.

## Fichiers principaux

```text
algorithms/
  genetic_algorithm.py   # Algorithme génétique et opérateurs
  plne.py                # PLNE, Branch and Bound, interface CBC
common.py                # Chargement, coûts et validation CVRP
main.ipynb               # Démarche, expériences et interprétation des résultats
benchmark.py             # Fonctions réutilisables de chargement et d'expérimentation
livrables/               # Modélisation formelle
data/                    # Instances VRPLIB et solutions de référence
results/                 # Quelques résultats exportés
```

## Installation et lancement

Depuis la racine du projet, installer les dépendances déclarées dans `pyproject.toml` :

```bash
uv sync
```

Lancer ensuite le notebook principal :

```bash
uv run jupyter notebook main.ipynb
```

Dans Jupyter, exécuter les cellules dans l’ordre avec **Run All**. Le notebook présente le modèle, les méthodes et leurs résultats. Pour lancer uniquement les expériences, aller à la section 8 ; ses cellules appellent les fonctions réutilisables de `benchmark.py`. Le multi-graines lance 115 recherches et peut prendre plusieurs minutes. Les sorties du notebook sont conservées dans le fichier si celui-ci est enregistré après exécution.

`benchmark.py` fournit des fonctions Python, sans interface en ligne de commande. Pour lancer un benchmark sans ouvrir le notebook, utiliser `uv run python -c` depuis la racine. Les commandes ci-dessous calculent les résultats et les enregistrent dans `results/`.

### Benchmarks depuis le terminal

Benchmark GA sur les 23 instances, avec une graine :

```powershell
uv run python -c "from benchmark import run_single_seed_ga_benchmark; df = run_single_seed_ga_benchmark(); print(df.to_string(index=False)); df.to_csv('results/ga_single_seed.csv', index=False)"
```

Benchmark multi-graines (5 graines × 23 instances, soit 115 exécutions) :

```powershell
uv run python -c "from benchmark import run_multi_seed_ga_benchmark; runs, summary = run_multi_seed_ga_benchmark(); print(summary.to_string()); runs.to_csv('results/ga_multi_seed_runs.csv', index=False); summary.to_csv('results/ga_multi_seed_summary.csv')"
```

Comparaison GA–PLNE sur les instances d’au plus 30 clients (jusqu’à 5 secondes par méthode) :

```powershell
uv run python -c "from benchmark import compare_plne_vs_ga; df = compare_plne_vs_ga(); print(df.to_string(index=False)); df.to_csv('results/ga_vs_plne.csv', index=False)"
```

Test de scalabilité sur des sous-instances Leuven1 de 50 à 500 clients :

```powershell
uv run python -c "from benchmark import run_scalability_benchmark; df = run_scalability_benchmark(); print(df.to_string(index=False)); df.to_csv('results/scalability.csv', index=False)"
```

Analyse du taux de mutation sur `A-n33-k5` :

```powershell
uv run python -c "from benchmark import run_mutation_sensitivity; df = run_mutation_sensitivity(); print(df.to_string(index=False)); df.to_csv('results/mutation_sensitivity.csv', index=False)"
```

Chaque commande peut prendre du temps selon l’expérience et la machine. Les fonctions acceptent des paramètres pour réduire le nombre d’instances ou modifier les graines et budgets ; leurs signatures et valeurs par défaut sont documentées dans `benchmark.py`.

## Protocole expérimental du notebook

- **Jeu d’essai** : 23 instances de référence VRPLIB des séries A, B, E et P, de 12 à 79 clients. Ce sont des benchmarks académiques, pas des données de tournées réelles. Les fichiers `.sol` sont des références connues ; ils ne constituent pas tous une preuve d’optimalité.
- **GA** : une exécution de référence par instance, puis cinq graines (`42`, `123`, `456`, `789`, `1024`) sur chacune des 23 instances. Les résultats comprennent les gaps, coûts, temps, générations, faisabilité, moyenne, médiane et écart-type.
- **Comparaison exacte** : GA et PLNE sur les instances d’au plus 30 clients, avec une limite maximale de cinq secondes par méthode. Le statut et la borne inférieure du PLNE permettent de distinguer un optimum certifié d’un arrêt sur limite.
- **Autres essais** : relaxation linéaire, Branch and Bound sur des instances plus grandes, sous-instances Leuven1 de 50 à 500 clients, sensibilité au taux de mutation, convergence et cartes des tournées.

Les fonctions qui exécutent les expériences sont dans `benchmark.py`; `main.ipynb` les appelle et présente les tableaux, graphiques et interprétations.

Les paramètres, graines et versions logicielles sont regroupés au début de la section expérimentale de `main.ipynb`. Les temps dépendent de la machine. Les tableaux et graphiques sont des sorties d’expérience ; enregistrer le notebook après exécution pour les conserver.

## Représentation des solutions et PLNE

Les instances sont chargées dans `common.Instance`. Le dépôt a l’identifiant interne `0`. Une solution est une liste de tournées sans le dépôt, par exemple `[[3, 1, 2], [4, 5]]`. Le coût inclut le départ et le retour au dépôt. Les distances `EUC_2D` suivent l’arrondi CVRPLIB.

`algorithms/plne.py` contient les modèles PLNE et le Branch and Bound avec relaxations HiGHS et coupes de capacité. `solve_with_cbc` fournit une résolution de référence supplémentaire. Les performances exactes dépendent de l’instance, de la formulation et du temps accordé ; il n’existe pas de frontière fixe en nombre de clients.

Le CVRPTW (fenêtres temporelles, interdiction de livrer hors fenêtre et attente autorisée) est une piste d’amélioration avancée, prévue pour une suite éventuelle du projet et non implémentée dans ce livrable. Le trafic dépendant de l’heure nécessiterait aussi des durées d’arc dépendant de l’heure de départ.
