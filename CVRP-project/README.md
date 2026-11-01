# CVRP Project — Optimisation de Tournées de Véhicules avec Capacité

Ce projet a pour objectif de modéliser, implémenter et comparer plusieurs approches algorithmiques pour résoudre le problème de tournées de livraison avec contraintes de capacité (**CVRP** — *Capacitated Vehicle Routing Problem*), dans le cadre du projet CesiCDP (CESI / ADEME).

---

## 📁 Structure du Projet

Le projet est structuré de manière modulaire pour séparer la gestion des données, les algorithmes de résolution, les benchmarks et les visualisations :

```text
cvrp-project/
├── data/                          # Instances du problème (.vrp) à importer
│   └── .gitkeep
├── algorithms/                    # Modules des algorithmes (à implémenter)
│   ├── __init__.py
│   ├── plne.py                    # Résolution exacte par PLNE (ex: PuLP)
│   ├── hill_climbing.py           # Recherche locale (Hill Climbing)
│   ├── genetic_algorithm.py       # Algorithme Génétique
│   └── tabu_search.py             # Recherche Tabou
├── common.py                      # Fonctions communes (parsing, calculs distances/coûts, validation)
├── benchmark.py                   # Script d'exécution et collecte des résultats
├── results/                       # Sorties et analyses
│   ├── results.csv                # Tableau récapitulatif des performances
│   └── plots/                     # Graphiques comparatifs et tracés de tournées
├── main.ipynb                     # Notebook interactif d'expérimentation et visualisation
├── livrables/                     # Livrables théoriques et modélisations (Livrable 1)
│   └── Livrable_1_Modelisation_CVRP_ameliore.ipynb
├── pyproject.toml                 # Définition du projet et dépendances
├── uv.lock                        # Fichier de verrouillage des versions
├── .gitignore                     # Règles d'exclusion Git
└── README.md                      # Documentation du projet
```

### Rôle des composants

- **`data/`** : Répertoire destiné à accueillir les instances de test au format `.vrp` (instances standard issues de CVRPLIB ou instances personnalisées). *Les données seront importées ultérieurement.*
- **`algorithms/`** : Contient les différentes méthodes de résolution. Chaque fichier correspond à un paradigme d'optimisation spécifique (*à implémenter ultérieurement*).
- **`common.py`** : Regroupera les fonctions partagées : chargement des fichiers avec `vrplib`, calcul de la matrice des distances euclidiennes, évaluation du coût d'une solution, vérification de la faisabilité (respect de la capacité $Q$, unicité de visite des clients, départ/retour au dépôt).
- **`benchmark.py`** : Script automatisé permettant de tester les algorithmes sur un ensemble d'instances, de mesurer les temps d'exécution et les coûts obtenus, et d'exporter les résultats dans `results/results.csv`.
- **`results/`** : Conserve l'historique des exécutions, les métriques (`results.csv`) et les figures exportées (`results/plots/`).
- **`main.ipynb`** : Point d'entrée interactif sous Jupyter pour manipuler les données, tester les fonctions à la volée et afficher les cartes des tournées.

---

## 🛠️ Installation et Environnement

Le projet requiert **Python 3.12 ou supérieur**.

### Option 1 : Avec `uv` (Recommandé - rapide et moderne)

