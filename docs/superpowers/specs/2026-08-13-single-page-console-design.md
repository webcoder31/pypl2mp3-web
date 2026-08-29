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

Prévue en trois colonnes avec le lecteur en pied de page, elle n'a pas
tenu : la passe « look » a mis l'inspecteur au-dessus de la liste et la
nav de côté, pour donner à la liste toute la largeur de la colonne
principale. Le schéma ci-dessous est celui qui est en place.

```
┌────────────────────────────────────┬─────────────────┐
│ en-tête : recherche · compteurs · ruban des jobs     │  #header
├────────────────────────────────────┼─────────────────┤
│ inspecteur                #inspector│ playlists       │
├────────────────────────────────────┤  #nav           │
│ ⏮ ▶ ⏭  ▂▃▅▂▃▁▂  0:47   🔊▬▬▭ #player│                 │
├────────────────────────────────────┤                 │
│ PLAYLIST │ IMPORTS          onglets │                 │
├────────────────────────────────────┤                 │
│ liste des morceaux                  │                 │
│  #list  —  ou  #imports             │                 │
└────────────────────────────────────┴─────────────────┘
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

Les filtres — `playlist`, `artist`, `q`, `junk` — sont poussés dans l'URL
par `history.replaceState`. Recharger la page restitue la vue ; un signet
sur « les junks de telle playlist » marche.

**Le morceau sélectionné n'y est pas**, contrairement à ce que cette
section annonçait. La route de la console ne lit aucun identifiant et le
gabarit rend toujours « Select a song. » ; c'est la page qui choisit le
premier de la liste à l'arrivée. Mettre le morceau dans l'URL demanderait
que le serveur sache pré-remplir l'inspecteur, ce qu'il ne fait pas.

La file de lecture est de l'état client. Sémantique habituelle des
lecteurs : jouer un morceau depuis une vue fait de cette vue la file.

## L'établi

Même contenu que l'inspecteur, disposé en plein cadre, avec un curseur
sur la sélection courante. Bascule par une classe sur `<body>` et un
gabarit d'inspecteur différent — pas une autre page, pas une modale.

Entrer dans l'établi cale la file de lecture sur la sélection triée :
le morceau jugé est le morceau entendu.

Touches, telles qu'elles ont été faites — la liste prévue ici annonçait
un jeu de raccourcis dédiés (`✓` accepter, `✗` éditer, `⌫` junkiser) qui
n'a pas vu le jour :

| touche | effet | portée |
|---|---|---|
| `←` `→` | morceau précédent / suivant | partout |
| `↑` `↓` | volume, par pas de 5 % | partout |
| `␣` | lecture / pause | partout |
| `⇥` | ouvrir la vidéo | partout |
| `⏎` | enregistrer le panneau | établi seulement |
| `⎋` | replier l'établi | établi seulement |

Accepter la proposition de Shazam et junkiser restent des boutons.
`⏎` fait office d'« accepter » puisqu'il enregistre ce que le panneau
montre, mais rien n'est câblé sur `✓` ni sur `⌫`.

### Préchargement Shazam — et ses deux limites

`SongModel.last_shazam_request_time` est un **attribut de classe** : la
temporisation de 15 s est globale au processus. (Le numéro de ligne cité
ici à l'origine avait dérivé de trois lignes — un rappel qu'une
référence de ce genre vieillit sans prévenir.)

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
respecter. *Posé depuis, en `ff39232` : `SongModel.shazam_lock()`.*

## Popups

Une seule, et **ce n'est plus celle qui était prévue ici**. La règle
posée à l'ouverture — confirmer l'import, ne pas confirmer le junkisage —
s'est inversée à l'usage, dans les deux sens :

L'import n'en a plus. Le volet le dit à l'endroit où le dialogue se
trouvait : ce qui est arrivé reste, et relancer est un clic. Un dialogue
n'y gardait rien.

Junkiser en a une, sur la ligne comme dans l'inspecteur. Le raisonnement
d'origine — « c'est réversible » — était faux : `junkize_song` appelle
`reset_state`, qui efface artiste, titre, pochette, données de sortie et
provenance. Shazam peut les retrouver, mais une correction faite à la
main est perdue. Le libellé du dialogue le dit sans détour : *« This
cannot be undone. »*

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

## Choix laissés ouverts

Ni dettes ni tâches : des décisions prises, susceptibles d'être reprises,
écrites ici pour qu'elles ne passent pas pour des oublis.

### Le reflet du waveform non joué, très pâle

Il dérive de `--line-strong` (17 % d'opacité) que la moitié basse
reprend à 55 %, soit 9 % effectifs. C'est cohérent avec la crête non
jouée, tout aussi discrète. Lui donner sa propre couleur a été proposé
et écarté tant que ça ne gêne pas.

### Le glyphe au repos du transport, sous le seuil du texte

2,4:1 en clair, 3,1:1 en sombre sur le fond du lecteur. Le seuil de
4,5:1 vise le texte à lire ; un pictogramme dont le rôle est de dire
« pas ce sens-ci » n'a rien à lire. Monté d'un cran depuis 1,7 et 2,1,
où il ressemblait à un bouton désactivé. Le remonter encore le
rapprocherait du côté actif, qui plafonne à 4,0 en clair.

### Le volume prend 112 px à la timeline

640 → 508 px, soit 160 → 127 barres. Annoncé à ~90 px avant d'être
écrit ; le bouton et ses marges pèsent plus que je ne l'avais estimé. Le
levier le plus propre serait la piste à 3 rem au lieu de 4, mais elle
tomberait à 2,4 px par cran, sous le seuil que le test impose. Accepté en
connaissance de cause.

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

Dette ouverte par là : les 420 ms payées à la première écoute — voir la
section suivante, qui la clôt.

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

### L'import repensé — de `0408b57` à `aff4a2c`

Le compte rendu d'import était une page à part, atteinte après coup.
Il est devenu un onglet : un bouton, la liste de ce qui manque avec son
nombre et le nom de la playlist, des cases à cocher, un bouton de départ,
puis ligne par ligne ce que le CLI montre — les quatre barres d'étape, le
score Shazam nommé, l'erreur en clair, l'id et un lien vers la vidéo. Une
pastille sur l'onglet et un bouton d'arrêt suivent.

`report.html` a disparu avec. C'était le dernier point de « Reste à
faire » à côté du mode interactif : une page servie aux seules requêtes
non-HTMX de `/jobs/{id}/report`, pour qu'une URL de compte rendu mise en
favori réponde autre chose qu'un fragment nu. Il n'y a plus d'URL de
compte rendu, donc plus de page. **`console.html` est désormais le seul
document du projet** — tout le reste est fragment, `base.html` avait
déjà disparu.

Deux couches ont dû naître pour ça. `ProgressPort` avait des *étapes* —
une phase mesurée à la fois ; il a maintenant des *articles*, membres
d'un lot portant une identité (`item_listed`, `item_started`, `item_done`,
`item_failed`). Et `Job` a gagné `items`, une ligne par membre, à côté de
`current` qui ne portait que le dernier état.

Le chiffre qui a dicté la forme : un import de 34 morceaux produit plus
de **10 000 événements contre un anneau de 500**. Chaque frontière de
morceau du premier tiers était écrasée avant d'être lue. Les
pourcentages mettent donc `current` à jour en place et n'entrent jamais
dans l'anneau ; seules les transitions y vont.

Quatre bogues trouvés en s'en servant, pas en le lisant :

- **Décocher toutes les lignes importait tout.** Une case décochée
  n'envoie rien, donc un formulaire entièrement décoché est
  indiscernable d'un formulaire sans lignes — que le serveur lisait
  comme « aucune sélection donnée », c'est-à-dire tout ce qui manque. Un
  marqueur caché toujours envoyé dit maintenant qu'une sélection a eu
  lieu, fût-elle vide.
- **`KeyError('videoDetails')` n'était pas classé comme un refus**, donc
  n'était pas réessayé. Le retour dépendait de la propriété pytubefix lue
  en premier. Reclassé en `a462aa3`.
- **Un second import ne pouvait pas suivre le premier** (`b31124c`).
- **Appuyer sur Démarrer vidait la liste** qu'on venait de choisir
  (`aff4a2c`).

Trois tests se sont révélés creux à la contre-épreuve : la raison du job
de *check*, le garde `import:`, et d'où une ligne tire son nom.

### La marche à travers l'outil — `bf2f0a3` à `654126c`

L'UI a été parcourue comme un utilisateur la parcourt, chaque
fonctionnalité utilisée. Ce qui en est sorti, du plus grave au plus
petit : l'établi pouvait s'ouvrir sur rien et vous y enfermer ; le volet
des imports suivait le job le plus récent et non la playlist regardée ;
trois silences — des états où la page ne disait rien de ce qu'elle
faisait ; puis six points mineurs traités d'un bloc.

Un test de câblage n'aurait vu aucun des trois premiers : ils ne sont
visibles qu'en enchaînant les gestes dans l'ordre où on les enchaîne.

### Les surfaces — `75db91b` à `00bd28a`

Quelle colonne porte quel fond, et l'inversion volontaire entre les deux
palettes : sur un écran clair le contenu veut la surface la plus blanche
et le cadre la teintée, sur un écran sombre c'est le cadre qui se lève.
Les rôles (`--content-bg`, `--frame-bg`) sont ce qui permet de permuter
en un endroit au lieu d'un sélecteur sur deux.

Ont suivi : l'en-tête de la playlist rejoint le cadre de la liste, la
barre d'onglets ne peint plus rien, le lecteur perd sa règle du bas, et
les champs de saisie s'éclaircissent dans les deux thèmes.

### L'anneau de focus — `99646ca` à `f7b9554`

Parti d'une observation : les boutons `<<` et `>>` affichaient parfois
une bordure verte au changement de morceau. Cause réelle — Chrome ne
montre pas `:focus-visible` sur un clic pointeur, mais le révèle à la
frappe suivante. Le focus restait donc sur le bouton cliqué et
réapparaissait à la première touche.

`event.detail` est le nombre de clics et vaut **0** pour une activation
au clavier : c'est le discriminant qui permet de rendre le focus après
un clic pointeur sans rien casser au clavier (`99646ca`).

Puis l'anneau a été retiré partout sauf sur les champs, où il se dit par
la bordure accent et rien d'autre. Reste une exception, et c'est une
seule marche : Tab depuis le dernier champ tombe sur Save, dessiné à
l'intérieur du bouton dans la couleur de son texte — un anneau accent
sur un fond accent serait précisément celui qu'on venait de supprimer.

Deux pièges de CSS notés au passage : `outline-width: 0.5px` est arrondi
à `1px` par Chrome, il n'existe pas de contour plus fin ; et supprimer
une règle `:focus-visible` rend l'anneau par défaut du navigateur — il
faut écrire `outline: none`, pas effacer la règle.

### Le waveform, modèle SoundCloud — `6254ff0` à `fad3ef7`

Quatre changements, chacun mesuré au navigateur.

**Asymétrique.** Les barres partent d'une ligne de base à ~73 % de la
hauteur : la crête au-dessus, un reflet en dessous à 36 % de sa hauteur
et 55 % de sa couleur. Le bas n'est pas la moitié négative du signal —
les crêtes sont des valeurs absolues, il n'y en a pas. Un vrai tracé à
deux côtés dépenserait la moitié de ses pixels à répéter la forme du
dessus. Ce que le reflet achète en échange, c'est une ligne de sol : des
barres posées se comparent d'un coup d'œil, des barres flottant de part
et d'autre d'un milieu se comparent dans deux directions à la fois.

**Fluide.** Deux causes à l'à-coups. La frontière était arrondie à la
barre entière, donc immobile deux tiers de seconde puis sautait ; elle
est maintenant fractionnaire — la barre traversée est peinte deux fois,
la couleur jouée par-dessus l'autre à l'opacité de la fraction
parcourue. Et le repeint suivait `timeupdate`, qui ne tire que quatre
fois par seconde ; il suit `requestAnimationFrame` tant que ça joue.
Mesuré : **64 repeints/s en lecture, 0 en pause, 0,33 ms par repeint**.

**Rééchantillonné.** Le nombre de barres était figé à 400 et c'est leur
largeur qui absorbait la place : à 594 px, une barre d'un demi-pixel et
aucune gouttière. Inversé — la barre fait 3 px et le pas 4 px, c'est le
nombre de barres qui cède. Le maximum de chaque groupe, jamais la
moyenne : une moyenne noie une caisse claire dans le silence voisin.
Jamais plus de barres que de pics, sinon on dessinerait du détail que
personne n'a mesuré.

Le pas est **entier dès le calcul**. Arrondir le bord de chaque barre
rendait les bords nets mais pas l'espacement : la fraction accumulée
revenait d'un coup, un trou de 5 px toutes les 75 barres, et un seul
trou large dans un champ régulier est la première chose que l'œil
trouve. Mesuré aux colonnes du canvas, à cinq largeurs de 160 à 594 px :
**3 px de barre et 4 px de pas partout**, contre `{4: 143, 5: 2}` avant.
Le reste — moins d'un pas, donc au plus 3 px — est laissé au bord droit.

**Les temps dans la bande basse**, ce que l'asymétrie achetait en second.
La timeline y gagne les **72 px** qu'ils prenaient de part et d'autre.
Trois détails porteurs : positionnés hors flux même sans waveform, sinon
tout le contrôle bougerait à l'arrivée des pics ; un fond, parce que des
chiffres gris sur le reflet joué étaient illisibles ; et `z-index: 1`,
parce que `#seek` est positionné et vient après eux dans le markup — le
fond était peint puis recouvert. Le temps écoulé prend `--accent`, la
durée totale reste grise : l'un dit où on est et bouge, l'autre est une
propriété du morceau. Descendus d'un pixel ensuite (`d90c4e6`) : posés à
`bottom: 0` ils touchaient la ligne de base sous laquelle ils sont censés
pendre.

