# Interface web pour PYPL2MP3 — conception

**Date** : 2026-08-11
**Statut** : validé, prêt pour planification
**Projet** : `pypl2mp3-web`, cloné depuis `pypl2mp3` (gelé)

---

## 1. Intention

L'outil tire sa valeur de deux capacités :

1. récupérer des fichiers audio depuis YouTube ;
2. valider et corriger leurs métadonnées (titre, auteur, pochette) via Shazam.

Tout le reste est de l'habillage destiné à rendre ces deux capacités utilisables.
C'est cet habillage qu'on améliore ici, en ajoutant une interface web servie
localement, avec **parité complète** avec les huit commandes actuelles.

La CLI n'est pas retirée : elle devient une façade parmi deux.

### Frictions visées

| Friction | Origine |
|---|---|
| Correction Shazam pénible | Suite de questions `oui/non`, sans pochette visible, sans écoute, sans retour arrière |
| INDEX volatils | Aucun état ne persiste entre deux invocations, d'où la nécessité de re-lister avant chaque action |
| Pas de vue d'ensemble | Aucun état agrégé ; il faut interroger commande par commande |
| Premier contact | Installation, configuration par variables d'environnement, découvrabilité |

Les trois premières partagent une racine unique : l'outil est une collection de
commandes sans mémoire. La quatrième est un problème de distribution, traité
séparément et hors périmètre de ce document.

---

## 2. Décisions structurantes

### 2.1 Interface graphique web locale, servie par Python

Retenu contre une TUI terminal et contre une application desktop native.

**Pourquoi une GUI plutôt qu'une TUI** : la correction Shazam est intrinsèquement
visuelle. Comparer des métadonnées, **voir la pochette**, écouter un extrait pour
trancher. Un terminal n'affiche pas d'image ; aujourd'hui l'utilisateur valide une
pochette sans la voir.

**Pourquoi le web plutôt que Qt/PySide6** : le navigateur gère nativement les
images et la lecture audio, il n'y a aucun empaquetage ni signature à produire
sur macOS, et la portabilité est acquise. Qt imposerait ~100 Mo de dépendance,
la réimplémentation du lecteur audio et une chaîne de distribution pénible.

**Pourquoi pas de front React/Vite** : cela ajouterait une chaîne Node/npm à
maintenir en plus de Python, pour un projet à mainteneur unique.

### 2.2 Extraction d'une couche de services

Retenu contre deux alternatives :

- **Envelopper les commandes en capturant `stdout`** — écarté. Il faudrait
  analyser du texte ANSI pour reconstituer des données structurées, et surtout
  les seize points d'interaction bloquante bloqueraient le serveur. Inapte à la
  parité sur `fix -p`, `import -p` et `play`.
- **Implémentation parallèle** (le web parle directement à `libs/`, la CLI reste
  intacte) — écarté. La parité complète conduirait à dupliquer l'intégralité de
  l'orchestration ; un correctif appliqué d'un côté serait oublié de l'autre.

### 2.3 Le projet actuel est gelé

`pypl2mp3` reste en l'état comme référence. Le développement se poursuit
uniquement ici. Les deux dépôts restent liés par un remote `upstream` afin qu'un
report de correctif reste possible si cette décision est revue.

---

## 3. État du code hérité

Mesuré sur la base de départ. Détermine l'ampleur réelle du travail.

| Module | Lignes | dont affichage | Réutilisable tel quel |
|---|---|---|---|
| `libs/repository.py` | 556 | 0 | oui, intégralement |
| `libs/song.py` | 1777 | 18 | oui — piloté par callbacks |
| `commands/fix_junks.py` | 733 | 115 | non |
| `commands/import_playlist.py` | 590 | 65 | non |
| `commands/play_songs.py` | 334 | 11 | non — spécifique terminal |
| `commands/list_playlists.py` | 151 | 12 | après allègement |
| `commands/junkize_songs.py` | 149 | 5 | après allègement |
| `commands/list_junks.py` | 133 | 8 | après allègement |
| `commands/list_songs.py` | 87 | 3 | après allègement |
| `commands/browse_videos.py` | 80 | 2 | après allègement |