Si vous avez installé [`uv`](https://github.com/astral-sh/uv) :

1. **Synchroniser l'environnement et installer les dépendances** :
   ```bash
   uv sync
   ```
   Cette commande crée automatiquement le dossier `.venv` et installe l'ensemble des dépendances verrouillées par `uv.lock`.

### Option 2 : Avec `venv` et `pip` standard

1. **Créer l'environnement virtuel** :
   ```bash
   python -m venv .venv
   ```

2. **Activer l'environnement virtuel** :
   - **Sur Windows (PowerShell)** :
     ```powershell
     .venv\Scripts\Activate.ps1
     ```
   - **Sur Windows (Invite de commandes cmd)** :
     ```cmd
     .venv\Scripts\activate.bat
     ```
   - **Sur Linux / macOS / Git Bash** :
     ```bash
     source .venv/bin/activate
     ```

3. **Installer les dépendances** :
   ```bash
   pip install -r <(python -c "import tomli; ...") # ou directement :
   pip install numpy pandas matplotlib pulp vrplib ipykernel requests
   ```

---

## 🚀 Utilisation

### 1. Ajout des données de test
Déposez vos fichiers d'instances `.vrp` dans le dossier `data/` :
```text
data/
├── A-n32-k5.vrp
├── B-n31-k5.vrp
└── ...
```

### 2. Lancement du Notebook interactif
Ouvrez [`main.ipynb`](file:///C:/Users/ramol/OneDrive/Bureau/CESI%20Ann%C3%A9e%203/Bloc%20Algorithmique/Projet_Algorithmique/CVRP-project/main.ipynb) dans VS Code ou lancez le serveur Jupyter :

- Avec `uv` :
  ```bash
  uv run jupyter notebook main.ipynb
  ```
- Avec `venv` activé :
  ```bash
  jupyter notebook main.ipynb
  ```

> Dans VS Code, veillez à sélectionner le noyau Python situé dans `.venv` (`Python 3 (.venv)`).

### 3. Utiliser Hill Climbing
Le module `common.py` utilise `vrplib.read_instance` pour charger les sections
`NODE_COORD_SECTION`, `DEMAND_SECTION` et `DEPOT_SECTION` d'une instance CVRPLIB/TSPLIB,
ainsi que sa matrice de distances. Par exemple :

```python
from algorithms.hill_climbing import hill_climbing

resultat = hill_climbing("data/A-n32-k5.vrp")
print("Distance totale :", resultat["cost"])
for numero, tournee in enumerate(resultat["routes"], start=1):
    print(f"Camion {numero} :", tournee)
```

`routes` donne les clients visités par chaque camion; le dépôt est ajouté au
départ et au retour lors du calcul du coût. Les distances `EUC_2D` suivent
l'arrondi entier TSPLIB. Le résultat est une solution heuristique : elle est
faisable, mais n'est pas garantie optimale.

### 4. Exécution des Benchmarks (une fois les algorithmes implémentés)
Pour lancer la comparaison globale de tous les algorithmes sur les instances :

- Avec `uv` :
  ```bash
  uv run python benchmark.py
  ```
- Avec `venv` activé :
  ```bash
  python benchmark.py
  ```

---

## 🧠 Algorithmes prévus (À implémenter ultérieurement)

| Algorithme | Type | Fichier | Objectif |
| :--- | :--- | :--- | :--- |
| **PLNE** | Exact | [`algorithms/plne.py`](file:///C:/Users/ramol/OneDrive/Bureau/CESI%20Ann%C3%A9e%203/Bloc%20Algorithmique/Projet_Algorithmique/CVRP-project/algorithms/plne.py) | Trouver la solution mathématiquement optimale (petites instances) via PuLP/CBC |
| **Hill Climbing** | Métaheuristique | [`algorithms/hill_climbing.py`](file:///C:/Users/ramol/OneDrive/Bureau/CESI%20Ann%C3%A9e%203/Bloc%20Algorithmique/Projet_Algorithmique/CVRP-project/algorithms/hill_climbing.py) | Amélioration locale itérative (voisinages 2-opt, swap de clients) |
| **Algorithme Génétique** | Métaheuristique | [`algorithms/genetic_algorithm.py`](file:///C:/Users/ramol/OneDrive/Bureau/CESI%20Ann%C3%A9e%203/Bloc%20Algorithmique/Projet_Algorithmique/CVRP-project/algorithms/genetic_algorithm.py) | Recherche globale par population, croisements (ex: OX) et mutations |
| **Recherche Tabou** | Métaheuristique | [`algorithms/tabu_search.py`](file:///C:/Users/ramol/OneDrive/Bureau/CESI%20Ann%C3%A9e%203/Bloc%20Algorithmique/Projet_Algorithmique/CVRP-project/algorithms/tabu_search.py) | Échappement aux optima locaux via une liste tabou des mouvements récents |

---

## 📦 Bibliothèques Principales

- **[NumPy](https://numpy.org/)** : Calculs matriciels et distances euclidiennes.
- **[Pandas](https://pandas.pydata.org/)** : Traitement et exportation des résultats de benchmark.
- **[Matplotlib](https://matplotlib.org/)** : Visualisation graphique des réseaux, des clients et des tournées des camions.
- **[VRPLIB](https://github.com/leonlan/vrplib)** : Parsing standardisé des fichiers d'instances `.vrp`.
- **[PuLP](https://coin-or.github.io/pulp/)** : Modélisation et résolution du programme linéaire en nombres entiers (PLNE).
- **[IPyKernel](https://ipython.org/)** : Exécution du notebook `main.ipynb`.
