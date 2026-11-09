# Avancement du projet CVRP

**Mise à jour :** 8 novembre 2026
**Contexte :** CESI — Année 3 — Bloc Algorithmique et Optimisation
**Notebook principal :** [`main.ipynb`](main.ipynb)

## État du livrable

Le notebook suit la progression du projet : contexte et périmètre, modélisation PLNE, complexité, rôle du PLNE comme référence, choix du GA pour les grandes instances, puis expérimentation et interprétation.

Le périmètre implémenté est le CVRP de niveau B : dépôt unique, flotte homogène, capacités identiques et demandes connues. Les fenêtres temporelles, l’attente et le trafic variable selon l’heure ne sont pas implémentés.

## Données et références

Le jeu d’essai contient 23 instances de référence VRPLIB des séries A, B, E et P, avec de 12 à 79 clients. Il s’agit de benchmarks académiques, pas de données de tournées réelles. Chaque instance dispose d’un fichier `.sol` de référence. Une référence `.sol` n’est pas automatiquement un optimum certifié ; le gap est présenté comme écart à la référence, sauf lorsque le Branch and Bound prouve explicitement l’optimalité.

## Méthodes

- **PLNE / Branch and Bound** : utilisé pour vérifier et certifier l’optimum de certaines petites instances. La section 6 montre également des essais limités à cinq secondes sur `A-n37-k6`, `A-n60-k9` et `A-n80-k10`. Ces essais atteignent la limite de temps ; ils illustrent les limites pratiques sur ces instances et cette configuration, pas une impossibilité générale ni un seuil universel en nombre de clients.
- **Algorithme génétique** : méthode retenue pour chercher rapidement des tournées réalisables sur les grandes instances. Il utilise une permutation des clients, un Split glouton, le croisement OX, la mutation et l’élitisme. Il ne garantit pas l’optimalité.

## Résultats expérimentaux enregistrés dans le notebook

- Une exécution avec la graine 42 produit des solutions faisables sur les 23 instances. Le gap moyen par rapport aux références est de 8,54 % (médiane 8,28 %). Dix instances dépassent 10 %.
- L’étude multi-graines porte sur les 23 instances et cinq graines, soit 115 exécutions. La moyenne des gaps moyens par instance est d’environ 9,33 % ; la dispersion varie fortement selon l’instance.
- La comparaison à budget maximal égal porte sur huit instances de 30 clients ou moins, avec cinq secondes par méthode. Le PLNE certifie l’optimum sur six instances ; il atteint la limite sans solution entière sur deux autres.
- Le test de passage à l’échelle utilise des sous-instances Leuven1 de 50 à 500 clients. Le GA trouve des solutions faisables dans un budget de trois secondes sur les grandes tailles testées. Ces coûts ne disposent pas ici d’un gap de référence.
- Le notebook inclut une analyse de relaxation linéaire, une sensibilité au taux de mutation, une courbe de convergence et des cartes de tournées. Une interprétation est placée directement après chaque tableau ou figure ; la section 8.8 en donne une synthèse.

Les temps sont ceux de la machine où le notebook a été exécuté. Les expériences peuvent être relancées depuis la section 8 ; le multi-graines comprend 115 recherches et peut prendre plusieurs minutes. Enregistrer le notebook après exécution pour conserver ses sorties.

## Limites et prochaines améliorations

1. Ajouter une recherche locale après le Split (relocate, échange, 2-opt*) et comparer les gaps aux résultats actuels avec le même protocole et les mêmes graines.
2. Comparer le Split glouton à un Split optimisé par programmation dynamique.
3. Étendre les tests de passage à l’échelle au-delà de 500 clients et documenter le coût, le temps et la mémoire.
4. Étudier ultérieurement le CVRPTW de niveau avancé (fenêtres temporelles, attente autorisée et interdiction de livraison hors fenêtre) ; cette extension n’est pas réalisée dans le périmètre actuel.
5. Nuancer toute conclusion sur le PLNE en fonction de l’instance, du solveur et du budget de calcul, et distinguer systématiquement référence connue et optimum certifié.
