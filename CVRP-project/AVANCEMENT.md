# Avancement du projet CVRP

**Mise à jour :** 9 novembre 2026
**Contexte :** CESI — Année 3 — Bloc Algorithmique et Optimisation
**Notebook principal :** [`main.ipynb`](main.ipynb)

## État du livrable

Le notebook suit la progression du projet : contexte et périmètre, modélisation PLNE, complexité, rôle du PLNE comme référence, choix du GA pour les grandes instances, puis expérimentation et interprétation.

Le périmètre implémenté est le CVRP de niveau B : dépôt unique, flotte homogène, capacités identiques et demandes connues. Les fenêtres temporelles, l’attente et le trafic variable selon l’heure ne sont pas implémentés.

## Données et références

Le jeu d’essai contient 23 instances de référence VRPLIB des séries A, B, E et P, avec de 12 à 79 clients. Il s’agit de benchmarks académiques, pas de données de tournées réelles. Chaque instance dispose d’un fichier `.sol` de référence. Une référence `.sol` n’est pas automatiquement un optimum certifié ; le gap est présenté comme écart à la référence, sauf lorsque le Branch and Bound prouve explicitement l’optimalité.

## Méthodes

- **PLNE / Branch and Bound** : utilisé pour vérifier et certifier l’optimum de certaines petites instances. La section 6 montre également des essais limités à cinq secondes sur `A-n37-k6`, `A-n60-k9` et `A-n80-k10`. Ces essais atteignent la limite de temps ; ils illustrent les limites pratiques sur ces instances et cette configuration, pas une impossibilité générale ni un seuil universel en nombre de clients.
- **Algorithme génétique mémétique** : méthode retenue pour les grandes instances. Le chromosome est une permutation des clients (tour géant), décodée par un Split optimal (programmation dynamique de Prins avec flotte limitée). Chaque enfant issu du croisement OX et de la mutation est amélioré par une recherche locale (relocate/or-opt, swap, 2-opt, 2-opt*) restreinte aux 15 plus proches voisins, puis réécrit dans le chromosome (apprentissage lamarckien). Les clones de même coût sont refusés et les 4 meilleurs individus sont conservés. La méthode ne garantit pas l’optimalité.

## Résultats du GA mémétique (9 novembre 2026)

Mêmes protocoles que la section 8 du notebook, relancés depuis le terminal avec `benchmark.py` ; les tableaux sont dans `results/` (`ga_single_seed.csv`, `ga_multi_seed_runs.csv`, `ga_multi_seed_summary.csv`, `ga_vs_plne.csv`, `scalability.csv`, `mutation_sensitivity.csv`). Les sorties de la section 8 du notebook datent encore de l’ancien GA et doivent être régénérées.

- Graine 42 (5 à 12 s selon la taille) : 23 solutions faisables, gap moyen 0,29 % (médiane 0 %). 17 instances atteignent leur référence ; seul `B-n45-k6` dépasse 1 % (4,87 %).
- Cinq graines × 23 instances à 3 s : 115 solutions faisables, moyenne des gaps moyens 0,48 % (médiane 0 %), écart-type moyen 0,28 point. Les cas difficiles sont `B-n45-k6` (5,58 %), `A-n45-k6` (2,48 %) et `A-n80-k10` (1,68 %) : ce sont des instances où la flotte est presque pleine.
- PLNE vs GA à 5 s : le GA atteint la référence sur les huit instances, y compris `E-n30-k3` et `P-n22-k8`, où le PLNE s’arrête sans solution entière.
- Sous-instances Leuven1 à 3 s : coûts de 6 453 (50 clients) à 39 918 (500 clients), contre 7 140 à 45 365 pour l’ancien GA.
- Sensibilité à la mutation sur `A-n33-k5` : gap nul pour tous les taux. L’instance est devenue trop facile pour cette étude ; il faut la refaire sur une instance difficile (`B-n45-k6`, `A-n45-k6`).

## Résultats de l’ancien GA (Split glouton, sans recherche locale) enregistrés dans le notebook

- Une exécution avec la graine 42 produit des solutions faisables sur les 23 instances. Le gap moyen par rapport aux références est de 8,54 % (médiane 8,28 %). Dix instances dépassent 10 %.
- L’étude multi-graines porte sur les 23 instances et cinq graines, soit 115 exécutions. La moyenne des gaps moyens par instance est d’environ 9,33 % ; la dispersion varie fortement selon l’instance.
- La comparaison à budget maximal égal porte sur huit instances de 30 clients ou moins, avec cinq secondes par méthode. Le PLNE certifie l’optimum sur six instances ; il atteint la limite sans solution entière sur deux autres.
- Le test de passage à l’échelle utilise des sous-instances Leuven1 de 50 à 500 clients. Le GA trouve des solutions faisables dans un budget de trois secondes sur les grandes tailles testées. Ces coûts ne disposent pas ici d’un gap de référence.
- Le notebook inclut une analyse de relaxation linéaire, une sensibilité au taux de mutation, une courbe de convergence et des cartes de tournées. Une interprétation est placée directement après chaque tableau ou figure ; la section 8.8 en donne une synthèse.

Les temps sont ceux de la machine où le notebook a été exécuté. Les expériences peuvent être relancées depuis la section 8 ; le multi-graines comprend 115 recherches et peut prendre plusieurs minutes. Enregistrer le notebook après exécution pour conserver ses sorties.

## Limites et prochaines améliorations

1. ~~Ajouter une recherche locale après le Split~~ et ~~un Split optimal par programmation dynamique~~ : réalisés (GA mémétique).
2. Gérer les enfants irréalisables : sur les instances à flotte presque pleine, jusqu’à 80 % des enfants dépassent le nombre de véhicules. Une pénalité de capacité (comme dans HGS, Vidal et al. 2012) permettrait de les réparer au lieu de les rejeter.
3. Rendre les benchmarks reproductibles : toutes les exécutions s’arrêtent sur la limite de temps, donc les résultats dépendent de la machine. Ajouter un budget en nombre d’évaluations.
4. Corriger le test de passage à l’échelle (la flotte vaut le nombre de clients, donc n’est pas limitée) et l’étendre aux instances X d’Uchoa et al. (100 à 1 000 clients, références connues).
5. Étudier ultérieurement le CVRPTW de niveau avancé (fenêtres temporelles, attente autorisée et interdiction de livraison hors fenêtre) ; cette extension n’est pas réalisée dans le périmètre actuel.
6. Nuancer toute conclusion sur le PLNE en fonction de l’instance, du solveur et du budget de calcul, et distinguer systématiquement référence connue et optimum certifié.
