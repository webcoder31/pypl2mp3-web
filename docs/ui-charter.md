# Charte d'UI de la console

Ce document sert à concevoir. Il dit quoi faire en ajoutant un élément,
et non comment les éléments existants ont été faits. Ce qui décrit
l'existant est dans `ui-rules-inventory.md`, dont cette charte est tirée.

Deux parties : ce qui est décidé, qui ne se rediscute pas élément par
élément, et les principes, qui disent comment choisir dans ce qui reste.

---

# Ce qui est décidé

Aucune de ces valeurs ne se réinvente localement. Un élément neuf prend
dans ces jeux ; si rien n'y convient, c'est le jeu qu'il faut changer, et
c'est une décision, pas un dépassement local.

## Les échelles

**Type — six pas.** `--fs-xs` 0.6875 · `--fs-sm` 0.75 · `--fs-md` 0.8125
· `--fs-base` 0.875 · `--fs-lg` 1.0625 · `--fs-xl` 1.375 rem.

**Espacement — cinq pas.** `--space-1` 0.25 · `--space-2` 0.5 ·
`--space-3` 0.75 · `--space-4` 1 · `--space-5` 1.5 rem.

**Rayon.** Trois valeurs, pas une de plus : `2px` par défaut, `50%` pour
une pastille, `0` pour un bouton qui n'a ni fond ni bordure et dont le
rayon ne décrirait rien. Rien entre les deux, et jamais de pilule.

**Composés** — déjà nommés, à réutiliser plutôt qu'à recomposer :
`--block-pad-x` et `--block-pad-y`, `--row-pad-x` et `--row-pad-y`,
`--row-font`, `--row-meta-size`, `--nav-row-pad`, `--nav-font`,
`--nav-gap`, `--btn-pad`, `--field-pad`.

**Polices.** La pile système, `--font` et `--font-mono`. Aucune police
distante : la console ne joint pas un hôte qu'elle ne sert pas.

## Les surfaces

Trois valeurs — `--bg`, `--surface`, `--sunken` — et deux rôles par
dessus, `--content-bg` et `--frame-bg`, que les deux palettes attribuent
en sens inverse. **On écrit le rôle, jamais la valeur** : c'est ce qui
permet au sens de s'inverser d'un thème à l'autre en un seul endroit.

Les surfaces diffèrent par la clarté, pas par une bordure. Pour séparer,
`--line`, ou `--line-strong` quand une séparation doit se voir.

Un champ se pose sur `--sunken` : il reste distinct de la surface qui le
porte, dans les deux thèmes, et sa bordure doit avoir de quoi tenir.

## Les couleurs

Texte : `--text`, `--text-2`, `--text-3`, plus `--text-green` pour un
texte de la famille de l'accent qui doit reculer.

Accent : `--accent` et `--accent-text`, avec `--accent-soft`,
`--accent-line`, `--accent-dim` et `--queued` pour ses degrés.

États : `--junk` et `--junk-soft`, `--ok`, `--bad`, `--busy`, et les trois
bandes `--score-high`, `--score-mid`, `--score-low`.

## Les boîtes fixes

`--cover-size`, `--wave-height`, `--pane-nav`. Une dimension qui doit
tenir se nomme ici, pas dans la règle qui l'utilise.

---

# Les principes

## 1. Les rôles, pas les valeurs

Quand deux choses doivent s'accorder, elles partagent **une seule
déclaration**. Jamais deux règles qui se ressemblent, jamais une valeur
recopiée.

Quand la réponse dépend du thème, on nomme le rôle et chaque palette y
répond — `--content-bg` plutôt qu'un `--surface` écrit à cent endroits
qu'il faudrait tous retourner.

Quand une valeur dérive d'une autre, on la dérive — `color-mix` sur la
variable, pas une copie de sa couleur, qui dériverait le jour où
l'originale bouge.

C'est le principe qui coûte le moins à suivre et le plus à rattraper. Un
bouton rempli de plus rejoint la liste de sélecteurs existante ; il ne
reçoit pas sa propre règle.

## 2. Le poids dit l'engagement, et rien d'autre

Trois niveaux, pas quatre :

- **Rempli** — accent plein, texte `--accent-text`, graisse 600. Réservé
  au clic qui *est* le but du panneau où il se trouve, et qui écrit.
- **Filet** — le `button` par défaut : une bordure d'1 px, du texte,
  aucune surface, aucune ombre. Tout le reste.
- **Sans boîte** — `.quiet`, pour un bouton qui vit dans du texte. Dans
  une liste, une boîte par ligne transforme le contenu en grille de
  chrome.

Filtrer, basculer un thème, choisir une portée : rien de tout cela
n'engage. Ce qui n'engage pas n'est pas rempli.

## 3. La couleur répond d'un état ; elle ne décore jamais

Une teinte neuve doit pouvoir nommer l'état dont elle répond. Si
l'élément n'a pas d'état, il prend la rampe de texte.

Toute variable ajoutée à une palette est ajoutée à l'autre : une couleur
déclarée d'un seul côté ne se signale pas, elle hérite en silence de ce
que l'autre palette avait dit.

**Une opacité n'est pas une couleur.** Sur fond clair une alpha faible
éclaircit, sur fond sombre elle assombrit : une même opacité ne peut pas
vouloir dire « plus clair » dans les deux thèmes. Ce qui doit reculer
dans les deux prend sa propre variable, et chaque palette dit comment.

