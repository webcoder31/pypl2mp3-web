# Similarité musicale — conception

**But :** relier les morceaux entre eux par ce qu'ils *sonnent*, pour
que la bibliothèque devienne un territoire — une carte qu'on parcourt —
et que l'écoute puisse continuer d'elle-même sans rupture.

**Forme retenue :** un vecteur de traits par morceau, rangé dans le MP3 ;
un quatrième ordre de lecture « Radio » qui ordonne la liste de proche en
proche ; un panneau de cinq voisins dans l'inspecteur ; un onglet Carte
en 3D.

---

## L'idée qui tient l'ensemble

**On mesure au lieu de débattre.**

La question qui décide de tout — « des traits calculés à la main
suffisent-ils, ou faut-il un modèle appris ? » — n'a pas à être tranchée
par une opinion. La bibliothèque porte déjà de quoi juger : pour un
morceau, combien de ses cinq plus proches voisins sont **du même
artiste** ?

Deux morceaux tirés au hasard le sont avec une probabilité de **0,6 %**
— la somme des carrés des proportions. C'est une règle exigeante, et
c'est la bonne : deux morceaux du même artiste se ressemblent
effectivement, par la voix, la production, l'instrumentation. C'est
exactement ce que « ça sonne pareil » veut dire.

**Le genre a d'abord servi de règle, et il ne valait rien.** 86 % des
morceaux en portent un, posé par Shazam, ce qui en faisait le candidat
évident. Mesuré sur les 944 : le vecteur livré atteint 1,4 fois le
hasard sur le genre, et **16,5 fois le hasard sur l'artiste** — sur le
même corpus, avec les mêmes vecteurs, le même jour. Les traits ne sont donc pas
faibles ; c'est l'étiquette qui l'est. « Alternative » et « Pop » sont
des catégories commerciales, pas acoustiques : deux morceaux Pop de 1985
et 2020 partagent un libellé et rien d'autre.

Le genre reste rapporté, parce qu'un chiffre qui monte serait une bonne
nouvelle et qu'il colore la carte. Il ne décide plus rien.

## Ce que ça licencie

Partir des traits mesurés — **aucune dépendance nouvelle** — en gardant
l'empreinte apprise en réserve, parce que **la plomberie ne dépend pas de
l'origine du vecteur**. Extraire → ranger → normaliser → distances →
voisins → parcours → carte : seul le premier maillon changerait.

Le dépôt a déjà le mécanisme exact pour en changer. `libs/waveform.py`
verse ses peaks dans une frame ID3 privée dont l'*owner* porte un numéro
de version, « pour que changer la façon de calculer rende toutes les
frames existantes invisibles plutôt que subtilement fausses ». Passer de
la version 1 à la version 2, c'est incrémenter ce numéro : les 944
vecteurs disparaissent et se recalculent.

---

## Contraintes de la machine

Mesurées, pas supposées, parce qu'elles ont fermé une porte :

| Fait | Conséquence |
|---|---|
| Intel Core i7-4770HQ, x86_64, macOS | pas d'accélération MPS ; 4 cœurs / 8 fils |
| **PyTorch : aucune roue x86_64 macOS pour CPython 3.13** (2.14 courante) | l'option « modèle appris » passe obligatoirement par ONNX |
| onnxruntime **1.23.2** a la roue (1.30.0 courante) | la porte reste ouverte, avec un runtime légèrement en retard |
| **numpy 1.26.4 déjà installé** (transitif de moviepy) | le calcul des traits ne coûte rien à installer |
| pas de scipy | tout ce qui suit s'écrit en numpy seul |
| **ffmpeg 8.0.1** | décode ; ses filtres d'analyse se sont révélés inutiles, la STFT du timbre donnant déjà la couleur |
| GPU Intel Iris Pro, 1,5 Go — **mais processus GPU désactivé dans Chrome** | WebGL indisponible ; la carte se dessine sur un canvas 2D |
| décodage mono 22 kHz : **0,53 s** par morceau | le coût sera dans le calcul, pas dans le décodage |

---

## 1. Le vecteur

### Ce qu'on mesure

ffmpeg décode en mono **22 050 Hz**. La waveform se contente de 8 kHz
parce qu'elle ne mesure que le volume ; ici il faut ~11 kHz de Nyquist
pour que le timbre existe.