### Le transport — `d90c4e6` à `0881995`

**Plus gros.** `1,95 × 1,6 rem` → `2,5 × 2 rem`, soit 40 × 32 px contre
31 × 26 : +60 % de surface. Le glyphe passe de `--fs-sm` à `--fs-lg`,
12 px → 17 px. Le tout reste sous les 38 px du waveform, donc la rangée
du lecteur ne grandit pas — 74 px avant comme après, et un test l'exige
désormais explicitement. L'écart entre boutons passe de 4 à 6 px.

**Le sens de lecture, dit là où il se décide.** Un indicateur existait —
`NEXT ←` / `NEXT →` dans la barre d'outils — mais la barre est en haut de
page et le transport en bas : appuyer sur ⏮ retournait le lecteur avec
pour seul signe une flèche à trois cents pixels de la main qui venait de
le faire. `#transport` porte maintenant `data-direction`, écrit à un seul
endroit, juste à côté du libellé qui dit la même chose en mots ; un test
compte les écrivains, parce que deux auraient divergé. À l'arrêt
l'attribut est retiré : rien ne joue, il n'y a pas de parcours à
désigner.

**Trois passes sur la forme du signal**, chacune corrigeant la
précédente. D'abord la bordure du bouton actif seule : mais n'encadrer
qu'un des deux se lisait comme une différence de nature. Puis les deux
bordures en permanence et le glyphe en gris : mais gris contre vert dit
« désactivé », deux choses différentes, là où la paire est une seule
chose qui pointe dans un sens. Enfin un seul vert en deux forces —
`--accent-line` pour les cadres, `--accent-dim` pour le glyphe au repos,
`--accent` pour l'actif.

