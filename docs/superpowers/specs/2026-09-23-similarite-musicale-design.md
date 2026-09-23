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

Deux morceaux tirés au hasard le sont avec une probabilité de **0,7 %**
— la somme des carrés des proportions. C'est une règle exigeante, et
c'est la bonne : deux morceaux du même artiste se ressemblent
effectivement, par la voix, la production, l'instrumentation. C'est
exactement ce que « ça sonne pareil » veut dire.

**Le genre a d'abord servi de règle, et il ne valait rien.** 86 % des
morceaux en portent un, posé par Shazam, ce qui en faisait le candidat
évident. Mesuré : le vecteur livré atteint 1,4 fois le hasard sur le
genre, et **11,6 fois le hasard sur l'artiste** — sur le même corpus,
avec les mêmes vecteurs, le même jour. Les traits ne sont donc pas
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
| GPU Intel Iris Pro, 1,5 Go | 944 points en WebGL : sans effort |
| décodage mono 22 kHz : **0,41 s** par morceau | le coût sera dans le calcul, pas dans le décodage |

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

Coût : ~0,9 s par morceau dont 0,41 s de décodage, soit **~15 min pour
944 en séquentiel, ~4 min sur 4 cœurs**, une seule fois.

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
VOISINS
 Big Wide World          ●●●●○   timbre        ▸ SUIVANT
 Gyöngyhajú Lány         ●●●○○   couleur       Play next
 We'll Let You Know      ●●●○○   rythme        Play next
 Hunter and the Hunted   ●●○○○   timbre        Play next
 Si jamais               ●●○○○   dynamique     Play next
```

Cinq voisins, **les cinq plus proches au total** — pas un par facette.
Pris parmi les morceaux encore à venir dans la liste : proposer ce qui
vient d'être joué n'aurait pas de sens.

Les points disent la proximité **en percentile**, pas en pourcentage
inventé : le rang de cette distance parmi *toutes les distances entre
paires de la sélection en cours*. « Plus proche que 96 % des paires »
est une phrase vraie et stable ; « 96 % de similarité » n'aurait aucun
référent. Cinq points, donc cinq paliers : ≥99, ≥97, ≥93, ≥85, en
dessous.

Le mot à côté est la facette où l'écart est le plus faible — une
explication, pas le critère de sélection.

Le premier porte **SUIVANT** au lieu d'un bouton, parce qu'il est déjà la
ligne d'après : lui proposer « Play next » serait proposer de ne rien
faire.

Les quatre autres réutilisent **le `Play next` existant** — même bouton,
même insertion, même animation de changement de rang. Cliquer fait passer
ce morceau devant, et **la queue du parcours est replanifiée depuis lui**
sur les morceaux situés après le curseur. « Après le curseur » et non
« effectivement écoutés » : un morceau dépassé par un clic plus loin
compte comme passé, définition que la file utilise déjà.

Hors mode radio le panneau reste affiché et reste utile : il n'y a
simplement plus de **SUIVANT**, et les cinq boutons redeviennent cinq
`Play next` ordinaires.

### Les bords

Un morceau sans vecteur n'a pas de voisins ; le panneau le dit. Dans le
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
**k = 8** plus proches voisins — assez pour que les amas se tiennent,
assez peu pour qu'ils ne fusionnent pas ; la valeur est un réglage, pas
une constante de la nature, et la carte dira si elle est bonne —, relâché
dans l'espace par une relaxation à
**nombre d'itérations fixe** — attraction le long des arêtes, répulsion
entre tous les points. 890 000 paires par itération, vectorisé en numpy :
**une à trois secondes** pour tout le nuage.

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
coordonnées, le navigateur dessine avec **three.js**.

C'est la première bibliothèque front-end après htmx, et elle coûte :
`htmx.min.js` pèse 50 Ko dans `/static/`, three.js en pèse ~600, douze
fois plus. Pas de build, pas de npm — un fichier déposé à côté, comme
htmx l'est déjà. 944 points forment un seul objet `Points`, pas 944
objets.

Survoler nomme le morceau ; cliquer le joue, la carte devenant une entrée
dans la file comme une ligne de la liste ; le morceau en cours est
allumé.

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

Références mesurées sur 352 morceaux : hasard **0,7 %** pour l'artiste,
**12,3 %** pour le genre. Le vecteur livré atteint **11,6×** sur
l'artiste et 1,4× sur le genre. Un témoin de vecteurs aléatoires donne
exactement le hasard sur les deux, ce qui dit que la mesure elle-même
est saine.

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
| routes web | `/fragments/neighbours/{key}`, `/fragments/map`, points en JSON | les trois ci-dessus |
| `static/map.js` + `static/three.module.js` | le rendu | — |
| `console.js` | le 4e ordre, le panneau, le clic sur un point | `similarity` via les routes |

Chaque unité répond seule aux trois questions : ce qu'elle fait, comment
on s'en sert, de quoi elle dépend. `libs/features.py` ignore qu'une
radio existe ; `services/similarity.py` ignore qu'il y a une carte.

---

## Ce qui est écarté, et pourquoi

- **La tonalité** — coûteuse, gain indéfendable a priori. Reviendra si la
  mesure le réclame.
- **faiss, base vectorielle, index approximatif** — 890 000 distances en
  10 ms ; il n'y a pas de problème à résoudre.
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

## Ce que la mesure de l'artiste ne dit pas

Elle dit que le vecteur trouve la ressemblance acoustique. Elle ne dit
pas que la carte s'organisera en genres — et la mesure du genre à 1,4×
suggère plutôt le contraire. **Les amas seront des familles acoustiques**
(une voix, une production, une époque de studio) et non les étiquettes
que Shazam donne. Colorer par genre montrera une correspondance
partielle, ce qui reste informatif : c'est la carte qui dira laquelle
des deux lectures est la plus juste.

Et aucun nombre ne remplace l'écoute. 11,6× sur l'artiste veut dire que
les voisins sonnent comme le morceau ; il reste à savoir si on a envie
de les entendre l'un après l'autre.

## Le coût de la première passe

~7 minutes sur 4 cœurs pour 944 morceaux, pendant lesquelles 944 fichiers
MP3 sont réécrits pour recevoir leur frame. C'est le même risque que les
peaks font déjà courir, à la même échelle, mais c'est un risque : une
coupure au mauvais moment laisse un fichier en cours d'écriture.
`waveform.py` s'en remet à mutagen ; on fera pareil, sans prétendre que
c'est atomique.