| Facette | Contenu | Dims |
|---|---|---|
| **Timbre** | 13 MFCC (mel → cosinus discret), médiane + écart interquartile | 26 |
| **Rythme** | enveloppe d'attaques → autocorrélation : tempo, netteté de pulsation, densité d'attaques | 3 |
| **Couleur** | centroïde, rolloff, flatness, entropie, médiane + écart | 8 |
| **Dynamique** | niveau RMS, facteur de crête, dispersion des niveaux courts | 3 |

**Médiane et écart interquartile, pas moyenne et écart-type.** Une intro
silencieuse ou une fin en fondu tirent une moyenne ; elles ne tirent pas
une médiane.

**La tonalité est écartée** de la version 1. Deux morceaux en La mineur
ne se ressemblent pas pour autant, et le chroma coûte cher pour un gain
indéfendable a priori. Si la mesure de fin de chantier montre qu'il
manque quelque chose, il entrera derrière le même numéro de version.

**Un seul décodage, une seule STFT.** La première rédaction faisait venir
la couleur d'`aspectralstats` et la dynamique d'`ebur128`, au motif que
ffmpeg les calcule en C gratuitement. L'argument supposait qu'on n'avait
pas déjà le spectre en main — or le timbre en calcule un, et centroïde,
rolloff, flatness et entropie s'en déduisent en trois lignes. Deux passes
ffmpeg et deux analyseurs de sortie texte disparaissent.

La dynamique se dérive du PCM plutôt que d'une loudness EBU R128 : la
LUFS est une mesure perceptive pour la normalisation de diffusion, et
tout le vecteur est standardisé de toute façon.

Coût mesuré sur vingt morceaux tirés au hasard : **2,44 s par morceau**,
dont 0,53 s de décodage et 1,91 s de calcul — soit **38 min pour 944 en
séquentiel**, et **une vingtaine de minutes** sur le pool de quatre fils
(1,89× mesuré de bout en bout).

La première rédaction annonçait 0,9 s par morceau et 4 min sur 4 cœurs.
Elle se trompait deux fois : sur le calcul, presque trois fois plus cher
que prévu, et sur le parallélisme, qui rend 1,89× et non 4× — ffmpeg et
numpy se disputent les mêmes quatre cœurs.

### Où ça vit

Une frame ID3 privée, *owner*
`https://github.com/webcoder31/pypl2mp3#features-1`, 40 flottants en
`float32` petit-boutien mis bout à bout = **160 octets**. Une longueur
qui n'est pas exactement celle attendue rend la frame invalide, donc
absente — le même « invisible plutôt que subtilement faux » que le
numéro de version. Le dispositif de `waveform.py` et ses raisons : le
vecteur suit le fichier quand il est renommé — ce que cette application
fait en permanence — et il n'y a pas de second magasin à invalider.

### La règle structurelle non négociable

**La frame ne contient que des valeurs brutes.** Aucune normalisation.

Normaliser suppose de connaître la dispersion de toute la bibliothèque.
Or celle-ci change à chaque import, et des vecteurs normalisés contre une
ancienne bibliothèque seraient silencieusement faux *les uns par rapport
aux autres* — le pire mode de défaillance qui soit, parce que rien ne le
signale.

Donc : *la frame dit ce qui est vrai de ce morceau seul ; les
statistiques de la collection sont recalculées à la volée, jamais
stockées.* C'est la distinction que `read_order` fait déjà en répondant
`None` plutôt que `{}`.

### Quand c'est calculé

À l'import, là où les peaks le sont déjà, et par un job en masse pour
rattraper les 944 existants. Un morceau que ffmpeg n'arrive pas à décoder
n'a pas de frame : il reste dans la liste, il n'a simplement ni voisins
ni place sur la carte, et il est marqué.

---

## 2. Ce que « proche » veut dire

### Le piège du nombre de dimensions

26 des 40 dimensions décrivent le timbre. Une distance euclidienne brute
lui donnerait les deux tiers du vote **par simple effet de comptage**, et
un vingtième à la dynamique — non pas parce que c'est musicalement juste,
mais parce qu'il faut 26 MFCC pour décrire un timbre et 3 mesures pour
une dynamique.

La distance se calcule donc **par facette d'abord** : dans chaque bloc,
l'écart moyen entre dimensions standardisées, ce qui donne quatre nombres
comparables entre eux, recombinés ensuite par des poids explicites.

Ce détour paie deux fois : **c'est aussi ce qui rend l'explication
possible.** « Proche par le rythme, loin par les sonorités » n'est pas un
commentaire ajouté après coup, ce sont les quatre nombres qu'on vient de
calculer. Le panneau les a sous la main sans rien recalculer.