Les deux palettes prennent des alphas différents parce qu'elles n'ont pas
la même marge : contre le blanc, l'accent plein ne monte qu'à 4,0:1,
alors que contre la page sombre il atteint 9,2:1. Mesuré sur le fond du
lecteur, glyphe au repos contre glyphe actif : **2,4 contre 4,0 en clair,
3,1 contre 9,2 en sombre**.

Dette de bord, ouverte et refermée : une contre-épreuve a montré que
**rien ne vérifiait qu'une variable de palette existe dans les deux
thèmes**. Supprimer `--accent-dim` de la palette sombre ne cassait rien
de visible — le glyphe aurait simplement hérité de la valeur claire sur
la page sombre. Voir la section suivante.

### La parité des deux palettes n'était vérifiée par personne

Une variable définie dans un seul `:root` ne dit rien : l'autre thème
hérite simplement de la valeur qu'on lui a laissée, et un vert réglé pour
un écran clair atterrit sur un écran sombre sans que rien ne le signale.
Trouvé par contre-épreuve, pas par relecture.

La règle posée est mécanique, donc elle ne peut pas être oubliée : **une
variable dont la valeur est une couleur littérale demande une réponse
dans l'autre palette**. Les échelles — espacement, typo, tailles — et les
variables de rôle qui pointent vers d'autres variables sont partagées
exprès et en sont dispensées ; elles peuvent tout de même être redéfinies,
et deux le sont, ce qui est précisément ce qui permet aux deux surfaces
de permuter.

Vérifié sur l'état du jour : 55 variables côté clair dont 26 à valeur-
couleur, 28 côté sombre, aucune orpheline dans un sens ni dans l'autre.
Cinq contre-épreuves, dont une qui doit passer — ajouter une variable
d'échelle au seul bloc clair reste licite.

Le garde local qui avait été posé sur `--accent-dim` a été retiré : la
règle générale le dit de toutes les couleurs.

### La pochette en fondu enchaîné — `c0cd740` à `717a096`

Le panneau est remplacé en entier à chaque morceau, donc la pochette
sortante part avec lui et une transition n'a rien à quoi s'accrocher.
L'ancienne est conservée en `background-image` du conteneur le temps du
fondu et la nouvelle monte par-dessus : dissolution, pas carré vide.

Trois décisions portent le reste :

- **Une transition, pas des keyframes.** La règle
  `@media (prefers-reduced-motion: reduce)` en bas de la feuille
  neutralise les `transition-duration` ; une animation serait passée à
  côté. L'outil de navigateur n'expose pas cette préférence, donc c'est
  un test statique qui la couvre — le choix *et* l'existence de la règle
  dont il dépend.
- **Opaque par défaut, rendue transparente par le script.** Si rien ne
  tourne — pas de swap, une erreur, un navigateur qui n'émet pas `load` —
  la pochette est simplement là. L'inverse l'aurait laissée invisible.
- **Le hook est gardé.** Branché sans condition sur `htmx:afterSwap`, il
  tournait sur le poll des imports, une fois par seconde, sur du markup
  sans pochette.

La durée a été portée à 0,22 s puis 0,5 s puis 0,75 s — très long pour
cette feuille, où tout le reste est à un dixième de seconde, mais c'est
le seul endroit où la page demande à être regardée plutôt qu'utilisée.
Au passage, le délai avant d'effacer l'image du dessous était écrit en
dur à 400 ms : à 500 ms de fondu, l'ancienne aurait disparu **avant** la
fin, et la nouvelle aurait fini de monter au-dessus de rien. Le script
lit maintenant la durée dans la feuille, donc il n'y a plus deux nombres
qui doivent s'accorder — et en `prefers-reduced-motion` le nettoyage suit
tout seul.

Mesuré frame par frame : **783 ms sur 43 frames intermédiaires, zéro
frame vide**, image du dessous effacée 66 ms après la fin. Sur un swap
sans rapport, l'opacité reste à 1 sur 85 frames.

### La durée du morceau suivant — `d3cb1d0`

`NEXT → 2:52 June The Girl` est devenu `NEXT → June The Girl … 2:52`. Les
deux se lisent à des moments différents — le nom pour savoir ce qui
vient, la durée seulement si on hésite à la laisser passer — et dans une
même chaîne la durée se lisait comme un début de titre.

Le vrai point de conception n'était pas l'ordre mais **la troncature**.
Elle portait sur toute la boîte ; en mettant la durée en dernier, un nom
long l'aurait mangée, alors que la durée est la seule chose ici qui ne
s'allonge jamais. `#player-next` est donc devenu une rangée flex, l'ellipse
vit sur le nom seul et la durée est en `flex: 0 0 auto`. Vérifié au
navigateur : `nameClipped` et `timeVisible` vrais **en même temps**, ce qui
est exactement le cas qui posait problème.

### Le contrôle de volume — `a41ccbb` à `4cf7745`

Proposé avant d'être écrit, avec trois contraintes du projet posées
d'abord : les popups sont proscrits (la spec en autorise un), la largeur
de la timeline est disputée, et les contrôles sont dessinés et non laissés
au navigateur. Plus deux ressources libres : **↑ et ↓** — ← → font
morceau précédent/suivant, Espace lecture/pause, Tab ouvre la vidéo — et
le précédent `localStorage` du thème, note sur la navigation privée
comprise.

Retenu : le haut-parleur et une piste courte tout à droite de la rangée,
`flex: 0 0 auto` pour qu'ils ne reprennent jamais de la place à l'image.
À droite et non collés au transport, parce que le transport signifie
désormais « déplacement dans la file » depuis le marquage du sens.

**Crans de 5 %, pas de continu.** `#seek` mappe le clic directement sur la
durée parce qu'un pixel y désigne un instant demandé ; un niveau n'a
aucune valeur à atteindre exactement. Vingt crans de 3,2 px sont chacun
atteignables à la souris, et le même geste deux fois donne le même
nombre. C'est le pas entier du waveform à nouveau : un nombre rond vaut
mieux qu'un nombre juste. Un test refuse un pas qui ne divise pas 100 et
une piste trop étroite pour ses crans.

**Le silence est la sourdine, quel qu'en soit le chemin.** Ma première
version gardait deux états distincts, et glisser la piste à zéro laissait
le haut-parleur dire que le son était ouvert alors que rien ne sortait —
un second état identique au premier est un état sur lequel personne ne
peut agir. La sourdine conserve le niveau ; ce qui tombe à zéro est la
sortie, pas le nombre retenu. Et revenir de zéro n'ayant nulle part où
revenir, ça revient à un cran.

Une branche morte supprimée au passage : `setVolume` acceptait un second
argument `undefined` avec un commentaire décrivant un comportement
qu'aucun appelant ne déclenchait.

**Trois passes sur la forme**, chacune demandée après avoir vu la
précédente : le haut-parleur perd son cadre pour n'être plus que l'icône
(mais reste un `<button>`, sinon le clic ne serait pas atteignable au
clavier), le lavis de survol passe sur le groupe entier plutôt que sur
chaque moitié, l'icône prend `--fs-lg` — le jeton du transport, parce
qu'elle sortait un tiers plus petite que les flèches d'à côté — et la
piste emprunte les deux verts de l'image en thème clair.

Ce dernier point a été **mesuré et non deviné** : les pixels du canvas
disent que la timeline claire ne peint que deux verts, `#3fb5a1` pour la
crête et le même à 55 % pour le reflet ; le côté non joué est gris. La
piste prend le premier tel quel pour son remplissage, et **45 %** pour sa
moitié vide — plus clair que le reflet, parce que le reflet se lit contre
des barres du même vert et n'a qu'à être plus discret qu'elles, alors que
ceci est la moitié vide d'une piste et doit se lire comme vide.