Un texte qui porte de l'information passe le seuil de contraste sur le
fond qu'il a — pas sur le fond de la page.

## 4. L'appartenance se dit en surface, la séparation en un filet

Pour grouper : une surface commune, ou de l'espace. Pour séparer : un
filet d'1 px, un seul. Jamais une boîte par élément.

Les blocs principaux partagent un même retrait horizontal. Le vertical
leur appartient.

Une bordure fait partie de la bande que l'œil voit : un bandeau borduré
en bas est plus profond en haut pour paraître égal.

## 5. Rien n'arrive en poussant la page

Ce qui arrive après coup entre dans une place déjà tenue. Une pochette
de forme inconnue va dans un carré fixe ; un dessin qui se calcule
réserve sa hauteur avant d'exister ; deux faces qui alternent partagent
une cellule, de sorte que la hauteur est celle de la plus grande.

Le corollaire, en masquant :

- **`visibility`** quand la place doit rester tenue.
- **`display`** quand la place doit être rendue.

Et dans les deux cas, **toutes les règles masquent, aucune ne remet
visible**. Écrire « caché par défaut, visible sous telle classe » met
deux règles en concurrence, et le jour où une troisième les couvre
toutes, les deux gagnent en même temps.

## 6. L'affordance et l'effet sont le même ensemble

Ce qui n'aurait aucun effet n'est pas offert : une action impossible est
absente ou éteinte, pas allumée et inerte.

Ce qui a l'air d'agir agit. Ce qui s'allume au survol est ce qu'un clic
atteindra : la zone surlignée et la cible cliquable sont la même.

Un contrôle qui commande répond aussi. Une case « tout sélectionner » qui
ne se décoche pas quand on décoche les lignes dit le contraire de ce que
la liste montre.

## 7. Ce qu'on dit, on le dit près de ce dont on parle

Un libellé, un compteur, un avertissement se placent contre l'élément
qu'ils qualifient, pas dans une zone d'état à l'autre bout de la page.

Le nom de fichier est contre le bouton qui le réécrit ; le transport est
sous le morceau qu'il joue ; la ligne de portée est contre le titre
qu'elle qualifie. Un signe à trois cents pixels de la main qui vient
d'agir n'est pas un signe.

Deux contrôles l'un au-dessus de l'autre dans une colonne finissent au
même endroit : l'œil lit le décalage avant de lire l'un ou l'autre.

## 8. Un libellé nomme son objet

Pas d'adjectif seul, pas de « tout » sans dire tout quoi. Un champ dit ce
qu'il attend. Un bouton dit ce qu'il fait, et deux boutons côte à côte
qui tronquent tous les deux ne disent rien — on les empile plutôt.

Si deux nombres de sens différents sont à l'écran en même temps, chacun
dit lequel il est.

L'avertissement précède ce qu'il avertit. Le compte finit la ligne.

## 9. Ce qui ne varie pas n'occupe pas de place

Une colonne qui répéterait la même valeur sur toutes ses lignes ne gagne
sa place que lorsqu'elle varie. Un zéro n'est pas une mesure : une
colonne de zéros se lit comme un problème compté, et aucun ne l'est —
on n'écrit rien.

Une animation sans alternative ne tourne pas : un tableau à une seule
face est fixe.

## 10. Un geste répété donne le même résultat

Un réglage continu qui n'a pas de valeur exacte à viser se pose sur des
crans, assez gros pour être atteints à la souris. Là où un pixel désigne
un moment voulu — une barre de lecture — on garde le continu.

Un état atteint par deux chemins est un seul état : il n'y a pas deux
silences, l'un par la coupure et l'autre par le niveau à zéro.

## 11. Le clavier voit où il est, et n'est pas la souris

Tout ce que le clavier peut atteindre porte un anneau visible. Un pas de
tabulation qui mène quelque part sans que ça se voie est un pas aveugle.

L'anneau se pose selon le fond : sur une surface, la bordure d'accent
suffit ; sur un aplat d'accent, c'est un anneau en creux, et l'épaisseur
du trait et celle du décalage restent en proportion — le cadre ne doit
pas être plus épais que ce qu'il cadre.

Un bouton cliqué à la souris rend le focus, sans quoi il s'allume à la
touche suivante sans rapport avec elle.

Les flèches agissent selon ce qu'est le contrôle, pas selon ce qui est à
côté : sur un curseur de lecture elles déplacent la tête.

## 12. Au-delà d'une demi-seconde, l'attente se dit

Une attente qu'une personne remarque reçoit un mot, et un nombre quand il
y en a un. Une liste qui met une demi-seconde à se remplacer le dit, au
lieu de rester là en ayant l'air d'être la réponse.

Un compteur vaut mieux que des points de suspension : il fait la
différence entre attendre et s'inquiéter.

## 13. Aucun contrôle n'est laissé au navigateur

Chaque contrôle est dessiné dans la feuille de style. Un seul laissé nu
apporte ses biseaux, son rayon, son anneau de focus, et aucune mise en
page ne le rattrape.

Les icônes sont dessinées, pas tapées : un glyphe Unicode n'existe pas
dans toutes les polices système, et là où il existe il s'affiche à la
taille que cette police a décidée.

Un dessin posé sur un contrôle qui fonctionne est décoratif : il ne
s'annonce pas une seconde fois, le contrôle le fait déjà.
