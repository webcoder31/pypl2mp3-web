# Console une page — conception

**But :** tout avoir sous la main dans une seule page. Aucune navigation,
aucune popup sauf confirmation d'action destructrice.

**Forme retenue :** la console (trois panneaux, lecteur permanent) avec
l'établi (carte plein cadre, clavier) qui se déplie par-dessus pour la
correction en série.

---

## L'idée qui tient l'ensemble

Le curseur de tri et le curseur de lecture sont **le même curseur**.

Aujourd'hui il y a deux lecteurs qui s'ignorent (`fix.html:19` et
`player.html:16`) : on écoute dans l'un, on corrige dans l'autre. Le
morceau qu'on juge doit être le morceau qu'on entend. C'est ce qui fait
de l'établi la suite naturelle de la console plutôt qu'un second outil
collé à côté.

## Les cinq défauts que ça corrige

1. Le lecteur est une page — cliquer coupe la musique.
2. Filtrer recharge tout — scroll perdu, lecture coupée.
3. Corriger = une page + une redirection, quarante fois de suite.
4. Un job vit dans une cellule de tableau ; quitter la page le perd de vue.
5. Playlists et morceaux sont deux pages ; on ne voit jamais où on est.

Le point commun : rien ne persiste. Chaque action détruit le contexte de
la précédente.

---

## Structure

```
┌──────────────────────────────────────────────────────┐
│ en-tête : recherche · compteurs · ruban des jobs     │  #header
├───────────┬──────────────────────┬───────────────────┤
│ playlists │ liste des morceaux   │ inspecteur        │
│  #nav     │  #list               │  #inspector       │
├───────────┴──────────────────────┴───────────────────┤
│ lecteur : ⏮ ▶ ⏭  titre  ────●──── temps    #player   │
└──────────────────────────────────────────────────────┘
```

### La règle structurelle non négociable

L'élément `<audio>` vit dans `#player` et **aucun échange HTMX ne doit
jamais contenir cet élément**. Un swap qui l'englobe le recrée et coupe
le son. Toute cible d'échange est `#nav`, `#list`, `#inspector`,
`#header`, ou une ligne de la liste — jamais un ancêtre de `#player`.

C'est la contrainte dont découle tout le reste : si le lecteur doit
survivre à chaque interaction, il ne peut pas être dans le flux échangé.

### Ce que devient chaque commande

| Commande CLI | Où elle vit maintenant |
|---|---|
| `playlists` | `#nav`, en permanence |
| `songs` / `junks` | `#list`, filtré en direct |
| `play` | `#player` + la file, en permanence |
| `fix` | `#inspector`, ou l'établi pour la série |
| `junkize` | un bouton de l'inspecteur |
| `import` / `check` | un job, ruban dans `#header` |

## État et rechargement

La sélection courante (playlist, recherche, junk, morceau sélectionné)
est poussée dans l'URL par `history.replaceState`. Recharger la page
restitue la vue ; un signet sur « les junks de telle playlist » marche.

La file de lecture est de l'état client. Sémantique habituelle des
lecteurs : jouer un morceau depuis une vue fait de cette vue la file.

## L'établi

Même contenu que l'inspecteur, disposé en plein cadre, avec un curseur
sur la sélection courante. Bascule par une classe sur `<body>` et un
gabarit d'inspecteur différent — pas une autre page, pas une modale.

Entrer dans l'établi cale la file de lecture sur la sélection triée :
le morceau jugé est le morceau entendu.

Touches : `✓` accepter Shazam, `✗` éditer, `⏭` passer, `␣` pause,
`⇥` vidéo, `⌫` junkiser, `⎋` replier.

### Préchargement Shazam — et ses deux limites

`SongModel.last_shazam_request_time` est un **attribut de classe**
(`song.py:527`) : la temporisation de 15 s est globale au processus.

**Conséquence 1 — le préchargement est forcément séquentiel.** Un seul
worker de fond qui parcourt la file et range les résultats dans un cache
mémoire par identifiant YouTube. Quarante junks = dix minutes de travail
de fond. Il ne rattrapera jamais quelqu'un qui juge en moins de 15 s,
mais il prend de l'avance dès qu'on écoute vraiment un morceau. Le gain
est réel sans être total : l'annoncer autrement serait mentir.

**Conséquence 2 — il faut un verrou, sinon on aggrave l'existant.** La
temporisation n'est pas une exclusion mutuelle : elle lit une date, puis
attend. Deux coroutines qui la traversent ensemble passent le test
toutes les deux et tirent en même temps. Aujourd'hui ça n'arrive pas
parce qu'il n'y a qu'un appelant à la fois ; le worker de préchargement
en crée un second. Un `asyncio.Lock` autour de l'attente **et** de
l'appel, sinon le préchargement casse la limite qu'il est censé
respecter.

## Popups

