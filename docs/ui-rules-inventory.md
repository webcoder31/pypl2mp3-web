# Charte d'UI — inventaire à trancher

Brouillon. Chaque ligne est la règle qu'un test d'apparence tient
aujourd'hui, extraite de `tests/test_web_look.py` et rendue à la forme
d'une règle. Les 111 tests du fichier y figurent tous.

Les renvois `test_… (L…)` sont là pour le tri et n'ont pas leur place
dans la charte : une règle qui a besoin de citer son test n'est pas
énoncée. Ils partent quand les lignes sont validées.

Trois sections à la fin ne sont pas des règles et attendent une décision
distincte.

## 1. Échelles et jetons

- Les coins sont arrondis à 2 px au plus ; aucune forme de la page n'est
  une pilule. — `test_nothing_on_the_page_is_a_pill` (L82)
- Toute taille de texte vient d'une échelle nommée. —
  `test_type_sizes_come_from_a_scale` (L329)
- Tout espacement vient d'une échelle nommée. —
  `test_spacing_comes_from_a_scale` (L758)
- Tout mouvement vient d'une échelle nommée, animations comprises. —
  `test_motion_comes_from_a_scale` (L780)
- Aucune propriété personnalisée n'est déclarée deux fois dans un même
  thème. — `test_no_custom_property_is_declared_twice_in_one_theme`
  (L3461)

## 2. Surfaces, cadre et appartenance

- La page n'emprunte jamais le blanc natif du navigateur : toute surface
  est choisie. — `test_the_page_has_designed_surfaces` (L311)
- L'appartenance se dit en fond : la colonne principale est une surface,
  la latérale une autre. —
  `test_the_main_column_is_one_surface_and_the_side_one_another` (L424)
- La colonne latérale est le cadre, la principale le contenu. —
  `test_the_side_column_is_the_frame` (L3231)
- Les deux palettes attribuent les surfaces en sens inverse : en clair le
  contenu prend la plus blanche, en sombre c'est le cadre qui se lève. —
  `test_the_two_palettes_assign_the_surfaces_oppositely` (L3270)
- Tous les blocs principaux partagent un même retrait. —
  `test_every_main_block_shares_one_inset` (L813)
- L'appartenance se dit aussi en blanc : le lecteur s'écarte de la
  liste. — `test_the_player_leans_away_from_the_listing` (L2850)
- Une bordure fait partie de la bande que l'œil voit : un bandeau est
  aussi profond au-dessus qu'en dessous. —
  `test_the_header_band_is_as_deep_above_as_below` (L2944)
- La barre d'outils partage la surface des rangées ; le filet d'1 px est
  tout ce qui l'en sépare. — `test_the_toolbar_is_marked_off_by_its_rule`
  (L1026)
- Un champ se détache de la surface qui le porte, dans les deux thèmes. —
  `test_a_field_stands_off_its_surroundings_in_both_themes` (L3308)

## 3. Couleur

- La couleur marque un état, elle ne décore pas : chaque teinte du
  fichier répond de quelque chose. —
  `test_colour_marks_state_rather_than_decorating` (L406)
- Un score est coloré par la confiance qu'il mérite. —
  `test_a_shazam_score_is_coloured_by_confidence` (L364)
- Un texte porteur d'information passe le seuil de contraste sur le fond
  qu'il a. — `test_the_count_survives_the_lighter_header` (L1076)
- En thème sombre le texte n'est jamais presque blanc : la rampe est
  adoucie. — `test_dark_text_is_not_near_white` (L345)

## 4. Thèmes

- Trois réglages : clair, sombre, et suivre le système. —
  `test_the_theme_offers_three_settings` (L1091)
- Le thème est un attribut, pas une media query — une media query ne sait
  pas dire « sauf si le lecteur en a décidé autrement ». —
  `test_the_theme_is_an_attribute_not_a_media_query` (L1102)
- Un thème explicite ne bouge pas quand le système change. —
  `test_an_explicit_theme_ignores_the_system_changing` (L1164)
- Le thème est appliqué avant le premier rendu. —
  `test_the_theme_is_applied_before_the_first_paint` (L1149)
- Toute variable déclarée dans une palette l'est dans l'autre. —
  `test_both_themes_define_the_same_colours` (L1116),
  `test_every_colour_is_answered_by_both_palettes` (L1708)

## 5. Poids des commandes

- Le remplissage est réservé à ce qui engage. —
  `test_a_playlist_button_is_filled_like_save` (L1231)
- Le reste est un filet et du texte, sans surface ni ombre. —
  `test_ordinary_buttons_sit_back` (L1306)