D'où deux rôles, `--level` et `--level-rest`, assignés différemment par
palette comme `--content-bg` / `--frame-bg` — en sombre l'accent appartient
déjà à la famille de l'image et il n'y avait rien à réconcilier. Et un
`color-mix` plutôt que les canaux réécrits, qui auraient dérivé le jour où
`--wave-played` bouge.

Mesuré au navigateur, geste par geste : clics à 60/62/63 % → 60, 60, 65 ;
↑↓ partout dans la page, et un champ de saisie qui garde ses flèches ;
↑ sur la piste focalisée **sans changer de morceau** ; sourdine 70 → 0 →
70 ; glissé à zéro puis clic → 5 ; niveau inchangé au changement de
morceau et relu au rechargement, un zéro stocké restant un zéro.

### Ce que Shazam disait déjà et qu'on jetait — `9e3536f`

Une reconnaissance réelle sur un morceau du dépôt, dévidée en structure,
a montré qu'on ne lisait **trois champs** de la réponse : le titre, le
sous-titre et une URL de pochette. Sont désormais gardés l'album, le
label, l'année et le genre.

Dans les trames ID3 **standard** — `TALB`, `TPUB`, `TDRC`, `TCON` — et non
dans des `TXXX` maison : tout lecteur et toute bibliothèque savent déjà
les lire, c'est à ça qu'elles servent. Appliqués au même seuil que
l'artiste et le titre, et sans copie « rejetée » à la façon de
`shazam_artist` : personne ne juge un nom d'album contre un titre de
vidéo YouTube, donc une copie refusée serait quatre trames sans lecteur.

Deux pièges que la mesure a levés :

- **Shazam envoie des espaces insécables** dans les noms d'album —
  `X:\xa0The Godless Void`. Elles survivaient jusqu'à la trame puis
  jusqu'à toute recherche qui attend une espace. Normalisées comme le
  sont déjà l'artiste et le titre.
- **Le champ s'appelle `publisher`, pas `label`.** J'ai d'abord cru à une
  collision dans `SongModel` et je me suis trompé — `self.label` y
  appartient à `ProgressBarInterface`. Mais le nom reste juste pour la
  vraie raison : `SongSummary.label` est la ligne « artiste - titre » que
  trois gabarits lisent, et la collision aurait atterri **là**, où rien du
  côté modèle n'aurait paru anormal.

Les rangées de `sections[0].metadata` sont lues **par leur `title`** et
chacune est optionnelle : c'est de la copie d'affichage, ordonnée comme
Shazam l'entend, pas une interface.

Vérifié sur un vrai MP3 : les quatre trames écrites, relues à l'ouverture
suivante, effacées par `reset_state`, **et le fichier n'a pas grossi d'un
octet** — le padding ID3 a absorbé, comme pour les crêtes du waveform.

### La ligne à deux faces — `503fb06` à `d5dc369`

Deux lignes sous le titre, c'était une de trop. Il n'en reste qu'une : la
playlist toujours, la sortie Shazam quand il y en a une, dix secondes
chacune. La durée du morceau est partie avec la seconde ligne — la rangée
de la liste et le lecteur la portent déjà.

**Split-flap, comme un tableau d'aéroport.** Chaque caractère a sa fente,
qui bascule depuis son propre bord haut avec 18 ms de décalage sur la
précédente. Deux traits fidèles au mécanisme réel : une fente qui affiche
déjà le bon caractère **ne tourne pas**, et la face la plus courte est
complétée d'espaces pour que les fentes ne bougent jamais.

**Le caractère arrive dans l'accent et refroidit** vers le gris de la
ligne en 0,6 s, contre 0,09 s pour la bascule. C'est l'écart qui rend le
changement lisible après coup. Difficulté : `color` étant transitionnée,
mettre l'accent l'aurait *animée vers* le vert et la frappe serait
arrivée après la fermeture du volet — d'où le retrait de `color` de
`transition-property` le temps que la classe est posée. Pas
`transition: none`, qui aurait emporté la bascule avec elle.

Transitions et non keyframes, encore : la règle `prefers-reduced-motion`
neutralise les durées et une animation serait passée à côté.

Trois choses que la mesure a imposées et qui ne se voyaient pas sur le
papier :

- Les espaces de remplissage sont **réels**, donc tout ce qui partageait
  la ligne *après* le tableau flottait à 473 px sur la droite. Le compteur
  de l'établi et l'avertissement « unsaved edits » sont passés **avant**,
  et un test l'exige.
- Le point médian de l'établi devenait orphelin quand le compteur est
  vide. Il appartient maintenant au compteur
  (`#workbench-position:not(:empty)::after`), pas au gabarit.
- Une bascule en vol doit savoir qu'elle est **périmée**, sinon un morceau
  changé en pleine rotation finit d'épeler le précédent.

Mesuré : bascule à 3349 puis 8348 ms — l'intervalle exact ; mi-bascule le
texte lit `"Kingdom of Wes - What I listen now"`, les deux faces
entrelacées ; au changement de morceau l'horloge repart (swap à 8532 ms →
bascule 5002 ms plus tard) ; et **aucune horloge** pour un morceau sans
seconde face. Le refroidissement relevé fente par fente :
`rgb(70, 201, 177)` posé d'un coup, puis jusqu'à `rgb(102, 113, 111)` en
~540 ms.

`fadeMillis` est devenu `transitionMillis` au passage : il sert au fondu
de la pochette *et* au point de bascule des fentes, et « fade » était
devenu faux.

### Le rattrapage des 804 — `a9164eb`, `13bed8c`

Un script hors du paquet, `scripts/backfill_shazam_data.py` : c'est une
opération qu'on fait une fois, pas une fonctionnalité. Il comble deux
manques historiques d'un seul appel par morceau — les données de sortie,
jamais lues avant qu'elles n'existent dans le modèle, et les trames de
provenance `Shazam *`, arrivées dans le CLI le **4 mai 2025**.

**Ce qu'il ne fait pas est le cœur du sujet.** Il n'appelle pas
`shazam_song()`, qui réapplique tout le match : sur un bon score cette
méthode réécrit artiste, titre, pochette et renomme le fichier. Passée
sur huit cents morceaux corrigés à la main depuis, elle aurait défait ce
travail en silence. Le script pose la même question et n'écrit que ce qui
manque.

Le calcul de correspondance a donc été **extrait du modèle** en
`SongModel.match_score`, pour qu'il n'existe pas deux réponses à la même
question. Vérifié équivalent à l'ancien calcul inline sur **500
comparaisons, 0 écart**, avec de vraies paires du dépôt croisées entre
elles — la suite verte ne prouvait rien, elle l'était déjà avant.

**Le filtre d'entrée n'est pas la provenance.** C'est l'erreur qui a rendu
mon premier compte faux d'un facteur sept : l'absence de
`TXXX:Shazam artist` ne dit pas qu'un morceau n'a jamais été reconnu, elle
dit qu'il a été importé avant mai 2025. Ce qui subsiste, c'est l'URL de
pochette : Shazam sert son visuel depuis le CDN d'Apple, et une vignette
`i.ytimg.com` signifie qu'il n'a jamais matché. 800 morceaux portaient une
pochette `mzstatic.com`.

**Le réessai s'est révélé décisif.** Un essai à blanc sur vingt morceaux a
rendu deux `FailedDecodeJson` — des refus de Shazam, pas des problèmes de
fichier. Le modèle répond à un refus en attendant 35 s et en redemandant
une fois ; le script ne le faisait pas. Sur la passe complète, le rythme
observé (21,4 s contre un plancher de 15) implique **environ 120
réessais**, soit près d'un morceau sur cinq — et la colonne des échecs est
restée à **zéro pendant cinq heures**. Sans lui, 15 % de la bibliothèque
aurait demandé une seconde passe.