Standardisation sur la sélection en cours, par médiane et écart
interquartile — mêmes statistiques robustes qu'à l'extraction, pour la
même raison.

### Les poids

**Timbre 0,60 · couleur 0,15 · rythme 0,15 · dynamique 0,10.**

Le timbre domine parce que c'est ce que « ça sonne pareil » veut dire en
premier, et parce que c'est là qu'est le signal : mesuré sur les 944,
le timbre seul retrouve un morceau du même artiste **14,3 fois mieux que
le hasard**, contre 5,7 pour le rythme, 5,6 pour la couleur et 3,8 pour
la dynamique.

Et retenu délibérément en deçà de ce que la mesure réclamerait. **La
règle de l'artiste flatte structurellement le timbre** — même artiste,
même voix, presque par définition — donc la suivre jusqu'au bout
donnerait un curseur « timbre » et trois qui ne font rien. Les trois
autres gardent un poids que la mesure ne demande pas, parce qu'une radio
qui ne suit que le timbre est une radio à un seul tempo.

**Le test du genre vérifie ces poids, il ne les choisit pas.** Optimiser
aveuglément l'accord avec l'étiquette Shazam donnerait un devineur
d'étiquettes : une reprise acoustique cesserait d'être voisine de son
original électro, alors que c'est exactement le lien qu'on veut voir
apparaître. Le genre est une règle pour détecter qu'on s'est planté — un
score à 15 % dit que le vecteur ne vaut rien — pas une cible.

### Deux règles qui viennent de ce dépôt

**Un voisin n'est jamais le même enregistrement.** Huit morceaux sont
présents dans deux playlists : deux clés distinctes, un audio identique,
donc une distance nulle. Sans garde-fou, chacun serait éternellement son
propre voisin n°1 et la radio jouerait deux fois de suite la même chose.
L'exclusion se fait sur l'identifiant vidéo — précisément ce qui
distingue le fichier de l'enregistrement, la distinction établie en
corrigeant les doublons.

**Le voisinage se calcule sur la sélection affichée**, pas sur toute la
bibliothèque, parce que la file de lecture *est* la liste : la radio ne
peut proposer que ce qu'elle pourrait effectivement jouer. Dans « All
songs » elle parcourt les 944 ; filtrée sur mid90s, elle reste dans les
onze. Proposer un morceau absent de la liste rouvrirait la brèche qu'on a
fermée.

### Le coût, et ce qu'il élimine

944 × 40. La matrice complète des distances, c'est 890 000 calculs —
**120 ms** en numpy, mesuré à la vraie taille : quatre matrices de
distances et un tri de 445 000 paires. Puis 0,1 ms pour demander un
voisinage. Recalculé à chaque changement de sélection sans que personne
le remarque.

Donc : **pas d'index approximatif, pas de faiss, pas de base
vectorielle.** Un service qui lit les frames, une matrice, et c'est tout.

---

## 3. La radio

### Un quatrième ordre

`Play order` gagne un quatrième bouton à côté de YouTube / A-Z / Shuffle,
et obéit aux mêmes règles : un clic remet la file à zéro, et **la liste
reste l'ordre de lecture**.

Le parcours est une chaîne gloutonne : depuis le morceau en cours (ou le
premier de la liste si rien ne joue), son plus proche voisin, puis le
plus proche de celui-là parmi ceux qui restent, jusqu'au dernier. La
liste entière est réordonnée d'un coup, visible jusqu'au bout — pas de
file qui s'allonge dans le dos.

Cette construction a la propriété qui fait tout tenir : **à tout moment,
la ligne suivante *est* le plus proche voisin du morceau en cours parmi
ceux qui restent.** C'est vrai par construction. « Si on ne fait rien,
c'est le plus proche qui est joué en suivant » est donc satisfait sans
qu'aucun code décide quoi que ce soit au changement de morceau.

### Le panneau

Dans l'inspecteur, sous les faits du morceau :

```
Voisins                                                    Voisins  Edit
 Big Wide World          ●●●●○   timbre            [    Next     ]
 Gyöngyhajú Lány         ●●●○○   couleur           [  Play next  ]
 We'll Let You Know      ●●●○○   rythme            [  Play next  ]
 Hunter and the Hunted   ●●○○○   timbre            [  Play next  ]
 Si jamais               ●●○○○   dynamique         [  Play next  ]
```

Le panneau partage sa case avec le bloc qui corrige le titre et
l'artiste, et avec celui où Shazam répond : trois faces, une seule
hauteur, et c'est celle-ci par défaut — on écoute en continu et on
corrige de temps en temps.