- Une préférence se marque en texte, pas en segment rempli. —
  `test_the_theme_switch_marks_its_choice_in_text` (L1177)
- Filtrer n'engage à rien : le bouton n'est pas rempli. —
  `test_the_filter_button_is_not_filled` (L1210)
- Dans un texte, un bouton ne porte pas de boîte. —
  `test_buttons_inside_text_carry_no_box` (L480)

## 6. Contrôles

- Aucun contrôle natif n'est laissé tel quel ; la feuille de style les
  habille tous. — `test_every_control_is_drawn_by_the_stylesheet`
  (L175), `test_the_player_is_not_the_browser_s_own` (L65)
- Les icônes sont dessinées, jamais tapées : pas de glyphe Unicode en
  guise d'icône. — `test_the_toolbar_icons_are_drawn_not_typed` (L1396)
- Un bouton d'icône dispose son contenu en rangée plutôt que de
  l'asseoir sur la ligne de base. —
  `test_an_icon_button_lays_its_contents_out_in_a_row` (L2922)
- Un bouton est dimensionné pour être atteint, sans faire grandir la
  rangée qui le porte. — `test_a_transport_button_is_big_enough_to_hit`
  (L2546)
- Un curseur répond aux flèches selon ce qu'il est : la barre de lecture
  déplace la tête, pas la file. —
  `test_the_seek_bar_does_not_also_change_track` (L107)
- Un bouton cliqué à la souris rend le focus. —
  `test_a_clicked_transport_button_hands_the_focus_back` (L3352)
- Tout ce qu'un clavier peut atteindre porte un anneau visible. —
  `test_the_last_field_leads_somewhere_visible` (L3379)
- Une action sans effet n'est pas offerte. —
  `test_a_junk_song_is_offered_no_junkize` (L676),
  `test_nothing_to_play_offers_nothing` (L2990)
- Ce qui a l'air d'agir agit. — `test_the_junk_figure_does_what_it_looks_like`
  (L3065)
- Un contrôle qui commande des rangées leur répond aussi. —
  `test_select_all_answers_the_rows_as_well_as_commanding_them` (L3027)
- Un dessin décoratif posé sur un contrôle ne s'annonce pas une seconde
  fois. — `test_the_waveform_is_decoration_over_a_working_control`
  (L2644)
- Un réglage sans valeur exacte à viser se pose sur un cran : le même
  geste deux fois donne le même nombre. — `test_the_level_lands_on_a_notch`
  (L2342)
- Un état atteint par deux chemins est un seul état. —
  `test_silence_is_one_state_however_it_was_reached` (L2421)

## 7. Structure de la page

- Le morceau au-dessus de la liste, la liste sur toute la largeur de sa
  colonne, la navigation de côté. —
  `test_the_layout_puts_the_song_above_the_listing` (L497)
- Le panneau est visible depuis les deux onglets : il est au-dessus de la
  bande d'onglets, pas dedans. —
  `test_the_inspector_is_visible_from_either_tab` (L2888)
- Le transport est sous le morceau qu'il joue, plutôt qu'épinglé au pied
  de la fenêtre. — `test_the_transport_sits_under_the_song_it_plays`
  (L714)
- Ce qui parle de la file partage une rangée. —
  `test_the_toolbar_carries_the_queue_readout` (L898)
- Le lecteur tient sur une rangée. — `test_the_player_is_one_row` (L985)
- La colonne latérale s'échelonne avec la fenêtre, bornée des deux
  côtés : le plancher garde le plus long nom lisible, le plafond
  l'empêche de manger la liste. —
  `test_the_side_column_scales_with_the_window` (L1522)
- Sous le point de rupture, la colonne latérale cède : c'est la liste qui
  est rare. — `test_the_side_column_gives_way_when_the_listing_is_squeezed`
  (L3100)
- La pochette est à côté des champs, pas au-dessus. —
  `test_the_cover_sits_beside_the_fields` (L555)
- Une étiquette est à côté de son champ. —
  `test_a_label_sits_beside_its_field` (L581)
- Le panneau prend la largeur qu'il a. —
  `test_the_inspector_uses_the_width_it_has` (L1497)
- Deux contrôles l'un au-dessus de l'autre dans la même colonne finissent
  au même endroit. — `test_the_volume_ends_where_the_cover_ends` (L2377)
- Une seule règle décide l'alignement vertical des cellules de toutes les
  tables. — `test_the_imports_rows_are_centred_like_every_other_row`
  (L1254)

## 8. Le lecteur

- L'ordre de lecture est un fait nommé par un sélecteur, pas trois
  boutons qui laissent deviner lequel on entend. —
  `test_the_switch_says_which_order_is_playing` (L1437)