Résultat de la passe, seuil à 75 %, 4 h 47 :

| | |
|---|---|
| remplis | 791 |
| écartés par le seuil | 13 |
| sans réponse | 0 |
| échecs | 0 |

Vérifié indépendamment du journal sur les 944 fichiers : **aucun
illisible**, les 944 pochettes embarquées intactes, les 533 trames de
crêtes intactes. `TALB` est passé de 9 à 771, la provenance de 130 à 823.

Deux écarts qui ne sont pas des défauts. **29 morceaux confirmés à 100 %
n'ont reçu aucun nom d'album**, parce que Shazam n'en fournit pas — pas de
rangée « Album » dans sa réponse, ce qui est le cas des singles non
rattachés, des remixes et des live. D'où `TCON` à 797 contre `TALB` à 771 :
le champ absent n'est pas perdu, il est inconnu.

Et les **13 écartés forment une catégorie, pas un bruit** : remixes,
teasers, albums complets. Dans les trois cas l'audio n'appartient pas à la
sortie que le fichier revendique, Shazam le reconnaît à juste titre comme
autre chose, et écrire cet album serait faux. Deux cas nommaient même le
bon artiste et un autre morceau — un teaser de mind.in.a.box, un album
entier de Jean Leloup.

Le seuil de 75 a été choisi sur la distribution mesurée, très nette :
sur les 791 remplis, **plus de 770 à 100 %**. Il a évité deux écritures
fausses que le défaut de 50 aurait laissé passer, dont une à exactement
50 % — la comparaison étant `score < seuil`, un 50 pile est accepté à 50.

Un des treize a été tranché à la main : *The Power* de Snap!, que Shazam
attribuait à Chill Rob G. Ce n'était pas un faux positif — le fichier
porte la version de la bande originale de *The Fisher King*, et il a été
retagué d'après la référence Apple, renommage compris.

### Sauvegarder sans toucher la pochette effaçait son URL — `7bdaa21`

Trouvé en cherchant par quel chemin retaguer un morceau à la main, pas en
relisant le code. `apply_fix` passait `cover_art_url or None` à
`update_state`, où `None` veut dire « effacer » : laisser le champ COVER
vide dans le formulaire **supprimait la trame `TXXX:Cover art URL`**.

Ce qui le rendait invisible : l'image embarquée est une autre trame et
survivait. Mesuré sur une copie, 88 585 octets avant et après. Le panneau
avait donc l'air juste pendant que le fichier perdait le seul endroit où
était noté d'où venait cette image. Et le champ promet « leave empty to
keep the current one » : la promesse était tenue à l'écran et rompue sur
le disque.

**Les conséquences étaient modestes, et une première version de cette
entrée les a exagérées.** L'URL ne s'affiche nulle part — le champ n'est
pas pré-rempli — donc rien ne changeait à l'écran. Le seul effet
fonctionnel : `update_cover_art` ne retélécharge pas une pochette dont
l'URL demandée égale celle déjà notée, et sans la note cette optimisation
perd la mémoire. Quelques dizaines de kilo-octets retéléchargés pour
rien, pas une image perdue.

J'ai soupçonné bien pire, à tort. `update_cover_art` commence par « si
pas d'URL, supprime la pochette », ce qui laissait craindre qu'un fichier
amputé de son URL perde son image au prochain passage. Les sept appelants
vérifiés un par un : tous positionnent une URL non vide juste avant, ou se
gardent par `if cover_art_url:`. **Aucun chemin ne pouvait atteindre cette
branche à cause du bug.** Ce qui était vraiment perdu, c'est la
provenance — la même catégorie que ce que le rattrapage venait de réparer
pour les champs Shazam, et la raison de corriger malgré la faible gêne.

`update_state` distinguait déjà « effacer » de « ne pas y toucher »,
`None` contre `False` ; l'appel passait simplement le mauvais des deux.
Le correctif est ce mot-là.

La pochette est l'exception, pas la règle : un artiste ou un titre vide
veut bien dire vide, puisqu'un morceau sans ni l'un ni l'autre est
exactement ce qu'est un junk. Deux tests tiennent les deux moitiés du
distinguo, et la contre-épreuve les vérifie dans les deux sens — remettre
`None` sur la pochette, ou mettre `False` sur les noms.

### La pochette ne se mettait jamais à jour — `d4f23f2`, `a5c52d1`, `fa71f4e`

Signalé comme « l'image affichée ne change pas quand on modifie son URL ».
La reproduction a montré **deux** défauts, dont le second beaucoup plus
grave que le symptôme.

**Le navigateur resservait son cache.** `/songs/<id>/cover` est une
adresse immuable et la réponse ne porte ni `ETag`, ni `Last-Modified`, ni
`Cache-Control`. La date du fichier est désormais dans l'adresse
(`?v=…`). Elle bouge aussi lors d'écritures sans rapport — une balise,
les crêtes — et la pochette est alors refetchée pour rien : quelques
dizaines de kilo-octets en local contre une image périmée.

**Mais la pochette n'était jamais retéléchargée non plus.** `apply_fix`
appelait `update_state` d'abord, ce qui écrit la nouvelle URL dans le
fichier ; puis `update_cover_art` décidait de télécharger **en comparant
l'URL demandée à celle du fichier**, que `update_state` venait d'y
écrire. Toujours égales. Mesuré : **trois sauvegardes, trois URL
différentes, trois URL mises à jour, zéro téléchargement.**

La pochette est maintenant récupérée **avant** l'écriture des noms, ce
qui rend l'opération tout ou rien : une pochette introuvable laisse le
morceau intact, là où l'ancien ordre laissait un fichier annonçant une
image qu'il n'avait jamais reçue.

**Deux défauts de fond trouvés en cherchant l'origine.**

`has_cover_art` lisait `tags["APIC:Cover art"]` — l'image *appelée* ainsi.
Une trame APIC porte pourtant deux choses : un `type` normalisé (3 = face
avant) et une `desc` en texte libre inventée par qui l'écrit. Le
programme lisait le surnom. **105 fichiers** portant `Stored cover art`,
posé par une version antérieure au dépôt, étaient donc comptés comme
dépourvus de pochette — et `list-junks` signale un morceau sans pochette.
La recherche porte désormais sur le type : **105 → 0**, sans toucher un
seul fichier.

Et le record d'origine a été rétabli. L'ancien CLI gardait **deux** URL —
celle demandée et celle d'où venait l'image embarquée — et comparait
contre la seconde. Le refactor a continué de l'écrire mais s'est mis à
comparer contre la première. Pire, `update_id3_tags` efface toutes les
`TXXX` avant de réécrire celles qu'il connaît, et celle-là n'en était
pas : **un fichier sur 944 la portait encore**. Rétablie aux trois
endroits — lecture, comparaison, réécriture — et mesurée : cinq
sauvegardes, deux téléchargements, exactement ceux où l'URL changeait.

### L'id YouTube logé dans le numéro de piste — `2459840`

Relevé en dressant la topographie des balises. **659 fichiers** portaient
leur id vidéo dans `TRCK`, la trame que l'ID3 définit comme le numéro de
piste — posé par une version antérieure au dépôt, jamais relu depuis :
`TRCK` n'apparaît dans aucun commit des deux dépôts. Inerte du point de
vue de l'outil, mais pas du point de vue des lecteurs : tout logiciel
affichant un numéro de piste montrait `QxdSAAWRs3E`.

La règle de suppression est étroite, et c'est le point : une `TRCK` n'est
retirée que si sa valeur **est exactement l'id du morceau**. Pas « onze
caractères », pas « ressemble à un id ». Aucun des 944 ne portait de vrai
numéro de piste, mais un script qui les aurait détruits aurait été faux
même en ne détruisant rien ici.

