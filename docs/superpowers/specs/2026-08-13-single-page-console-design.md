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

## Reste à faire

### 1. Le mode interactif de `import -p`

Seul cas qui justifierait un `WebInteraction` : le port `InteractionPort`
existe, la console ne s'en sert pas.

### 2. Une seule page subsiste

`report.html`, servie uniquement aux requêtes non-HTMX de
`/jobs/{id}/report`. Une URL de compte rendu mise en favori doit
répondre autre chose qu'un fragment nu. Elle ne dépend plus de
`base.html`, supprimé.

## Tranches — toutes livrées

| # | Tranche | Commit |
|---|---|---|
| 1 | Coquille et lecteur permanent | `f72c9d8` |
| 2 | Recherche vivante et inspecteur | `9bdfeb3` |
| 3 | Jobs en ruban | `6bee025` |
| 4 | L'établi (+ verrou Shazam `ff39232`) | `46507d3` |
| 5 | Nettoyage | `94e51f4` |

## Dettes traitées

### Le parcours du dépôt — `fe8f2c0`, `909f942`

Cache des morceaux parsés dans `repository.py`, clé = chemin, validation
= (mtime, taille). Mesuré sur les 928 morceaux : console 1,46 s → 90 ms,
frappe dans la recherche 1,4 s → 65-100 ms. Coût : 66 Mo.

Angle mort assumé et testé : une réécriture qui ne change ni la date ni
la taille est invisible.

### Le double parsing — `256c8d7`

Les six commandes CLI demandent les modèles, plus les chemins.
`get_repository_song_files` supprimée : plus aucun appelant, et un
helper qui coûte le double en le disant dans sa propre docstring est un
piège.

`find_song_file` globe directement — 6 ms contre 41 ms à chaud, sur le
chemin de chaque clic. Sa docstring promettait déjà d'éviter de
construire un modèle par candidat, « ce constructeur réécrit l'en-tête
ID3 de tout fichier sans tag YouTube ID » ; le helper qu'elle appelait
faisait exactement ça. Le danger était réel, il est maintenant écarté
pour de bon.

### Aucune page n'avait jamais été rendue par un moteur de navigateur

Le verrou du profil Chrome a été levé. Depuis, chaque changement est
rendu, mesuré et piloté dans un vrai navigateur, et les tests de
câblage ne sont plus la seule preuve.

Ce que cela a immédiatement attrapé, et qu'aucun test de câblage
n'aurait vu : une chirurgie CSS par motif avait entièrement mangé
`#timeline` et `#seek` — la barre de lecture n'existait plus, et la
suite était verte. Depuis, les mesures qui portent des décisions sont
prises sur la page : `#seek` à 17 rem pour vérifier qu'un libellé ne se
tronque pas, la largeur du canvas de 362 px à 1400 px, la couleur
réellement peinte dans les deux thèmes.

Reste vrai : un test Python ne mesure pas du texte rendu. Ce qui est
vérifié au navigateur est dit comme tel dans les messages de commit.

### La passe « look » — de `bda2004` à `6c96584`

Livrée. Elle a produit, dans l'ordre : les contrôles dessinés au lieu
d'être laissés au navigateur (19 sur 19, contre 3 au départ), une échelle
typographique et une échelle d'espacement, la hiérarchie des surfaces
remise à l'endroit, la disposition inspecteur-au-dessus / nav-à-côté, un
sélecteur de thème à trois états — dont « suivre le système », qui est
la raison pour laquelle la palette est un attribut et non une media
query — et le waveform.

Les deux points nommés à l'ouverture sont clos : la durée affiche `6:17`
et non `00:06:17`, et la hauteur des lignes a été réglée par la
réorganisation.

### Le waveform — `0c50188`, `0148c7a`, `9b55710`

Les crêtes vivent dans le MP3, en frame ID3 privée versionnée, 400
octets. Mesuré sur un morceau de 3,1 Mo : 420 ms puis 1 ms, et le
fichier n'a pas grossi — le padding ID3 a absorbé la frame. Aucune
dépendance ajoutée : ffmpeg était déjà un binaire requis.

Échelle absolue, pas normalisée par morceau : un téléchargement muet ou
tronqué doit ressembler à ce qu'il est. Le canvas est *dans* `#seek`,
donc le clic, le glisser et les flèches n'ont pas été réécrits.

Dette ouverte par là : le point 1 ci-dessus.

### Les crêtes calculées pendant l'écoute — `9e495ce`

La dette ouverte par le waveform. 420 ms de ffmpeg payées par qui
appuyait sur lecture, c'est-à-dire au seul moment où quelqu'un attend la
musique. Deux endroits déplacent ce travail avant l'attente.

L'import stocke le waveform en convertissant : il tient déjà le fichier
et vient de l'encoder, donc la demi-seconde disparaît dans le
téléchargement qui précède, et un morceau importé désormais ne la paie
jamais. En best effort — un waveform impossible à calculer n'est pas un
import raté.

Le player demande les crêtes du morceau suivant pendant que le morceau
courant joue. Quel morceau est « suivant » dépend du sens de parcours de
la file, comme l'affichage de la barre d'outils. C'est ce qui couvre les
928 morceaux antérieurs sans les réécrire en masse dans le dos de
l'auditeur — un balayage global reste donc non offert, et n'est plus
nécessaire au problème posé.

Mesuré au navigateur : sauter au morceau préchauffé dessine son waveform
en 150 ms contre 1200 ms à froid.

Trois doubles de test ont gagné le `path` que la vraie `SongModel` a
toujours eu. Ils étaient partiels au point de laisser l'import se mettre
à utiliser un attribut qu'ils ne modélisaient pas.

### L'import ne disait pas à la page qu'il avait écrit — `91573b6`

`#list` et `#nav` se rafraîchissent sur `songsChanged`, et seule la
sauvegarde l'émettait. Un import téléchargeait ses fichiers et la liste
continuait d'afficher ce qu'elle avait, jusqu'au rechargement.

L'en-tête est posé dans `_job_fragment`, donc sur les deux chemins à la
fois. La règle est explicite : le *check* ne l'émet jamais, un import
sans nouveauté non plus, un import échoué si — il ne porte aucun rapport,
donc ce qu'il a écrit avant de s'arrêter est inconnu.

Une contre-épreuve a montré que le test du *check* était creux : il
passait parce qu'un check terminé n'a pas de clé `imported`, pas parce
que c'est un check. Corrigé en `09dfcef` avec le cas d'un check en échec,
qui n'est refusé que par son type.