- Le transport dit dans quel sens la file est parcourue, près de la main
  qui l'a changé. —
  `test_the_transport_says_which_way_the_queue_is_walked` (L2462)
- Un lien ne figure qu'une fois, à côté de ce qu'il désigne. —
  `test_the_player_carries_no_second_video_link` (L1004)
- La longueur du suivant vient après son nom et reste séparable de lui. —
  `test_the_next_up_length_comes_after_the_name_and_survives_it` (L2120)
- Le volume a une largeur fixe et ne prend jamais à la timeline. —
  `test_the_volume_never_takes_from_the_timeline` (L2181)
- Le haut-parleur et la piste sont deux moitiés d'un seul acte : ils
  s'allument ensemble et n'ont qu'un cadre. —
  `test_the_volume_lights_as_one_and_the_speaker_has_no_frame` (L2225)
- En clair, le niveau emprunte les verts de la timeline plutôt que
  l'accent. —
  `test_the_level_borrows_the_timeline_greens_on_a_light_screen` (L2289)

## 9. Le waveform

- Le waveform est dessiné dans le curseur, pas à côté. —
  `test_the_waveform_is_drawn_inside_the_slider` (L1641)
- La barre simple reste le repli : jamais de boîte vide là où était la
  position. — `test_the_plain_bar_stays_as_the_fallback` (L1663)
- Le reflet est le même nombre une seconde fois, plus court et plus
  pâle. — `test_the_reflection_is_shorter_and_fainter_than_the_crest`
  (L2663)
- La frontière de couleur avance de moins d'une barre. —
  `test_the_colour_boundary_moves_by_less_than_a_bar` (L2707)
- Une barre a la même largeur dans n'importe quelle taille de boîte. —
  `test_a_bar_is_the_same_width_in_any_size_of_box` (L2742)
- Le rééchantillonnage garde la plus forte de chaque groupe, pas la
  moyenne. — `test_the_bars_dropped_by_resampling_are_the_quiet_ones`
  (L2789)
- Le dessin suit la cadence de l'affichage pendant la lecture et s'arrête
  avec elle. —
  `test_the_picture_follows_the_display_only_while_it_plays` (L2820)
- Les durées sont dans la bande laissée libre sous la ligne de base. —
  `test_the_times_sit_in_the_band_under_the_baseline` (L2575)

## 10. Le tableau de départs

- La ligne meta tient ses faces sur une seule ligne. —
  `test_the_meta_line_holds_its_faces_and_only_one_line` (L1762)
- Un volet bascule depuis son bord haut, pas autour de son milieu. —
  `test_a_slot_turns_like_a_flap_and_not_like_a_fade` (L1818)
- Un caractère qui se pose refroidit de l'accent vers la ligne, de sorte
  qu'un regard en retard voit encore ce qui a bougé. —
  `test_a_landed_character_cools_from_the_accent_to_the_line` (L1855)
- Un tableau à une seule face ne tourne pas. —
  `test_the_board_holds_each_face_and_stops_when_there_is_one` (L1924)

## 11. Le panneau

- Deux panneaux qui éditent les mêmes balises gardent le même balisage. —
  `test_the_two_panels_keep_the_same_fields` (L626)
- Ce qui agit sur le morceau tel qu'il est se tient avec les autres
  actions ; seul l'enregistrement soumet le formulaire. —
  `test_junkize_stands_with_the_other_song_actions` (L653)
- Le nom de fichier est à côté du bouton qui le réécrit. —
  `test_the_filename_sits_beside_the_button_that_rewrites_it` (L688)
- La pochette est un carré de taille fixe : changer de morceau ne fait
  pas sauter les champs. — `test_the_cover_is_a_fixed_square` (L1321)
- Une ressource qui change change d'adresse. —
  `test_the_cover_address_changes_when_the_picture_does` (L1973)
- La pochette se fond d'un morceau au suivant, sans carré vide entre les
  deux. — `test_the_cover_dissolves_between_songs` (L2030)
- Le panneau dit quand il retient des modifications. —
  `test_the_panel_says_when_it_is_holding_edits` (L2972)
- Un champ dit ce qu'il attend. —
  `test_the_cover_field_is_short_and_says_it_wants_a_url` (L606)

## 12. Listes, navigation, compteurs

- Une colonne qui répète la même valeur sur toutes ses lignes ne gagne
  pas sa place. — `test_the_playlist_column_goes_when_it_says_nothing`
  (L129)
- Une rangée de navigation est un seul bouton : ce qui est surligné est
  ce qui est cliquable. — `test_a_nav_row_is_one_button` (L1594)