Après passage, vérifié indépendamment du script : **0 `TRCK`, 944
`TXXX:YouTube ID`, 944 pochettes, 0 fichier illisible, 944/944 dont le
modèle lit l'id.**

### Le code d'enregistrement, jeté à chaque réponse — `9fba802`, `05f0bfc`

Shazam renvoie un ISRC sur chaque réponse. Rien ne le lisait : avant
cette correction, **aucun des 944 fichiers ne portait de trame `TSRC`**,
alors qu'ID3 a la trame standard et que tout lecteur sait la lire.

Ce n'est pas un identifiant de plus. Un ISRC désigne **un
enregistrement**, pas une chanson ni un disque : deux prises de la même
pièce ont deux codes. C'est donc la seule donnée qui sépare un remaster,
un live ou un remix de l'original — exactement l'ambiguïté qui a laissé
treize morceaux inconfirmables lors du rattrapage, et exactement le cas
de *The Power* de Snap! contre celle de Chill Rob G.

Il rejoint album, label, année et genre : extrait de `track.isrc`, lu à
l'ouverture, écrit dans `TSRC`, effacé par `reset_state`. Le critère du
rattrapage s'élargit en conséquence — un morceau complet par ailleurs
mais sans code redevient candidat, ce qui était le cas des 944 avant
l'essai décrit ci-dessous, et l'est de 942 depuis.

La passe n'a pas été relancée. Chacune coûte cinq heures et huit cents
requêtes ; en lancer une pour l'ISRC puis une autre pour ce qui manquera
encore serait payer deux fois. Un essai réel sur trois morceaux a servi
de vérification : comparés à la sauvegarde de leurs balises, la **seule**
différence est l'ajout de `TSRC` — artiste, titre, album, label, année,
genre et pochette identiques à l'octet près.

Deux fausses alertes lors de cette vérification, levées en consultant la
sauvegarde plutôt qu'en supposant : un `TPE1` surprenant qui était déjà
là, et une recherche par nom de fichier qui échouait parce que macOS
stocke les noms en **NFD** — `E` suivi d'un accent combinant — quand le
littéral était en NFC.

## En cours — le document par morceau

Construit sur la branche `metadata-document`, **fusionné dans `main` en
`bf34c7c`** : neuf fichiers ajoutés, trois modifiés. La branche avait
commencé à quatre ajoutés et zéro modifié — tant que seuls des scripts
écrivaient le document, `main` pouvait l'ignorer entièrement. C'est le
modèle qui s'y est mis qui a fait tomber ce zéro.

Le merge ne change **que ce qu'une sauvegarde écrit**, pas ce qu'une
ouverture lit : la bascule de la lecture est un commit à part, donc
révocable à part. Ce qui l'autorise est une mesure et non un pari — sur
toute la bibliothèque, le document et les trames disent la même chose
des sept champs : **944/944, zéro divergence, zéro document manquant,
zéro illisible**. Seule exception, deux `TSRC` que le document ne porte
pas encore ; ils se répareront à la prochaine sauvegarde de ces fichiers.

### Pourquoi

Cinq défauts de stockage en une seule journée, et chacun est le
représentant d'une *classe* de défaut :

| ce qui a cassé | la règle absente |
|---|---|
| 105 fichiers vus sans pochette | identifier une trame par son sens, pas par son étiquette libre |
| une trame perdue sur 943 fichiers | ne supprimer que ce qu'on possède |
| trois générations de noms cohabitantes | versionner et migrer |
| l'id vidéo dans `TRCK` sur 659 fichiers | une donnée privée dans une trame privée |
| demandé et obtenu dans une même URL | une décision n'est pas une preuve |

Et un sixième, celui-là **en cours** au moment où on l'a constaté : à
chaque import, `author` et `title` de YouTube sont écrasés par la
première correspondance Shazam qui franchit le seuil, sans copie. Sur 944
morceaux, **715** portent le nom donné par Shazam et l'original est
perdu. Ce n'est pas une dette qui attend, c'est une perte qui se produit,
et qu'aucune migration ultérieure ne réparera — la vidéo aura peut-être
disparu.

### Ce qui est fait — `6775f27`, `3def1b8`, `055b1b3`

**`libs/metadata.py`** — un document JSON par morceau, dans une trame
`PRIV`. Trois blocs pour trois questions : `fields` (ce que le fichier
affirme, chaque valeur portant qui l'a décidée et quand), `sources` (ce
que chaque fournisseur a répondu, gardé verbatim et jamais écrasé),
`embedded` (ce que le fichier contient réellement — l'empreinte de
l'image, pas l'URL).

Le choix de la trame n'est pas cosmétique : `song.py` efface `TPE1`,
`TIT2`, les quatre trames de sortie, toutes les `TXXX` et toutes les
`APIC`, **jamais de `PRIV`** ; et `store_peaks`, qui en efface pourtant,
remet celles qu'il ne possède pas. Vérifié sur un vrai fichier avant
d'écrire une ligne : le document survit à `update_state`, à
`store_peaks`, et à une seconde sauvegarde.

La version est **dans** le document et non dans le propriétaire, à
l'inverse des crêtes (`#peaks-1`) — et c'est délibéré : un cache dont le
format change se jette et se recalcule, un registre doit se migrer, donc
un lecteur doit pouvoir le trouver quelle que soit sa version. Lire une
version inconnue lève une exception plutôt que de deviner.

**`libs/legacy.py`** — lit les trois générations de trames et en fait un
document, ISRC compris depuis `TSRC` : seul Shazam en fournit, donc un
fichier qui en porte un porte celui de Shazam. Il n'écrit rien :
construire et ranger sont deux actes séparés, pour qu'une passe de
comparaison puisse les tenir côte à côte sans toucher un fichier.

Sa colonne la plus intéressante est celle qu'il ne remplit pas. Une seule
attribution est certaine — la valeur égale ce que Shazam a proposé *et*
le score a franchi le seuil. Tout le reste est marqué `legacy`, y compris
les valeurs venues manifestement de YouTube : « manifestement » n'est pas
un enregistrement, et une correction faite à la main y est
indiscernable de l'original. Sur 944 morceaux : **753 artistes et 773
titres attribués à Shazam, tout le reste `legacy`**, horodatages nuls
partout — la date du fichier a été déplacée par les crêtes et par deux
passes de réparation, l'écrire serait un mensonge.

**`scripts/build_metadata_documents.py`** — construit, compare, et
n'écrit que sur `--write`. Sa règle de fusion tient en trois cas : un
champ marqué `user` n'est jamais écrasé (une reconstruction ne peut
produire que `shazam` ou `legacy`) ; une valeur inchangée garde l'entrée
qui connaît son instant ; tout le reste suit les trames, qui restent la
source de vérité tant que l'application les écrit.

### Où on en est

Les 944 documents sont écrits. Médiane **907 octets** à ce stade — 1056
depuis que le bloc `youtube` s'y ajoute — soit 0,9 Mo pour toute la
bibliothèque contre 58,6 Mo de balises. Relus intégralement : 944/944,
aucun illisible, pochettes et crêtes intactes. Seconde passe : **944
« matches the frames », 0 écrit** — l'idempotence tient sur la vraie
bibliothèque et pas seulement en test.

À ce stade l'application ignore tout du document et répond comme avant.
Elle l'écrit depuis `dc1cfae`, et le lit depuis `2a5bf73`.

### L'origine YouTube, récupérée avant de la perdre — `6d34c75`

Le manque le plus grave de l'inventaire, et le seul qui **se dégradait**.
L'import prend quatre choses à la vidéo — id, chaîne, titre, vignette —
et en confie trois aux champs que Shazam écrase ensuite, sans copie. Sur
944 morceaux, 715 portaient le nom donné par Shazam et l'original n'était
plus dans le fichier.