Cinq voisins, **les cinq plus proches au total** — pas un par facette.
Pris parmi les morceaux encore à venir dans la liste : proposer ce qui
vient d'être joué n'aurait pas de sens.

Les points disent la proximité par un **rang**, pas par un pourcentage
inventé : « plus proche que 96 % des paires » est une phrase vraie et
stable ; « 96 % de similarité » n'aurait aucun référent.

Contre quoi ce rang se lit a dû changer. Un percentile de *toutes les
paires* avec des paliers fixes ne marche pas aux deux bouts : sur 944
morceaux, le plus proche voisin de n'importe qui est dans la fraction de
percentile du haut, et sur un filtre qui en tient onze, aucun n'atteint
le 85ᵉ. Une échelle qui dit « cinq » pour tout le monde, ou « un » pour
tout le monde, ne dit rien.

Les cinq points se lisent donc contre **ce que les morceaux d'ici
atteignent habituellement** : la distance de chaque morceau à son propre
plus proche. Cinq quintiles de cette distribution — cinq points veut
dire « plus proche que la plupart des morceaux n'approchent jamais quoi
que ce soit », un point veut dire « ces deux-là ne sont voisins que
faute de mieux ». L'échelle se recalibre sur la sélection, ce qui est la
seule façon de servir 944 morceaux et onze avec la même règle.

Le percentile sur toutes les paires subsiste, dans l'étiquette que lit
un lecteur d'écran — c'est une phrase, pas une graduation.

Le mot à côté est la facette où l'écart est le plus faible — une
explication, pas le critère de sélection.

Le premier porte **Next** au lieu d'un bouton, parce qu'il est déjà la
ligne d'après : lui proposer « Play next » serait proposer de ne rien
faire. C'est une marque pleine de la taille des boutons d'à côté — pas
un bouton désactivé, car rien n'est retenu là, il n'y a qu'un fait — et
c'est la seule ligne sur laquelle un clic n'agit pas.

Les quatre autres réutilisent **le `Play next` existant** — même bouton,
même insertion, même animation de changement de rang. Cliquer fait passer
ce morceau devant, et **la queue du parcours est replanifiée depuis lui**
sur les morceaux situés après le curseur. « Après le curseur » et non
« effectivement écoutés » : un morceau dépassé par un clic plus loin
compte comme passé, définition que la file utilise déjà.

Hors mode radio le panneau reste affiché et reste utile : il n'y a
simplement plus de **Next**, et les cinq boutons redeviennent cinq
`Play next` ordinaires.

### Les bords

Un morceau sans vecteur n'a pas de voisins ; **le panneau le dit, et
lui seul** — la liste ne le marque pas, parce qu'un morceau sans vecteur
reste jouable et que la ligne ne parle que de ce qui s'écoute. Dans le
parcours, ces morceaux **vont en fin de liste**, exactement où vont les
orphelins de playlist et pour la même raison : ils n'ont pas de place
dans l'ordre que les autres suivent.

Changer de filtre pendant la radio rebâtit le parcours sur la nouvelle
sélection et remet la file à zéro — règle déjà vraie pour les trois
autres ordres.

---

## 4. La carte

### Où sont les points

Passer de 40 dimensions à 3. Une **ACP** est gratuite et déterministe,
mais elle conserve la variance globale et non la structure locale : sur
des traits audio, une patate uniforme où tout se recouvre. **t-SNE ou
UMAP** séparent superbement, mais c'est scikit-learn ou numba en plus, et
aucun des deux n'est déterministe sans qu'on s'y emploie.

Retenu : **la solution de cairn** (`src/lib/graph-3d.ts`). Un graphe des
**k = 4** plus proches voisins **et réciproques** — assez pour que les
amas se tiennent, assez peu pour qu'ils ne fusionnent pas ; la valeur
était un réglage et non une constante de la nature, et la carte a dit
qu'elle était bonne, le balayage plus bas le raconte —, relâché dans
l'espace par une relaxation à **nombre d'itérations fixe** (150) —
attraction le long des arêtes, répulsion entre tous les points. 890 000
paires par itération, vectorisé en numpy : **2,1 s** pour les 944,
mesuré.

Aucune dépendance nouvelle, et — ce à quoi cairn tient explicitement —
*même corpus en entrée, même nuage en sortie, sur chaque machine*. La
carte ne doit pas sauter parce qu'un import est passé.

