# Avancement du projet CVRP

**Mise à jour :** 9 novembre 2026
**Contexte :** CESI — Année 3 — Bloc Algorithmique et Optimisation
**Notebook principal :** [`main.ipynb`](main.ipynb)

## État du livrable

Le notebook suit la progression du projet : contexte et périmètre, modélisation PLNE, complexité, rôle du PLNE comme référence, résultats du GA de base, résultats du mémétique, puis comparaison de leurs gaps.

Le périmètre implémenté est le CVRP de niveau B : dépôt unique, flotte homogène, capacités identiques et demandes connues. Les fenêtres temporelles, l’attente et le trafic variable selon l’heure ne sont pas implémentés.

## Données et références

Le jeu d’essai contient 23 instances de référence VRPLIB des séries A, B, E et P, avec de 12 à 79 clients. Il s’agit de benchmarks académiques, pas de données de tournées réelles. Chaque instance dispose d’un fichier `.sol` de référence. Une référence `.sol` n’est pas automatiquement un optimum certifié ; le gap est présenté comme écart à la référence, sauf lorsque le Branch and Bound prouve explicitement l’optimalité.

## Méthodes

- **PLNE / Branch and Bound** : utilisé pour vérifier et certifier l’optimum de certaines petites instances. La section 6 montre également des essais limités à cinq secondes sur `A-n37-k6`, `A-n60-k9` et `A-n80-k10`. Ces essais atteignent la limite de temps ; ils illustrent les limites pratiques sur ces instances et cette configuration, pas une impossibilité générale ni un seuil universel en nombre de clients.
- **GA de base** : permutation des clients, opérateurs génétiques et Split glouton, sans recherche locale.
- **Algorithme mémétique** : méthode retenue pour les grandes instances. Le chromosome est une permutation des clients (tour géant), décodée par un Split optimal (programmation dynamique de Prins avec flotte limitée). Chaque enfant issu du croisement OX et de la mutation est amélioré par une recherche locale (relocate/or-opt, swap, 2-opt, 2-opt*) restreinte aux 15 plus proches voisins, puis réécrit dans le chromosome (apprentissage lamarckien). Les clones de même coût sont refusés et les 4 meilleurs individus sont conservés. La méthode ne garantit pas l’optimalité.

## Comparaison GA de base et mémétique (10 novembre 2026)

Le protocole apparié exécute les deux méthodes sur 23 instances et cinq graines, avec un budget maximal de trois secondes par méthode. Pour isoler les opérateurs, les deux utilisent une population de 30 individus et une limite de stagnation de 40 générations. Les 230 exécutions appariées sont conservées dans `results/ga_vs_memetic_runs.csv`, et l’agrégat par instance dans `results/ga_vs_memetic_summary.csv`.

- Le gap moyen des moyennes par instance passe de **19,88 %** pour le GA de base à **0,34 %** pour le mémétique, une baisse de **19,54 points**. Les médianes sont 14,98 % et 0 %.
- Le GA de base fournit une solution faisable sur 97,4 % des exécutions ; le mémétique en fournit une sur 100 %.
- Les gaps sont calculés uniquement pour les exécutions faisables. Le taux de faisabilité rend explicites les cas où le GA de base ne fournit pas de tournée.
- Les anciens résultats exportés du mémétique sont conservés sous des noms `memetic_*.csv` afin de les distinguer des nouveaux résultats du GA de base.

Ces mesures soutiennent le choix du mémétique sur les instances et budgets testés. Les références VRPLIB ne sont pas toutes des optima certifiés.

## Limites et prochaines améliorations

1. ~~Comparer le GA de base et le mémétique à budget égal~~ : réalisé sur 23 instances et cinq graines.
2. Gérer les enfants irréalisables : sur les instances à flotte presque pleine, jusqu’à 80 % des enfants dépassent le nombre de véhicules. Une pénalité de capacité (comme dans HGS, Vidal et al. 2012) permettrait de les réparer au lieu de les rejeter.
3. Rendre les benchmarks reproductibles : toutes les exécutions s’arrêtent sur la limite de temps, donc les résultats dépendent de la machine. Ajouter un budget en nombre d’évaluations.
4. Corriger le test de passage à l’échelle (la flotte vaut le nombre de clients, donc n’est pas limitée) et l’étendre aux instances X d’Uchoa et al. (100 à 1 000 clients, références connues).
5. Étudier ultérieurement le CVRPTW de niveau avancé (fenêtres temporelles, attente autorisée et interdiction de livraison hors fenêtre) ; cette extension n’est pas réalisée dans le périmètre actuel.
6. Nuancer toute conclusion sur le PLNE en fonction de l’instance, du solveur et du budget de calcul, et distinguer systématiquement référence connue et optimum certifié.