Deux constats ont renversé le calendrier prévu. D'abord le coût :
l'endpoint **oEmbed** de YouTube répond en 0,12 s, sans clé, sans verrou
et sans bibliothèque, et rend `title` et `author_name` — c'est-à-dire
exactement `video.title` et `video.author`. Les 944 morceaux prennent
deux minutes, pas cinq heures. Ensuite l'urgence : un échantillon de 60
a trouvé deux vidéos déjà supprimées. Un ISRC ne s'évapore pas, une
vidéo supprimée si — cette passe-là ne pouvait pas attendre la passe
globale.

**Résultat : 933 origines récupérées, 11 disparues** — 6× 404, 4× 403,
1× 401. Le réel (1,2 %) est plus doux que mon estimation (3,3 %), ce que
je note parce que j'avais avancé le chiffre.

**652 des 933 diffèrent de ce que le fichier affiche.** C'est la mesure
directe de ce que Shazam avait effacé. Les 281 autres coïncident : ce
sont les morceaux jamais reconnus, dont les noms venaient déjà de
YouTube.

Le bloc a **trois états**, et le troisième est sa raison d'être :

    {}                                     jamais demandé
    {"at": …, "author": …, "title": …}     demandé, répondu
    {"at": …, "gone": true, "http": 404}   demandé, la vidéo n'y est plus

Sans lui, chaque passe future réinterroge les mêmes vidéos mortes et
échoue pareil, sans distinguer « pas encore fait » de « impossible ». Le
code HTTP est gardé parce qu'ils ne disent pas la même chose : un 404 est
une suppression, un 401 une vidéo passée en privé, un 403 un blocage
régional — les deux derniers peuvent se rouvrir, d'où `--retry-gone`.

Quatre règles portent le reste. Un échec réseau n'est **pas** une
disparition : seuls 400, 401, 403, 404 et 410 sont enregistrés, un 500
ne laisse rien et le morceau reste candidat. Le suffixe « - Topic » des
chaînes automatiques de YouTube est conservé tel quel, parce que ce bloc
est une preuve et que le rogner serait trancher au mauvais endroit. Rien
n'est écrit dans les trames — aucune trame standard ne porte ça, et
inventer des `TXXX` est l'arrangement que cette branche quitte. Et la
reprise ne tient à aucun fichier d'état : ce que le document porte *est*
le registre de ce qui a été fait, ce qu'une seconde passe a confirmé —
944 « already known », zéro requête.

Un exemple qui éclaire rétrospectivement le rattrapage : l'*Ave Maria*
écarté à 68 % vient d'une chaîne nommée `ELITEXardas00`, sous le titre
« Franz Schubert - Ave Maria (Instrumental) ». Le fichier annonce André
Rieu ; l'origine ne le dit nulle part. Shazam y entendait autre chose,
et pour cause.

### Le modèle écrit son document — `dc1cfae`

Jusqu'ici le document était l'œuvre d'un script : une passe, un instant,
944 fichiers. À partir d'ici c'est le modèle qui l'écrit, à chaque
sauvegarde, pour le morceau qu'il a en main. Cette étape ne fait pas lire
le document — à ce stade rien ne le lit, les trames restent la vérité, et
la lecture ne bascule que deux commits plus loin. Ce qu'elle fait, c'est
l'empêcher de prendre du retard.

**Une seule écriture.** Le document est attaché aux trames avant
`mp3.save()`, pas après. Deux sauvegardes successives laisseraient une
fenêtre où les trames et le document se contredisent, et doubleraient
les entrées/sorties de la moindre correction.

**Une valeur inchangée garde son entrée.** C'est la règle qui porte tout
le reste. Réécrire `artist` avec la même chaîne remplacerait un vrai
moment — quand la valeur a été décidée, et par qui — par celui de la
sauvegarde en cours. Le document perdrait la seule chose que les trames
n'ont jamais portée, et il la perdrait à chaque passage, sans rien
signaler.

**Qui décide voyage avec la valeur.** `update_state(..., by=…)` pose
`_setter`, et les champs modifiés dans la foulée le portent. L'établi
passe `by="user"`, la reconnaissance `by="shazam"`, l'import
`by="import"` ; par défaut, `legacy` — l'aveu qu'on ne sait pas, et non
une affirmation fausse.

**Un document illisible n'est pas écrasé.** `_document()` rend `None`
quand le fichier porte un document que ce build ne sait pas lire : une
version plus récente, ou une trame abîmée. Les deux autres conduites
étaient pires. L'écraser détruirait ce qu'un build plus récent savait —
exactement le mécanisme qui a produit trois générations de noms de
trames Shazam coexistant dans la bibliothèque. Refuser la sauvegarde
casserait l'application pour une ombre que personne ne lit. Ne rien
faire ne fait ni l'un ni l'autre : les trames passent, le document
attend un build qui le comprenne.

### Ce que Shazam donne et qu'aucune trame ne pouvait porter — `f94eca7`

Les cinq éléments que la réponse contenait et que l'inventaire listait
comme ignorés sont désormais dans `sources.shazam` : `key` et `url` (la
fiche Shazam), `apple_album` et `apple_artists` (les identifiants Apple,
la clé d'entrée d'iTunes — celle qui a servi à retaguer *The Power*),
`colors` (la palette extraite de la pochette). Aucun n'a de trame ID3 où
aller ; c'est précisément ce que le document rend possible.

Deux comportements, et la distinction est le cœur de l'affaire. Une
**nouvelle reconnaissance** remplace le bloc : ce que la réponse
précédente nommait porte sur un morceau que celle-ci ne reconnaît
peut-être pas — vérifié sur un vrai fichier, où `apple_album` disparaît
bien quand la seconde réponse n'en a pas. Une **sauvegarde ordinaire**
fusionne : elle n'a aucune réponse à elle, et remplacer le bloc
laisserait tomber les identifiants et la palette, qui ne vivent que là
et qu'il faudrait cinq heures de passe pour retrouver.

Une valeur vide n'écrit pas sa clé, et un bloc vide n'efface pas ce
qu'une réponse antérieure avait consigné.

**Ce que la contre-épreuve a trouvé — `cf8a60e`.** Cinq altérations,
quatre rouges, une verte : supprimer la ligne de `shazam_song()` qui
relève les identifiants n'a rien cassé. Les treize tests posaient
`_shazam_extras` à la main et vérifiaient la mécanique sans jamais
vérifier le câblage. Le test manquant fait tourner `shazam_song()` sur
un client factice et lit le document du fichier ; l'altération refaite
échoue comme elle devait.

### La bascule de la lecture — `2a5bf73`

Le modèle interroge le document, et les trames seulement à défaut. C'est
le commit qui change qui l'on croit.

**La mesure d'abord.** Sur les 944 morceaux, le document et les trames
disent la même chose des sept champs : zéro divergence, zéro document
manquant, zéro illisible. C'est ce qui autorise la bascule — sans cette
mesure, elle aurait été un pari. Après bascule : **944 ouverts, zéro
erreur, zéro fichier réécrit** ; ouvrir ne modifie rien, ce qui est la
propriété à laquelle on tient le plus ici.

**Ce que la bascule récupère au passage : 135 attributs.** Ce ne sont pas
des valeurs nouvelles, ce sont des valeurs que le lecteur de trames ne
voyait plus — 55 artistes Shazam, 55 titres, 18 scores, 5 pochettes,
rangés sous des noms d'anciennes générations. `legacy` sait les lire, le
modèle ne savait plus les trouver. La panne que le document devait clore
était donc encore ouverte, et sur 135 cas ; elle se referme ici. Trois
vont dans l'autre sens — deux codes d'enregistrement et une origine de
pochette —, réparés à la prochaine sauvegarde de ces fichiers.