**Le noyau métier est déjà prêt.** Le couplage à la console est concentré dans les
modules de commandes, et surtout dans les deux qui portent la valeur.

`song.py:514-535` expose quinze points d'accroche (`pre_`/`on_`/`post_` pour la
récupération d'infos, le téléchargement, l'encodage MP3, la pochette et le
Shazam). Le travail le plus ingrat d'un portage GUI — démêler les `print` du code
métier — est donc déjà fait dans le domaine.

**Seize points d'interaction bloquante** (`input()`, `prompt_user`, `sshkeyboard`)
constituent la vraie difficulté : en CLI on bloque sur une saisie, sur un serveur
c'est interdit.

---

## 4. Stack

| Rôle | Choix | Justification |
|---|---|---|
| Serveur | FastAPI + uvicorn | Le code est déjà asynchrone (36 `async`/`await` dans `song.py`, `shazamio` async, `main.py` fait `asyncio.run`). Un framework synchrone imposerait des ponts entre boucles d'événements. WebSockets natifs. |
| Rendu | Jinja2 (fragments serveur) | Aucune étape de build ; toute la logique reste en Python. |
| Interactivité | HTMX | Le domaine est fait de listes, détails et formulaires — son terrain exact. |
| État client | Alpine.js | Lecteur audio et raccourcis clavier : état purement client, sans aller-retour serveur. |
| Temps réel | WebSocket | Bidirectionnel. Les SSE ne descendraient que du serveur, incapables de porter les réponses aux questions. |
| Tâches longues | Registre `asyncio` en mémoire | Outil local mono-utilisateur. Pas de Celery ni Redis : le principe « no database dependencies » est conservé. |
| Tests | pytest + pytest-asyncio + httpx | Les deux premiers sont **déjà installés** (tirés par `shazamio`). Seul `httpx` est à ajouter. |

**Dépendances ajoutées** : `fastapi`, `uvicorn`, `jinja2`, `httpx`.
**Fichiers statiques versionnés** : `htmx.min.js`, `alpine.min.js` — déposés dans
le dépôt plutôt que chargés depuis un CDN, pour rester utilisable hors ligne et
sans dépendance réseau à l'exécution.

**Résolution vérifiée le 2026-08-12** (`uv pip compile`, Python 3.13) :

```
fastapi==0.125.0   starlette==0.50.0   uvicorn==0.52.1
httpx==0.28.1      jinja2==3.1.6
anyio==3.7.1       pydantic==1.10.26
```

Aucun conflit. `anyio` reste en 3.7.1 — Starlette 0.50 l'accepte — et `shazamio`
est préservé en 0.4.0.1.

**Contrainte à retenir : `pydantic` est maintenu en 1.x par `shazamio`.** FastAPI
fonctionnera donc sur son chemin de compatibilité pydantic v1. Conséquences :

- Ne pas employer les API pydantic v2 (`model_validate`, `model_dump`,
  `Annotated`-style validators, `ConfigDict`).
- Les modèles de requête et de réponse s'écrivent en syntaxe pydantic 1.x
  (`class Config`, `parse_obj`, `dict()`).
- Si un besoin exigeait pydantic v2, il faudrait d'abord traiter `shazamio` —
  hors périmètre, et à mettre en balance avec le fait qu'il porte le cœur de
  valeur n°2.

### Réglages par défaut

- Écoute sur `127.0.0.1` exclusivement, jamais `0.0.0.0`. L'outil est local ; il
  ne doit pas se retrouver exposé au réseau par inadvertance.
- Dépendances principales plutôt qu'extra optionnel `[ui]` : le poids ajouté est
  négligeable et la GUI n'est pas un accessoire puisqu'on vise la parité.

---

## 5. Architecture

Principe : **une seule orchestration, deux façades**.

