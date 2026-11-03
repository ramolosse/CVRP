# Avancement du projet CVRP

Dernière mise à jour : 2 novembre 2026

## Périmètre retenu

Le projet conserve le **CVRP niveau B** : dépôt unique, flotte homogène de capacité identique, demandes clients et coût fixe par arc. Les méthodes retenues sont l’algorithme génétique et le PLNE. Hill Climbing et Tabu Search ont été retirés du code. Le trafic dépendant de l’heure et les fenêtres de temps décrits dans le contexte ne sont pas pris en charge par l’implémentation actuelle.

## État des livrables

- **Modélisation** : notebook présent avec formalisation, décision, réduction TSP vers CVRP et PLNE indexé par véhicule.
- **Correction de modèle** : la propagation de charge doit être activée par l’affectation du client suivant : `u_jk >= u_ik + q_j y_jk - Q(1 - x_ijk)`. Sans `y_jk`, une contrainte peut s’appliquer entre des clients rattachés à des camions différents et éliminer des solutions faisables. La formule et son explication ont été corrigées dans le notebook.
- **Algorithme génétique** : code présent avec représentation par permutation, décodage Split, sélection par tournoi, croisement OX, mutations, élitisme et critères d’arrêt par temps, générations ou stagnation. Il reçoit désormais un `common.Instance` via `solve(instance)` ; les choix et chemins de données sont dans `main.ipynb`. Il utilise `check_solution`, `route_cost`, `route_load`, `solution_cost` et `gap`, comme le PLNE.
- **PLNE** : deux formulations, Branch and Bound avec relaxations HiGHS et coupes de capacité, ainsi qu’une interface CBC sont présentes.
- **Notebook principal** : reprend les éléments de modélisation et explique les deux méthodes, avec une démonstration génétique puis une résolution PLNE sur petite instance.
- **Documentation** : README actualisé et périmètre CVRP explicité.

## Points à faire avant le rendu final

1. Exécuter le notebook principal de bout en bout dans l’environnement du projet et confirmer les chemins / dépendances.
2. Construire un plan expérimental d’au moins 20 instances et répéter les essais génétiques avec plusieurs graines.
3. Produire tableaux et graphiques sur coût, gap, temps, taille et caractéristiques des instances ; analyser robustesse et sensibilité des paramètres.
4. Vérifier les références et la formulation du notebook avec le tuteur, en particulier la portée de la preuve de complexité et les références bibliographiques.
5. Si le groupe veut finalement intégrer trafic horaire ou fenêtres de temps, étendre les données, la fonction de coût, le PLNE, le décodeur et l’évaluation de faisabilité ; ce travail n’est pas réalisé à ce stade.
6. Préparer une présentation en anglais et une démonstration fluide sur une petite instance.

## Risques et limites connus

- Le PLNE exact ne peut pas traiter plusieurs milliers de clients en pratique ; il sert de référence sur de petits cas.
- Les résultats sur les six fichiers présents ne satisfont pas encore à eux seuls l’exigence d’au moins 20 instances variées.
- Les coûts sont statiques : aucune décision d’heure de départ ni congestion variable n’est simulée.
- Le seuil de gap demandé doit être discuté avec les résultats réellement mesurés ; aucune performance cible n’est affirmée ici.