**Une lecture de trame survit**, et ce n'est pas une lecture de
métadonnée : savoir si le fichier porte la trame d'id est ce qui reconnaît
un téléchargement pas encore taggé, et c'est ce qui déclenche son
tagage. Poser la question au document aurait répondu « déjà taggé » pour
un fichier qui ne porte aucune trame, puisque le repli passe par le nom
de fichier. La contre-épreuve l'a confirmé : 37 tests tombent quand on
interroge le document à cet endroit.

**Les trames continuent d'être écrites.** `TPE1`, `TIT2`, `TALB`, `TPUB`,
`TDRC`, `TCON`, `TSRC`, `APIC` sont la surface d'interopérabilité : tout
lecteur audio les lit, et les retirer abîmerait la bibliothèque en dehors
de l'outil. Ce que le programme a cessé de faire, c'est de les croire.

Deux choses que la bascule a rendues porteuses, et qui ne l'étaient pas.

**L'URL est revenue à côté de l'empreinte.** `embedded` ne portait que le
SHA-256 des octets. C'est le fait, et il survit à la mort de l'URL — mais
il ne répond qu'une fois les octets en main, c'est-à-dire après avoir payé
le téléchargement que la question sert justement à éviter. Il fallait les
deux : l'empreinte parce qu'elle ne ment pas, l'URL parce qu'elle est la
seule réponse bon marché. Une seule trame `Stored cover art URL` existait
encore dans toute la bibliothèque, donc la bascule ne perd presque rien :
un morceau paiera un téléchargement de trop, une fois.

**Junkiser laissait le document debout.** Les trames étaient effacées, le
document non, donc la réouverture relisait le nom dedans et le morceau
n'était plus junk du tout. Bug créé par la bascule, trouvé avant de
livrer, en cherchant précisément ce que la bascule rendait critique.
`reset_state` le signale maintenant et le document suit. Survivent l'id
et `sources.youtube` : l'origine est irremplaçable une fois la vidéo
partie — c'est ce qu'une passe entière a servi à sauver — et ce n'est pas
une conclusion qu'on a tirée sur le morceau. `embedded` n'est pas traité
à part : il décrit ce que le fichier porte, et tant que la pochette n'est
pas retirée, il la porte encore.

**Onze contre-épreuves, quatre passées à tort.** Elles sont racontées
plus bas, avec le reste de ce que la méthode a coûté.

### Ce qui reste

**Retirer les sept `TXXX` devenues redondantes** — les quatre de Shazam,
les deux de pochette, celle de l'id. Elles ne sont plus lues ; elles sont
encore écrites, volontairement, parce qu'elles sont le chemin de retour.
C'est **le seul geste irréversible** de toute l'opération, et il n'y a
aucune raison de le presser.

**Ce que la console lit.** Le document porte trois choses qu'aucune trame
ne portera jamais : l'origine YouTube, la provenance de chaque valeur, et
les identifiants Shazam. C'est la réponse laissée en suspens à la question
de l'UI — quatre champs de plus dans le formulaire de l'inspecteur
seraient redondants avec la ligne sous le titre ; ces trois-là ne le sont
pas.

**La passe Shazam globale**, qui n'attend plus rien : l'inventaire des
données est clos, et elle écrira désormais dans le monde d'après. Côté
YouTube, oEmbed ne rend que la chaîne et le titre ; `publish_date`,
`length`, `description` et `keywords` demanderaient une requête plus
lourde et n'ont pas été jugés nécessaires.

## Méthode — trois échecs de procédure, et ce que les contre-épreuves ont appris

Le document dit ailleurs qu'aucune page n'avait jamais été rendue par un
navigateur. Trois autres angles morts ont été trouvés depuis, tous par
leurs conséquences et non par relecture.

**La suite de tests atteignait le réseau.** Nommer chaque morceau
manquant dans le check envoyait une requête YouTube par morceau ; les
tests concernés sont passés d'instantanés à plusieurs secondes et ont
commencé à échouer sur leurs propres budgets d'attente. Rien ne le
disait : `Playlist` était patché, `YouTube` non. Mesuré à **quatre
connexions réelles vers Google pour un check de deux morceaux**. Un
`conftest.py` refuse maintenant toute connexion non-loopback.

**Trois commits sur une suite rouge.** Cause unique : `pytest … | grep …`
masque le code de sortie, donc le `&&` qui suit voit un succès. Le
commit est désormais conditionné au code de sortie de pytest lui-même,
la sortie allant dans un fichier.

**Cinq destructions de travail non commité par `git checkout`.** À chaque
fois pendant une contre-épreuve, pour restaurer un fichier modifié
exprès. Les contre-épreuves passent maintenant par une copie hors de
git.

Les contre-épreuves, elles, ont payé : elles ont attrapé huit tests
creux, dont un `outline:\s*[^;n]` qui reconnaissait `outline: none` à
travers l'espace et comptait donc chaque suppression comme un anneau, un
`".t" in selector` qui attrapait aussi `.track`, et une regex cherchant la
fin du groupe `#volume` qui ne matchait rien du tout à cause des `</div>`
imbriqués.

Le huitième est d'une espèce à part, parce que rien dans son texte
n'était faux. Il vérifiait qu'une pochette inchangée garde l'instant où
elle a été enregistrée : deux sauvegardes, deux horodatages comparés.
Mais l'horloge du document a une résolution d'une seconde, et deux
sauvegardes de test tombent dans la même — donc l'assertion était vraie
que la règle existe ou non. Un test peut être juste, lisible, et ne rien
mesurer, parce que ce qui le vide est ailleurs que dans ce qu'il dit.

**Trois fois un manque d'un autre genre : pas un test creux, mais un test
absent.** Treize tests vérifiaient la mécanique des identifiants Shazam
en posant l'attribut à la main ; supprimer la ligne qui le remplit
réellement n'en a fait tomber aucun. La sauvegarde qui pose la pochette
n'était couverte par rien — elle n'écrit pas par le même chemin que les
autres, et c'est justement pourquoi elle méritait un test. Et le loquet
du junkisage, laissé levé, ne cassait rien de visible puisque les valeurs
sont réécrites juste après : ce qu'il emportait, c'était la provenance et
les identifiants, si bien qu'il a fallu prendre l'horodatage pour témoin.
Une suite peut couvrir toute la logique d'une fonctionnalité et rien de
son branchement — et la contre-épreuve est le seul procédé qui le montre,
parce que le test manquant, par définition, ne se relit pas.

**Et une fois, ce n'est pas un test qu'elle a corrigé mais un
commentaire.** J'avais écrit que ne pas relire le fichier lors d'une
réinitialisation empêchait les anciennes valeurs de revenir par-dessus
les nouvelles. La contre-épreuve a retiré la garde : rien n'est tombé.
Les gardes situées en dessous s'en chargeaient déjà ; ce que la ligne
économise, c'est une relecture du fichier — et sur un fichier sans
document, sa réouverture complète et le réhachage de sa pochette à chaque
édition. La ligne était bonne, sa justification était fausse, et c'est
la sorte d'erreur qu'aucune relecture n'attrape : un commentaire ne
s'exécute pas.

Elles ont aussi montré deux fois qu'une **contre-épreuve peut mentir** :
un `sed` dont le motif ne s'applique pas laisse le test passer et fait
croire à une assertion solide. Les deux fois, l'édition refaite
proprement a bien fait tomber le test. Une contre-épreuve doit donc
vérifier qu'elle a modifié quelque chose.

Dernier piège du même genre, et le plus instructif : une assertion qui
**comptait** les gardes d'ère du tableau (`== 2`) est tombée le jour où
une troisième étape différée a été ajoutée — en ne prouvant rien sur cette
troisième étape. Elle compte maintenant les gardes contre le nombre
d'attentes, ce qui est l'invariant réel : toute étape différée vérifie
qu'elle est encore attendue.