```
libs/          domaine, INCHANGÉ
  repository.py    (556 l., 0 affichage)
  song.py          (1777 l., callbacks)
  logger.py  utils.py  exceptions.py

ports/         contrats
  interaction.py   poser une question, obtenir une réponse
  progress.py      signaler l'avancement

services/      orchestration sans affichage
  import_playlist.py  fix_junks.py  junkize_songs.py
  list_playlists.py   list_songs.py  list_junks.py
  browse_videos.py    play_songs.py
  _song_callbacks.py  adaptateur ProgressPort → les callbacks de song.py
                      (un constructeur par API : create_from_youtube,
                      update_cover_art, shazam_song)

cli/           façade terminal (les commands/ actuelles, allégées)
  console_interaction.py  console_progress.py  + 8 modules d'affichage

web/           façade navigateur
  app.py  jobs.py  ws.py
  web_interaction.py  web_progress.py
  routers/  templates/  static/
```

Les services reçoivent leurs ports par injection et ignorent s'ils s'adressent à
un terminal ou à un navigateur. C'est ce qui garantit que les deux interfaces ne
peuvent pas diverger.

Les ~220 lignes d'affichage aujourd'hui mêlées à l'orchestration descendent dans
`cli/`.

### Nommage

| Élément | Valeur | Raison |
|---|---|---|
| Dépôt / projet | `pypl2mp3-web` | Distingue sans ambiguïté des deux côtés |
| Package Python | `pypl2mp3` (inchangé) | Évite de toucher une quarantaine d'imports pour un gain nul |
| Commande CLI | `pypl2mp3` (inchangée) | Les habitudes et scripts existants continuent de fonctionner |
| Lancement GUI | `pypl2mp3 ui` | Sous-commande, cohérente avec les huit autres |

**Conséquence** : les deux projets exposant la même commande `pypl2mp3`, ils ne
peuvent pas être installés simultanément sans que l'un masque l'autre. Sans effet
tant que l'ancien reste gelé.

---

## 6. Port d'interaction

Le seul endroit où les deux mondes sont réellement incompatibles. Le contrat
reprend la signature déjà présente dans `utils.py:412` :

```python
class InteractionPort(Protocol):
    async def ask(self, question: str, options: list[str]) -> str: ...
```

- **`ConsoleInteraction`** — appelle l'`input()` existant. Le comportement CLI
  actuel est préservé à l'identique.
- **`WebInteraction`** — pousse la question dans le WebSocket, crée une
  `asyncio.Future`, l'attend. À l'arrivée de la réponse, la Future est résolue et
  le service reprend où il en était.

Cette approche **ne réécrit pas les parcours interactifs** : `fix -p` garde sa
logique séquentielle. Seul le mécanisme d'attente change. Les seize points
bloquants se ramènent à cette unique interface.

### Cas limites à traiter explicitement

1. **Le navigateur se ferme pendant une question** — la Future est annulée avec
   une exception dédiée ; le service traite cela comme un abandon, pas comme un
   plantage.
2. **Deux onglets ouverts** — une question n'est posée qu'à un seul client, sinon
   deux réponses contradictoires arrivent. Le registre de tâches désigne un
   client propriétaire.
3. **Réponse invalide** — la validation reste côté service, jamais côté
   navigateur, afin que la CLI en bénéficie également.

---

## 7. Port de progression

```python
class ProgressPort(Protocol):
    def stage_started(self, stage: str, label: str) -> None: ...
    def stage_progress(self, stage: str, percent: float) -> None: ...
    def stage_done(self, stage: str) -> None: ...
    def song_identified(self, artist: str, title: str, score: float) -> None: ...
```

`song.py` **conserve ses paramètres de callback**. Un adaptateur unique
(`services/_song_callbacks.py`) projette le port sur ces paramètres ; écrit une
fois, utilisé par tous les services.

Trois API acceptent des hooks, et chacune n'accepte que les siens : d'où un
constructeur par API, `create_from_youtube_callbacks`,
`update_cover_art_callbacks` et `shazam_song_callbacks`. Splater le mauvais
dictionnaire lève un `TypeError`.

**Deux pièges que l'adaptateur neutralise** — les migrations suivantes en
héritent, elles n'ont rien à refaire :