Une seule : la confirmation d'import (téléchargement long, action
lourde), déjà présente en `hx-confirm`. Junkiser est réversible et n'en
mérite pas.

## Ce qui disparaît

Les gabarits `playlists.html`, `songs.html`, `player.html`, `fix.html`,
`report.html` en tant que pages. Leur contenu devient des fragments. Les
services et les routes de données ne bougent pas — la négociation de
contenu sur `HX-Request` est déjà en place.

## Découpage

Chaque tranche est visible et testable seule.

1. **La coquille et le lecteur permanent.** Une page, trois panneaux,
   lecteur en pied. Cliquer une playlist filtre sans recharger.
   *Épreuve : la musique ne s'arrête plus jamais.*
2. **Recherche vivante et inspecteur.** Filtrage à la frappe ;
   sélectionner une ligne remplit l'inspecteur ; enregistrer met la
   ligne à jour sur place.
   *Épreuve : corriger sans quitter la page ni perdre le scroll.*
3. **Les jobs en ruban.** Import et check dans l'en-tête, persistants ;
   le compte rendu s'affiche dans l'inspecteur.
   *Épreuve : lancer un import et continuer à travailler.*
4. **L'établi.** Plein cadre, clavier, curseur unique, worker de
   préchargement et son verrou.
   *Épreuve : corriger quarante junks d'affilée.*
5. **Nettoyage.** Suppression des pages mortes et de leurs tests.

Le « look » vient après, sur cette structure.

---

# Points en suspens

Tenu à jour au fil des tranches. Rien n'est perdu ici : ce qui est
mesuré est chiffré, ce qui est un choix est motivé.

## Dettes ouvertes par ce qui est déjà livré

### 1. La recherche vivante relance un parcours complet à chaque frappe

**Mesuré :** 1,4 s par parcours sur 927 morceaux, relancé à chaque pause
de 300 ms dans la frappe. Le contrôle d'une empreinte du dépôt (nombre de
fichiers + mtime maximum) coûte **6 ms**.

**Remède :** un cache du parcours invalidé par cette empreinte. Le point
délicat est que `SongModel` détient l'objet mutagen, pochette comprise —
927 modèles en mémoire, c'est à mesurer avant de s'engager. Cacher les
`SongSummary` (légers) obligerait en revanche à réimplémenter le
filtrage flou de `repository.py`, qui dériverait alors du CLI.

**Débloque aussi :** le point 2.

### 2. Les présélections d'artistes vieillissent après une correction

`#nav` n'est pas rafraîchi par `songsChanged` : un morceau réparé
n'apparaît sous son artiste qu'au rechargement de la page. Le rafraîchir
coûterait 1,4 s à chaque sauvegarde — inacceptable pendant une série de
corrections. Bloqué par le point 1.

### 3. Aucune page n'a jamais été rendue par un moteur de navigateur

Tout le comportement JavaScript — suivi de l'inspecteur, garde sur la
saisie non enregistrée, aperçu du suivant, sens de lecture, filtre de la
liste d'artistes — n'est vérifié qu'au niveau du **câblage** : le test
constate que le code est là, pas qu'il fait ce qu'il prétend. Les
verrous du bac à sable ont empêché Chrome de démarrer ; les vérifications
sont manuelles depuis le début.

## Tranches restantes

### 4. Tranche 3 — les jobs en ruban

Import et check remontent dans `#header`, persistants quoi qu'on fasse
ensuite. Le compte rendu s'affiche dans l'inspecteur au lieu d'une page.

### 5. Tranche 4 — l'établi

Plein cadre, clavier, curseur unique. Worker de préchargement Shazam
**et son verrou** : `SongModel.last_shazam_request_time` est un attribut
de classe qui lit une date puis attend, ce qui n'est pas une exclusion
mutuelle. Aujourd'hui il n'y a qu'un appelant ; le worker en crée un
second, et sans `asyncio.Lock` les deux traversent la temporisation
ensemble.

### 6. Tranche 5 — nettoyage

Suppression de `playlists.html`, `songs.html`, `player.html`,
`fix.html`, `report.html` et des routes `/playlists`, `/songs`,
`/player`, `/songs/{id}/fix` (GET), avec leurs tests. Le lien « Fix »
des lignes junk pointe encore sur l'ancien écran.

### 7. La passe « look »

Décidée avec l'utilisateur : après l'ergonomie. Points déjà relevés —
hauteur des lignes trop grande sur les titres longs, durée affichée
`00:06:17` là où `6:17` suffit.

## Hors périmètre web, notés au passage

### 8. Le CLI n'utilise pas `get_repository_songs`

Les commandes CLI passent encore par `get_repository_song_files` et
reconstruisent un `SongModel` par chemin. Le même gain d'environ 50 %
qu'a eu la couche web les attend.

### 9. Le mode interactif de `import -p`

Seul cas qui justifierait un `WebInteraction` : le port `InteractionPort`
existe, la console ne s'en sert pas.