Relaxation en 3D véritable, pas un plan relevé : garder la structure dans
deux axes donne « une carte plate avec du bruit », alors que laisser les
îlots trouver leur forme dans les trois fait des amas qu'on orbite.

### Ce que la couleur dit

**La position vient du son ; la couleur vient du genre.**

Deux sources délibérément indépendantes, ce qui rend la carte
**vérifiable d'un coup d'œil** : si les couleurs se regroupent, le
vecteur capture quelque chose de réel ; si elles sont poivrées au hasard,
il ne vaut rien. Le script de mesure dit ça sur un nombre, la carte le
montre. Même juge, deux langues.

Douze genres principaux prennent une couleur, les 37 autres un gris
commun : 49 teintes distinctes ne seraient plus une information.

### Les isolés

Un morceau sans vecteur ne peut pas être placé. Ces points vont sur **une
coque sphérique autour du nuage**, en spirale de Fibonacci — la solution
de cairn, reprise avec son argument : rien ne peut masquer la couche la
plus extérieure d'une scène, donc ils restent comptables depuis n'importe
quel angle, et leur place dit la vérité, matière non rattachée en
périphérie de la structure.

### Le rendu

Un onglet **Carte** à côté de Playlist et Imports. Le serveur calcule les
coordonnées, le navigateur dessine sur un **canvas 2D**, sans aucune
bibliothèque.