- `create_from_youtube` réécrit ses quinze callbacks avec ses propres closures
  d'affichage tant que `use_default_verbosity` vaut `True`, et les annule tous
  si `verbose` ne vaut pas `True`. Les deux drapeaux sont donc inclus dans le
  dictionnaire rendu (`verbose=True, use_default_verbosity=False`).
- les hooks `pre_`/`post_` sont attendus (`await`) ; le callback d'un
  `ProgressBarInterface`, non. `async def` d'un côté, `def` de l'autre.

**Pourquoi ce sens** : `song.py` fait 1777 lignes et c'est le seul module qui
télécharge et tague réellement. Y toucher reviendrait à risquer le cœur de valeur
pour un gain cosmétique. L'adaptateur coûte une centaine de lignes et isole la
verrue.

Implémentations : `ConsoleProgress` enveloppe la `ProgressBarInterface`
existante ; `WebProgress` émet des événements WebSocket.

**Ces méthodes sont synchrones et ne doivent jamais bloquer**, contrairement à
`InteractionPort.ask` qui est `async`. La raison : elles sont appelées depuis les
callbacks de `song.py`, au cœur de boucles de téléchargement où une attente
dégraderait le débit. `WebProgress` se contente donc de déposer l'événement dans
une file ; c'est une tâche distincte qui la vide vers le WebSocket.

L'asymétrie est voulue : signaler un avancement n'attend rien, poser une question
attend une réponse.

### Piège vérifié : les hooks Shazam doivent être asynchrones

Le port est synchrone, mais **les deux hooks Shazam que l'adaptateur fournit à
`song.py` ne le sont pas**. `song.py` les attend avec `await` :

- `song.py:1477` → `await pre_shazam_song(self)`
- `song.py:1595` → `await post_shazam_song(self)`

Leur passer une fonction synchrone provoque
`TypeError: object NoneType can't be used in 'await' expression` **sur chaque
chanson**. Constaté et reproduit le 2026-08-12 pendant l'implémentation du plan 1.

Les trois callbacks de `ProgressBarInterface` (`on_download_audio`,
`on_mp3_encode`, `on_download_cover_art`) sont au contraire appelés **sans**
`await` et doivent rester synchrones.

Règle générale à appliquer pour tout nouveau hook branché sur `song.py` :
vérifier le site d'appel réel avant de choisir `def` ou `async def`, et écrire
un test qui exerce le hook **par la même voie que `song.py`** — un test qui
appelle un hook asynchrone sans `await` ne détecte rien.

---

## 8. Cycle de vie des tâches longues

Registre en mémoire, un `Job` par opération :

```
pending → running → completed
                  ↘ failed
                  ↘ cancelled
```

Chaque `Job` porte sa tâche `asyncio` et **un tampon circulaire de ses derniers
événements**, qui permet à un navigateur rouvert de rattraper l'état au lieu de
repartir aveugle — indispensable quand un import dure des heures.

### Règles

- **Un seul job d'import par playlist à la fois.** Deux imports concurrents sur
  le même dossier téléchargeraient deux fois les mêmes titres.
- **L'annulation préserve le partiel.** `task.cancel()` lève `CancelledError`
  dans le service, qui la laisse remonter proprement ; les MP3 déjà écrits
  restent valides.
- **L'arrêt du serveur tue les jobs**, et c'est acceptable : le système de
  fichiers est la source de vérité. Un import interrompu se reprend par un
  nouveau sync, qui ne retéléchargera que ce qui manque. C'est précisément
  pourquoi aucune base de données n'est nécessaire.

---

## 9. Parité des huit commandes

| Commande | Web | Note |
|---|---|---|
| `import` | oui | Progression en direct, prompts via WebSocket |
| `fix` | oui | Pochette visible, écoute de l'extrait, validation |
| `playlists` | oui | Vue d'ensemble. Voir la restriction ci-dessous sur les « nouveautés ». |
| `songs` | oui | Liste filtrable |
| `junks` | oui | Liste filtrable |
| `junkize` | oui | Action sur sélection |
| `videos` | oui | Simple lien vers YouTube |
| `play` | oui | **Divergence assumée** — lecture par `<audio>` dans le navigateur ; `pygame` et `sshkeyboard` restent côté CLI. Le service se réduit à sélectionner et servir le fichier. |