- Le libellé tronque, le compte jamais. —
  `test_the_nav_label_truncates_and_the_count_does_not` (L1624)
- Deux titres de même nature sur deux listes de même nature se traitent
  pareil. — `test_both_lists_in_the_nav_say_how_long_they_are` (L3144)
- La ligne de portée est avec le titre qu'elle qualifie. —
  `test_the_scope_line_sits_with_the_heading_it_qualifies` (L3166)
- Une seule sortie : la ligne de portée n'en offre pas une seconde. —
  `test_the_scope_line_offers_no_second_way_out` (L3183)
- La rangée qui couvre tout n'est pas un élément de plus dans la liste ;
  le poids le dit, pour elle et pour son compte. —
  `test_the_whole_library_row_is_not_a_fourth_playlist` (L3202)
- Deux compteurs qui disent des choses différentes disent laquelle. —
  `test_the_two_counts_say_which_is_which` (L3046)
- Un compteur qui en remplace un autre dit ce que l'autre disait. —
  `test_the_counter_still_shows_the_selection_size` (L946)
- L'avertissement précède ce qu'il avertit ; le compte finit la ligne. —
  `test_the_junk_mark_leads_and_the_count_ends_the_line` (L3120)
- La liste suit le morceau, et seulement quand il change. —
  `test_the_listing_follows_the_song_but_only_when_it_changes` (L3004)
- Au-delà d'une demi-seconde, la liste dit qu'elle est en train d'être
  remplacée plutôt que de rester là en ayant l'air d'être la réponse. —
  `test_the_listing_says_when_it_is_being_replaced` (L3084)

## 13. Libellés et format

- Un libellé nomme le nom, pas seulement l'adjectif. —
  `test_the_junk_checkbox_names_what_it_filters` (L1548),
  `test_the_unfiltered_row_names_what_it_covers` (L1568)
- Un bouton dit ce qu'il fait ; deux boutons tronqués côte à côte ne
  disent rien. — `test_the_import_button_says_what_it_does` (L841)
- Une durée ne montre pas d'heures vides. —
  `test_durations_lose_their_empty_hours` (L120),
  `test_the_inspector_shows_a_short_duration` (L572)

## 14. Ce qui ne bouge pas

- Ce qui arrive après coup entre dans une place déjà tenue. —
  `test_a_waveform_arriving_does_not_move_the_page` (L1689)

## 15. Ce qui est servi ici

- Rien de ce que la page va chercher d'elle-même ne vient d'ailleurs que
  d'ici ; une adresse distante ne peut être que ce qu'on choisit
  d'ouvrir. — `test_the_page_reaches_no_host_it_does_not_serve` (L249)

---

# Ce qui n'est pas une règle

## Gardes de régression

Chacun tient un défaut précis qui a eu lieu, pas une règle. Ils gardent
leur valeur de garde et n'ont rien à faire dans une charte : la règle
qu'ils énoncent serait « ne pas refaire cette erreur-là ».

- `test_the_listing_is_placed_by_its_own_column` (L529) — une
  `grid-area` nommant une zone que le parent ne définit plus.
- `test_the_toolbar_is_not_swept_away_by_a_refetch` (L923) — la barre
  d'outils emportée par le fragment qu'un filtre recharge.
- `test_the_scrub_bar_keeps_its_own_line` (L958) — des règles perdues
  par une édition trop large.
- `test_the_actions_row_keeps_its_bottom_margin_to_itself` (L1367) — une
  marge qui s'échappe par fusion à travers le formulaire.
- `test_the_panel_s_own_margins_outrank_its_paragraph_rule` (L3435) —
  une classe qui ne peut pas battre un id.
- `test_the_switch_is_updated_by_the_code_that_changes_the_order`
  (L1474) — rendu à l'arrivée et jamais ensuite.

## Mécanique, sans contenu de design

- `test_a_junkized_row_matches_the_rows_around_it` (L153) — la rangée
  lit `HX-Current-URL` pour savoir ce que la page affiche.
- `test_the_transport_reports_and_seeks` (L96) — l'écouteur
  `timeupdate`, l'affectation de `currentTime`, la garde `isFinite`.

## Ce que personne ne signerait

- `test_the_density_switch_is_gone` (L541) — « le sélecteur de densité
  n'existe pas ». Une absence n'est pas une règle : tant que rien ne
  cherche à le réintroduire le test ne protège rien, et le jour où on
  voudrait le réintroduire il serait le seul obstacle.
- `test_the_cover_field_is_short_and_says_it_wants_a_url` (L606) épingle
  le libellé exact du champ. La règle — un champ dit ce qu'il attend —
  est bonne ; le mot est un réglage.