Ce n'est pas le choix de départ. La spec prévoyait **three.js** — 600 Ko
à côté des 50 Ko d'htmx, sans build ni npm, un fichier déposé comme htmx
l'est déjà — et le tableau des contraintes annonçait « 944 points en
WebGL : sans effort ». Le GPU était là, le pilote non : le Chrome de
cette machine refuse d'ouvrir un processus GPU (`GPU access is disabled
due to frequent crashes`), donc la version WebGL n'a **jamais** été vue
tourner. Celle en 2D a révélé deux défauts dans ses dix premières
minutes, et three.js a fini par être supprimé plutôt que gardé en
parallèle : garder les deux, c'était garder un moteur que personne ne
pouvait vérifier.

Un nuage de points demande très peu à un moteur de rendu : une rotation,
une projection, un tri en profondeur et une fiche estampée. Chaque image
coûte **2,4 ms** pour 944 morceaux, mesurées dans le navigateur, sur un
budget de 16,7.

#### La forme du point

Elle a changé trois fois, et les deux premières étaient fausses pour la
même raison. *Dans ce qui suit, « la carte » reste l'onglet et « une
fiche » est la marque qui représente un morceau* — sans quoi la section
parle de deux choses avec un seul mot.

| forme | ce qui n'allait pas |
|---|---|
| sphère ombrée | lue comme un ballon d'anniversaire : le spéculaire blanc est le signal « plastique verni » |
| cube ombré | la bonne famille de formes, mais il modélise un volume que l'interface n'a nulle part |
| **fiche plate** | — |

La page est résolument plate : des filets d'un pixel, de la typographie,
un seul accent, aucun relief. Neuf cents solides éclairés au milieu de ça
n'étaient pas un détail de goût mais une faute de registre. **Et la carte
porte déjà toute la profondeur dont elle a besoin** — le lointain est
plus petit et plus pâle — donc il n'y a rien à modéliser par-dessus.

La forme retenue est une **fiche**, à la proportion d'une carte bancaire
(85,60 × 53,98 mm, soit 1,586), coins juste décrochés du droit, une seule
couleur plate, et **la même aire que le disque qu'elle remplace** pour
que changer la forme n'épaississe pas le nuage en douce.

Le cube mérite d'être retenu si quelqu'un veut le ramener. Tous les cubes
vivent dans le même monde, tournés du même angle, donc ils présentent la
**même silhouette** : c'était encore un sprite estampé, pas une
projection par point. Mais la silhouette devait être recoupée dès que la
vue tournait, et recouper les treize couleurs dans une image coûtait
**12,6 ms** contre une médiane de 2,6. Une fiche, elle, ne tourne jamais.

#### La profondeur se dit avec de l'air

Comme sur une carte, pas comme sur un rendu : plus petit et plus pâle.
Chaque couleur est découpée une fois par palier de profondeur, mélangée
vers la couleur de la page derrière le nuage.

C'est un **mélange opaque, pas une transparence**. La distinction n'est
pas théorique : neuf cents disques translucides superposés avaient donné
un voile où l'œil voulait des points, et des couleurs mélangées qui
n'étaient le genre de personne.

Les bornes du fondu sont les parois proche et lointaine du nuage **telles
que l'œil est placé à cet instant**, et non une distance absolue : la
respiration déplace l'œil d'un facteur cinq, et une échelle fixe
délaverait tout au bout de sa course.

Quand deux fiches de même couleur se recouvrent, rien ne dit laquelle est
devant. Un trait entre elles a été essayé deux fois et jeté deux fois —
à la couleur de la page il taillait une entaille blanche dans chaque
foule, et dans un ton plus sombre de la fiche il dessinait un bord autour
de choses qui n'en ont nulle part ailleurs sur cette page. Ce qui marche
ne dessine rien : **une pente de lumière** en diagonale dans chaque
fiche. Le coin éclairé de la fiche de devant rencontre l'extrémité
ombrée de celle de derrière, et la jointure se montre d'elle-même.

Enfin le nuage **quitte** le cadre au lieu d'être tranché par lui :
quatre bandes de la couleur de la page, une par côté, estompent la
dernière portion. Mesuré : sur les trois colonnes extérieures, **0,4 %**
des pixels diffèrent de la couleur de page, contre 83,7 % dans une bande
au centre.

#### Le mouvement

Tout est amorti, et tout s'arrête quand plus rien ne bouge.

- **Le zoom est un ressort** : 11 % de dépassement, stabilisé à la 19ᵉ
  image, constantes choisies en simulant quatre-vingt-dix images avant
  d'écrire la ligne.
- **Un glissement relâché garde son élan** environ une seconde.
- **Laissée seule, la carte tourne et respire** : une révolution en 44 s
  à vitesse constante, l'axe dérivant lui aussi à vitesse constante
  (0,96°/s, un radian de chaque côté), et l'œil allant du cadrage
  d'ensemble jusqu'au cinquième de cette distance — c'est-à-dire
  **dedans** — en 62 s. Et la couleur de la nappe tourne, en 17 s :
  un rapport de section dorée avec la respiration, donc les deux ne
  reviennent jamais en phase et une teinte rencontre un moment de la
  respiration dans une combinaison inédite.

La respiration est un **facteur**, et son ancre est ramenée vers la
distance qui cadre le nuage entier. La première version la laissait
chevaucher ce que la molette avait laissé : un zoom, et elle restait
rétrécie autour de ce point pour toujours. *Un coup de molette est un
coup d'œil sur quelque chose, pas un nouveau domicile.*

La boucle d'animation ne tourne que pendant un mouvement — **60 images
par seconde au repos, zéro dès que le pointeur se pose sur la carte,
zéro sur un autre onglet**. Qui a demandé à son système de ne pas animer
ne reçoit que la cible, sans aucune animation.

#### Ce que la carte dit d'elle-même

Survoler nomme le morceau ; cliquer le joue, la carte devenant une entrée
dans la file comme une ligne de la liste.

Le nom est dessiné **sur le canvas**, à droite de sa fiche et aligné sur
son milieu — une légende attachée à la chose, comme un nom de lieu
posé à côté de son point. Il est écrit dans **la couleur de sa fiche**,
poussée assez loin de la page pour être lue : assombrie à 55 % sur le
thème clair, éclaircie d'un quart sur le sombre. Mesuré sur la pire des treize
couleurs : **1,75:1 brut**, contre **5,28:1** et **6,26:1** après
poussée — au-dessus du 4,5:1 auquel un petit texte est tenu. Le sens de
la poussée se déduit de la luminance de la page, pas d'un drapeau de
thème : c'est un fait sur ce qui est derrière les lettres.

Et **laissée seule, la carte se nomme elle-même**. Un nom par seconde,
chacun restant trois, chacun s'effaçant sur son propre âge pour que celui
qui part et celui qui arrive se chevauchent. Trois règles le tiennent :

- **Seulement une fiche d'au moins huit pixels de large.** Ce n'est pas
  un niveau de zoom, bien que ça y revienne : ce qui empêche de rattacher
  un nom, c'est que la chose désignée est un grain de poussière. Mesuré,
  la plus large fiche fait 1,2 px au bout de la molette et 7,5 px au
  cadrage d'ouverture.
- **Jamais deux fois le même morceau dans la minute.** L'avant d'un nuage
  qui tourne aussi lentement est le même d'une seconde à l'autre ; sans
  mémoire, les mêmes quelques morceaux revenaient en boucle. Mesuré sur
  110 s : 118 noms, 105 distincts, le rapprochement le plus serré à 77
  d'écart pour un plancher de 60.
- **Un nom est coupé au quart de la largeur du cadre**, qui est aussi
  l'écart que deux noms doivent garder pour partager une ligne. Une
  limite et un écartement qui ne s'accordent pas laisseraient deux noms
  « séparés » se chevaucher. Sur la bibliothèque, le nom médian fait
  188 px et le plus long 698, soit les deux tiers du cadre.

La fiche nommée porte **le même anneau que fait le pointeur** : à cette
taille une fiche fait quelques pixels, et un nom planant au-dessus d'un
champ de pixels ne dit pas lequel.

`#map-hover` subsiste, masqué. Un canvas ne dit rien à un lecteur
d'écran ; retirer l'élément aurait laissé la carte sans aucune
restitution accessible.