`play` est la seule commande dont les deux façades divergent réellement, par
nature du média.

### Restriction sur les « nouveautés »

Détecter les titres ajoutés côté YouTube exige d'énumérer la playlist distante,
soit un aller-retour réseau dont le coût croît avec la taille de la playlist et
**dont la durée n'est pas prévisible** : elle dépend de la qualité de la liaison
au moment de l'appel. Sur une connexion normale, l'opération se compte en
secondes ; en conditions dégradées elle peut prendre des dizaines de minutes
(observé le 2026-08-11 sur une liaison à ~18 Kio/s avec coupures — cas extrême,
non représentatif).

C'est cette imprévisibilité, et non un coût élevé en soi, qui interdit de placer
l'opération sur le chemin synchrone d'un affichage. Deux comportements retenus :

- **Par défaut** : seules les données locales sont affichées — nombre de titres,
  nombre de junks. Immédiat, aucun appel réseau.
- **Sur demande explicite** : un bouton « chercher les nouveautés » lance un job
  de comparaison, dont le résultat est mis en cache et horodaté. L'interface
  affiche la fraîcheur de l'information plutôt que de laisser croire à un état
  temps réel.

Cette restriction vaut aussi pour la CLI : aucune commande de listing local ne
doit déclencher d'appel réseau implicite.

---

## 10. Gestion d'erreurs

Trois règles, chacune issue d'une panne réellement observée le 2026-08-11.

**1. Distinguer l'échec d'un élément de l'échec fatal.** Une coupure réseau sur
une vidéo a tué trente-quatre imports. Dans toute boucle sur des éléments, une
exception est capturée, consignée au rapport, et la boucle continue. Seul l'échec
de la résolution de playlist est fatal.

**2. Les accès paresseux sont un piège de classe.** `YouTube(url)` ne fait aucune
E/S ; la requête part au premier accès d'attribut. **Tout accès à un attribut
pytubefix doit se trouver à l'intérieur du bloc protégé.** Le gestionnaire
d'erreur existait déjà mais surveillait le constructeur, qui ne peut pas échouer.

**3. Codes de sortie.** L'outil rend aujourd'hui `0` même après une erreur
critique, ce qui fait croire au succès à un script appelant. Code non nul sur
échec fatal. L'équivalent web est le statut `failed` du job, accompagné d'un
rapport d'échecs calqué sur l'`ImportReport` existant.

---

## 11. Tests

Le projet hérité n'en a aucun. La couche de services les rend possibles, les
ports se remplaçant par des doublures :

- **`FakeInteraction`** — répond selon un script prédéfini. Rend testables
  `fix -p` et `import -p`, aujourd'hui intestables puisqu'ils attendent une
  frappe humaine.
- **`FakeProgress`** — enregistre les événements reçus ; on vérifie que la
  progression est signalée sans dépendre d'un affichage.
- **API** — `httpx` sur l'application FastAPI, sans réseau réel.

**Premier test à verser** : la régression du correctif « accès paresseux »
(bouchon levant `RemoteDisconnected` sur l'accès d'attribut). Il échoue sur le
code d'avant, passe sur le code d'après.

**Hors de portée des tests** : l'accès réel à YouTube et à Shazam. Ces chemins ne
se valident qu'en exécution.

---

## 12. Hors périmètre

- **Le premier contact** (installation, configuration, découvrabilité) — quatrième
  friction identifiée, de nature distincte. Fera l'objet d'un travail séparé.
- **Le découpage de `song.py`** (1777 lignes) — tentant, mais c'est le module qui
  porte le cœur de valeur. Intouché ici.
- **L'authentification** — inutile sur une écoute `127.0.0.1` mono-utilisateur.
- **Le report de correctifs vers `pypl2mp3`** — le projet est gelé ; le remote
  `upstream` préserve seulement la possibilité de revoir cette décision.