**En option, pas dans le socle :** tracer le parcours radio comme un fil à
travers le nuage. Presque gratuit une fois le graphe dessiné.

---

## 5. Comment on saura

### Deux instruments, pas un

**Les tests tiennent le mécanisme. La mesure du genre juge le choix des
traits** — et elle ne peut pas être un test unitaire, parce qu'elle
dépend de 4,2 Go qui ne sont pas dans le dépôt.

Donc un script, là où ce dépôt en met déjà sept :
`scripts/measure_similarity.py` sort le taux d'accord **d'artiste**
entre un morceau et ses cinq voisins, globalement et par facette, pour
une pondération donnée — et le taux d'accord de genre à côté, pour
information.

Références mesurées sur les 944 : hasard **0,6 %** pour l'artiste,
**12,1 %** pour le genre. Le vecteur livré atteint **16,5×** sur
l'artiste et **1,4×** sur le genre. Un témoin de vecteurs aléatoires
donne exactement le hasard sur les deux, ce qui dit que la mesure
elle-même est saine.

L'instrument décide de ce qu'il mesure, et il faut le relire avant de
comparer deux chiffres : l'artiste vient du **nom de fichier** et non de
la balise, un morceau seul à porter son étiquette n'est pas noté
puisqu'il ne peut pas réussir, et chaque morceau pèse pour la part de
ses cinq voisins qui s'accordent — pas pour un total mis en commun. Une
mesure refaite sans ces trois règles sortait 8,3× là où celle-ci
en donne 13,4.

Le plancher est **5× sur l'artiste** : nettement au-dessus du hasard,
nettement en dessous de ce qui est atteint, donc un garde-fou contre une
régression plutôt qu'une cible à viser. En dessous, quelque chose s'est
cassé — ou l'empreinte apprise devient l'option, et c'est cet instrument
qui le dira.

### Ce que les tests tiennent

**L'extracteur, sans aucun MP3.** On fabrique le signal : un click à 120
BPM contre un à 60 doit sortir un tempo double ; un bruit blanc contre
une sinusoïde grave, des centroïdes opposés ; le même signal joué deux
fois plus fort, un timbre quasi identique et une dynamique différente.
Chaque assertion a sa contre-expérience.

**La frame.** Aller-retour, puis renommage du fichier et relecture —
c'est la propriété pour laquelle on la met dans le MP3. Et l'incrément du
numéro de version doit rendre les anciennes frames *invisibles* plutôt
que subtilement fausses.

**L'invariant qui tient le design :** en mode radio, `le premier voisin
du panneau == la ligne suivante de la liste`. Si ce test tombe, « si on
ne fait rien, c'est le plus proche qui est joué » est devenu faux, et
c'est toute la promesse.

**Les trois règles de bord**, chacune avec sa contre-expérience : un
doublon n'est jamais son propre voisin ; un voisin est toujours dans la
sélection affichée ; un morceau sans vecteur va en fin de parcours.

**La carte est déterministe** : deux calculs sur le même corpus donnent
des coordonnées identiques, au bit près.

---

## Découpage

| Unité | Rôle | Dépend de |
|---|---|---|
| `libs/features.py` | décoder, calculer les 40 traits, lire/écrire la frame | ffmpeg, numpy, mutagen |
| `services/similarity.py` | normaliser, distances par facette, voisins, chaîne gloutonne | numpy, `libs/features` |
| `services/song_map.py` | graphe k-NN → relaxation 3D déterministe | numpy, `services/similarity` |
| `scripts/measure_similarity.py` | l'instrument de jugement | `services/similarity` |
| routes web | `/fragments/inspector/{key}` rend les voisins avec le reste de l'inspecteur ; `/map/points` sort le nuage en JSON ; `/features/analyse` lance la passe | les trois ci-dessus |
| `static/map.js` | le rendu, seul : pas de bibliothèque | — |
| `console.js` | le 4e ordre, le panneau, le clic sur un point | `similarity` via les routes |

Chaque unité répond seule aux trois questions : ce qu'elle fait, comment
on s'en sert, de quoi elle dépend. `libs/features.py` ignore qu'une
radio existe ; `services/similarity.py` ignore qu'il y a une carte.

---

## Ce qui est écarté, et pourquoi

- **La tonalité** — coûteuse, gain indéfendable a priori. Reviendra si la
  mesure le réclame.
- **faiss, base vectorielle, index approximatif** — 890 000 distances en
  120 ms ; il n'y a pas de problème à résoudre.
- **t-SNE, UMAP** — une dépendance et un non-déterminisme, pour un
  résultat que la relaxation donne déjà.
- **PyTorch** — aucune roue pour cette machine. Si l'empreinte apprise
  devient nécessaire, ce sera par ONNX.
- **Toute API externe de similarité** (Last.fm, Spotify) — même raison
  que pour l'API Google : rester indépendant. Et AcousticBrainz, qui
  aurait été le bon candidat, est arrêté depuis 2022.
- **Un panneau à cinq facettes** (un voisin par axe) — envisagé, écarté :
  deux morceaux au même tempo peuvent n'avoir rien d'autre en commun, et
  la continuité d'écoute est le critère retenu. Les quatre distances par
  facette étant calculées de toute façon, un sélecteur d'axe reste à une
  ligne d'UI près.

---

# Points en suspens

## Le déterminisme ne vaut pas sous insertion

La carte est reproductible pour un corpus donné, **pas stable quand le
corpus grandit** : importer dix morceaux peut redessiner le nuage, pas
seulement y ajouter dix points. Partir de positions initiales issues d'un
hachage du morceau — ce que fait cairn — limite la casse sans la
garantir.

La parade, si ça devient gênant à l'usage, est d'ancrer la relaxation sur
les positions précédentes. Pas dans le socle, parce qu'on ne sait pas
encore si le problème se posera.

## Ce que la carte a donné, une fois construite

Elle montre des îlots répartis dans tout le volume de la sphère. Il a
fallu deux corrections que la conception n'avait pas vues, et toutes
deux portaient sur le **graphe**, pas sur la relaxation.

*Les chiffres de cette section sont ceux du balayage, à sa date : ce
sont des comparaisons entre réglages, pas l'état livré. Pour celui-ci,
voir le dernier paragraphe.*

**Les arêtes doivent être réciproques.** Gardées dans un seul sens, un
morceau en entraîne un autre sans réciproque et, avec neuf cents
morceaux tenant chacun huit fils, plus rien ne peut se défaire : le
nuage se relâche en une dalle régulière et légèrement vrillée. Mutuel,
l'accord d'artiste passe de 6,5× à 11,0×.

**Et il en faut quatre, pas huit.** À huit, les trois quarts de la
bibliothèque s'entassent dans la moitié intérieure du rayon — une
sphère à cœur plein. À quatre, la moitié, et le volume passe de 0,68 à
0,83 sans que le juge bouge (10,6×).

Deux autres leviers ont été essayés et écartés par la mesure : une
attraction croissant avec la distance vide le cœur mais fait tomber
l'accord d'artiste à 9,4× — elle étale sans structurer ; pondérer les
arêtes par la proximité aplatit le nuage.

**Sur le genre, la prédiction tient : 1,3× sur la carte**, contre 1,4×
en quarante dimensions. Les amas sont
des familles acoustiques — une voix, une production, une époque de
studio — et non les étiquettes que Shazam donne. La couleur reste un
contrôle visuel, pas une promesse.

Et aucun nombre ne remplace l'écoute. **16,5× sur l'artiste dans les
quarante dimensions, 13,4× sur la carte** — la projection en garde donc
les quatre cinquièmes — veut dire que les voisins sonnent comme le
morceau ; il reste à savoir si on a envie de les entendre l'un après
l'autre.

## Le coût de la première passe

Une vingtaine de minutes sur le pool de quatre fils pour 944 morceaux —
38 minutes si le job tournait encore sur un seul, ce qu'il a fait
jusqu'à ce qu'on le mesure — pendant lesquelles 944 fichiers MP3 sont
réécrits pour recevoir leur frame. C'est le même risque que les
peaks font déjà courir, à la même échelle, mais c'est un risque : une
coupure au mauvais moment laisse un fichier en cours d'écriture.
`waveform.py` s'en remet à mutagen ; on fera pareil, sans prétendre que
c'est atomique.
