"""Corpus d'ÉVALUATION hors ligne pour calibrer le classement (aucun réseau).

Fiches représentatives de la future base : sections de documents de référence (souvent en anglais), actualités
(fraîches, nombreuses), appels d'offres, discussions, signaux médias et sociaux, avec des LEURRES volontaires
(actualité récente qui partage les mots de la requête mais ne répond pas au besoin). Les titres et résumés sont
rédigés pour l'évaluation (paraphrases courtes), ce ne sont pas des copies des documents.

Format d'une ligne : id | source | canal | type_doc | confiance | domaine | âge (jours) | ref | titre | résumé
"""

LIGNES = r"""
nist-1|nist-sp800-documents|document|norme|A|normes_documentation|400|NIST SP 800-63B-4 §3.1.1|Passwords|Requirements for password authenticators: minimum length of 15 characters for single-factor, at least 8 with MFA, no composition rules.
nist-2|nist-sp800-documents|document|norme|A|normes_documentation|400|NIST SP 800-63B-4 §3.1.1.2|Password verifiers|Verifiers shall compare passwords against blocklists of compromised values and shall not require periodic password changes.
nist-3|nist-sp800-documents|document|norme|A|normes_documentation|400|NIST SP 800-63B-4 §3.2.12|Storage of secrets|Passwords shall be salted and hashed using a suitable password hashing scheme; memory-hard functions recommended.
nist-4|nist-sp800-documents|document|norme|A|normes_documentation|400|NIST SP 800-63B-4 §5.1|Session management|Session secrets, cookies and access tokens; reauthentication timeouts by assurance level.
nist-5|nist-sp800-documents|document|norme|A|normes_documentation|400|NIST SP 800-63B-4 §2.2|Multi-factor authentication|Authenticator assurance level 2 requires two distinct authentication factors such as OTP or cryptographic device.
owasp-1|owasp-cheatsheets|document|guide|B|normes_documentation|200|OWASP Password Storage CS — Argon2id|Password Storage: Argon2id|Use Argon2id with minimum memory and iteration settings; bcrypt or scrypt for legacy systems; never encrypt passwords.
owasp-2|owasp-cheatsheets|document|guide|B|normes_documentation|200|OWASP Authentication CS — Password strength|Implement proper password strength controls|Minimum length, allow all characters, check against breached password lists, no forced rotation.
owasp-3|owasp-cheatsheets|document|guide|B|normes_documentation|200|OWASP Session CS — Cookies|Session ID cookies|Secure, HttpOnly and SameSite attributes for session cookies; session expiration and renewal after login.
owasp-4|owasp-cheatsheets|document|guide|B|normes_documentation|200|OWASP Authentication CS — MFA|Multi-factor authentication|MFA is the best defense against password-related attacks such as credential stuffing.
owasp-5|owasp-top10|document|norme|B|normes_documentation|700|OWASP Top 10 A03|Injection|Injection flaws including SQL injection; use parameterized queries and input validation.
anssi-1|anssi-guides|document|guide|A|normes_documentation|1100|ANSSI Guide authentification R21|Recommandation sur la longueur des mots de passe|Définir une politique de mots de passe : longueur minimale selon le niveau de sécurité, phrases de passe encouragées.
anssi-2|anssi-guides|document|guide|A|normes_documentation|1100|ANSSI Guide authentification R25|Stockage des mots de passe|Stocker les mots de passe sous forme d'empreinte avec une fonction de dérivation adaptée et un sel aléatoire.
anssi-3|anssi-guides|document|guide|A|normes_documentation|1100|ANSSI Guide authentification R5|Authentification multifacteur|Privilégier l'authentification multifacteur pour les accès sensibles et les comptes d'administration.
anssi-4|anssi-guides|document|guide|A|normes_documentation|900|ANSSI Guide d'hygiène mesure 7|Sauvegardes régulières|Effectuer des sauvegardes régulières, hors ligne, et tester la restauration.
anssi-5|anssi-guides|document|guide|A|normes_documentation|900|ANSSI Guide d'hygiène mesure 22|Journalisation|Activer et centraliser la journalisation des événements de sécurité ; conserver les journaux.
cnil-1|cnil-referentiels|document|guide|A|normes_documentation|1000|CNIL Délibération mots de passe art. 2|Recommandation CNIL relative aux mots de passe|La CNIL fixe des exigences de complexité et de longueur des mots de passe selon les mesures complémentaires.
cnil-2|cnil-referentiels|document|guide|A|normes_documentation|600|CNIL Guide sous-traitant|Guide du sous-traitant RGPD|Obligations du sous-traitant : contrat, clauses obligatoires, registre, sécurité, notification des violations au responsable.
cnil-3|cnil-referentiels|document|guide|A|normes_documentation|500|CNIL Guide sécurité fiche 4|Sécuriser les postes de travail|Verrouillage automatique, mises à jour, antivirus et chiffrement des postes nomades.
cnil-4|cnil-referentiels|document|guide|A|normes_documentation|500|CNIL Guide sécurité fiche 12|Gérer les violations de données|Documenter les violations de données et notifier la CNIL sous 72 heures en cas de risque.
rgpd-28|eurlex-rss|document|loi|A|droit|3100|RGPD art. 28|Article 28 — Sous-traitant|Le traitement par un sous-traitant est régi par un contrat qui prévoit l'objet, la durée, la sécurité, l'assistance au responsable du traitement.
rgpd-32|eurlex-rss|document|loi|A|droit|3100|RGPD art. 32|Article 32 — Sécurité du traitement|Mesures techniques et organisationnelles appropriées : pseudonymisation, chiffrement, résilience, tests réguliers.
rgpd-33|eurlex-rss|document|loi|A|droit|3100|RGPD art. 33|Article 33 — Notification d'une violation de données|Notification à l'autorité de contrôle dans les meilleurs délais et au plus tard 72 heures après en avoir pris connaissance.
rgpd-6|eurlex-rss|document|loi|A|droit|3100|RGPD art. 6|Article 6 — Licéité du traitement|Bases légales : consentement, contrat, obligation légale, intérêt légitime.
rgpd-13|eurlex-rss|document|loi|A|droit|3100|RGPD art. 13|Article 13 — Informations à fournir|Informations à communiquer lors de la collecte : identité du responsable, finalités, durée de conservation, droits.
aiact-50|eurlex-rss|document|loi|A|droit|820|AI Act art. 50|Article 50 — Obligations de transparence|Les personnes doivent être informées qu'elles interagissent avec un système d'IA ; marquage des contenus générés.
aiact-4|eurlex-rss|document|loi|A|droit|820|AI Act art. 4|Article 4 — Maîtrise de l'IA|Les fournisseurs et déployeurs prennent des mesures pour garantir un niveau suffisant de maîtrise de l'IA de leur personnel.
aiact-5|eurlex-rss|document|loi|A|droit|820|AI Act art. 5|Article 5 — Pratiques interdites|Interdiction des techniques subliminales, de la notation sociale et de certaines identifications biométriques.
wcag-1|w3c-tr|document|norme|A|normes_documentation|1000|WCAG 2.2 SC 1.4.3|Contrast (Minimum)|Text has a contrast ratio of at least 4.5:1, large text 3:1.
wcag-2|w3c-tr|document|norme|A|normes_documentation|1000|WCAG 2.2 SC 3.3.2|Labels or Instructions|Labels or instructions are provided when content requires user input in forms.
wcag-3|w3c-tr|document|norme|A|normes_documentation|1000|WCAG 2.2 SC 2.4.7|Focus Visible|Any keyboard operable interface has a mode where the keyboard focus indicator is visible.
wcag-4|w3c-tr|document|norme|A|normes_documentation|1000|WCAG 2.2 SC 3.3.8|Accessible Authentication (Minimum)|A cognitive function test is not required for any step in an authentication process.
rgaa-1|rgaa|document|norme|A|normes_documentation|900|RGAA 4.1 critère 11.1|Chaque champ de formulaire a-t-il une étiquette ?|Les champs de formulaire doivent avoir une étiquette accessible reliée au champ.
rgaa-2|rgaa|document|norme|A|normes_documentation|900|RGAA 4.1 critère 11.10|Le contrôle de saisie est-il utilisé de manière pertinente ?|Indications de format et messages d'erreur explicites dans les formulaires.
rgaa-3|rgaa|document|norme|A|normes_documentation|900|RGAA 4.1 critère 3.2|Contraste des couleurs|Le contraste entre la couleur du texte et celle de son arrière-plan est-il suffisamment élevé ?
rgaa-4|rgaa|document|norme|A|normes_documentation|900|RGAA 4.1 critère 10.7|Visibilité de la prise de focus|Pour chaque élément recevant le focus, la prise de focus est-elle visible ?
rgaa-5|rgaa|document|norme|A|normes_documentation|900|RGAA 4.1 critère 1.1|Images porteuses d'information|Chaque image porteuse d'information a-t-elle une alternative textuelle ?
rgesn-1|rgesn|document|norme|A|normes_documentation|900|RGESN 2024 critère 4.1|Limiter le poids des pages|Le service numérique limite le poids des pages et le nombre de requêtes pour réduire son impact environnemental.
rgesn-2|rgesn|document|norme|A|normes_documentation|900|RGESN 2024 critère 6.1|Hébergement et sobriété|Choisir un hébergeur engagé dans la réduction de son empreinte et dimensionner les serveurs au juste besoin.
rgesn-3|rgesn|document|norme|A|normes_documentation|900|RGESN 2024 critère 1.1|Stratégie d'écoconception|Le service a-t-il été évalué favorablement en matière d'utilité sociale et environnementale ?
rgesn-4|rgesn|document|norme|A|normes_documentation|900|RGESN 2024 critère 5.3|Images et vidéos sobres|Compresser les images, éviter la lecture automatique des vidéos.
rfc9110-1|rfc-documents|document|norme|A|normes_documentation|1600|RFC 9110 §15.5.4|403 Forbidden|The server understood the request but refuses to fulfill it.
rfc9110-2|rfc-documents|document|norme|A|normes_documentation|1600|RFC 9110 §8.8.3|ETag|The ETag field provides the current entity tag for the selected representation, used for conditional requests.
rfc9110-3|rfc-documents|document|norme|A|normes_documentation|1600|RFC 9110 §13.1.3|If-Modified-Since|Conditional request header: the server responds 304 Not Modified when the representation has not changed.
rfc6749-1|rfc-documents|document|norme|A|normes_documentation|5000|RFC 6749 §4.1|Authorization Code Grant|OAuth 2.0 authorization code flow with redirection and access token request.
rfc9116-1|rfc-documents|document|norme|A|normes_documentation|1700|RFC 9116 §2|The security.txt file|A file at /.well-known/security.txt describes how to report security vulnerabilities.
sqlite-1|sqlite-docs|document|documentation|A|normes_documentation|300|SQLite FTS5 §4.3|BM25 ranking function|The bm25() auxiliary function returns a relevance score for full-text queries; column weights are optional arguments.
sqlite-2|sqlite-docs|document|documentation|A|normes_documentation|300|SQLite FTS5 §4.6|Unicode61 tokenizer|The unicode61 tokenizer with remove_diacritics folds accents for full-text indexing.
sqlite-3|sqlite-docs|document|documentation|A|normes_documentation|300|SQLite URI §3.3|Read-only and immutable databases|The mode=ro and immutable=1 URI parameters open a database read-only without locking.
fastapi-1|fastapi-docs|document|documentation|A|normes_documentation|250|FastAPI Security — OAuth2 with Password|OAuth2 with Password (and hashing), Bearer with JWT tokens|Use OAuth2PasswordBearer, hash passwords with a secure algorithm and return JWT access tokens.
fastapi-2|fastapi-docs|document|documentation|A|normes_documentation|250|FastAPI CORS|CORS (Cross-Origin Resource Sharing)|Configure CORSMiddleware with explicit allowed origins.
caddy-1|caddy-docs|document|documentation|A|normes_documentation|200|Caddy reverse_proxy — headers|reverse_proxy header manipulation|Set or remove request and response headers when proxying to upstream services.
caddy-2|caddy-docs|document|documentation|A|normes_documentation|200|Caddy automatic HTTPS|Automatic HTTPS|Caddy obtains and renews TLS certificates automatically from Let's Encrypt or ZeroSSL.
docker-1|docker-docs|document|documentation|A|normes_documentation|150|Compose services — deploy.resources|Resource limits in Compose|Limit CPU and memory of a service with deploy.resources.limits.
docker-2|docker-docs|document|documentation|A|normes_documentation|150|Docker volumes read-only|Read-only bind mounts|Mount a volume with :ro so the container cannot write to it.
ollama-1|ollama-docs|document|documentation|A|normes_documentation|120|Ollama API — /api/generate|Generate a completion|POST /api/generate with model, prompt and options; streaming responses.
ollama-2|ollama-docs|document|documentation|A|normes_documentation|120|Ollama API — keep_alive|Model keep_alive and memory|keep_alive controls how long a model stays loaded in memory.
ccag-1|ccag-tic|document|cahier_des_charges|A|marches_publics|2000|CCAG-TIC art. 30|CCAG-TIC — Vérifications et admission|Opérations de vérification, de recette et d'admission des prestations informatiques.
ccag-2|ccag-tic|document|cahier_des_charges|A|marches_publics|2000|CCAG-TIC art. 38|CCAG-TIC — Droits de propriété intellectuelle|Options de cession ou de concession des droits sur les résultats et logiciels.
dae-1|dae-guides|document|cahier_des_charges|A|marches_publics|700|DAE Guide prestations intellectuelles|Modèle de CCTP pour prestations de développement web|Structure type d'un cahier des clauses techniques particulières : contexte, besoins, exigences, livrables, recette.
dae-2|guide-achats-numeriques-responsables|document|cahier_des_charges|A|marches_publics|1200|Guide achats numériques responsables §3|Intégrer l'écoconception dans le cahier des charges|Clauses environnementales types : sobriété, poids des pages, hébergement responsable.
dae-3|daj-guides-commande-publique|document|guide|A|marches_publics|900|DAJ Guide petits marchés|Guide de l'achat public pour les marchés de faible montant|Seuils, publicité adaptée, mise en concurrence et cahier des charges simplifié.
dae-4|ugap-modeles|document|cahier_des_charges|A|marches_publics|500|Modèle cahier des charges site internet (collectivité)|Cahier des charges pour la refonte d'un site vitrine|Arborescence, charte graphique, accessibilité RGAA, hébergement, maintenance et formation.
boamp-1|boamp-api|flux|appel_offres|A|marches_publics|3|BOAMP 26-123456|Refonte du site internet de la commune|Objet : création d'un site vitrine accessible ; acheteur : commune ; date limite dans 20 jours.
boamp-2|boamp-api|flux|appel_offres|A|marches_publics|5|BOAMP 26-123789|Développement d'une application de gestion avec intelligence artificielle|Marché de prestations intellectuelles ; acheteur : syndicat mixte.
boamp-3|boamp-api|flux|appel_offres|A|marches_publics|40|BOAMP 26-098765|Maintenance du parc informatique|Fourniture et maintenance de postes ; date limite dépassée.
ted-1|ted-api|flux|appel_offres|A|marches_publics|4|TED 2026/S 210-123456|Website development services — France|Contract notice for web development and hosting of an institutional website.
datagouv-1|datagouv-api|flux|donnees|A|marches_publics|60||Jeu de données : modèles de cahiers des charges numériques|Recueil de cahiers des charges types publiés par des collectivités.
decp-1|decp-consolidees|flux|donnees|A|marches_publics|2||Données essentielles de la commande publique — mise à jour|Montants et attributaires des marchés publics conclus.
anj-1|anj-actualites|flux|actualite|A|droit|30||Publicité des opérateurs de jeux : l'ANJ publie ses lignes directrices|Encadrement des communications commerciales des opérateurs de jeux d'argent, protection des mineurs et des joueurs excessifs.
anj-2|anj-actualites|flux|actualite|A|droit|200||Stratégie promotionnelle des opérateurs de jeux en ligne|L'ANJ examine les plans promotionnels annuels, y compris pour le poker en ligne.
anj-3|anj-actualites|flux|actualite|A|droit|10||Rapport de l'ANJ sur le marché des jeux en ligne|Chiffres trimestriels : paris sportifs, poker et paris hippiques.
csi-1|legifrance-api|document|loi|A|droit|1800|Code de la sécurité intérieure art. L320-12|Publicité en faveur des jeux d'argent|Les communications commerciales des opérateurs de jeux sont interdites dans les publications destinées aux mineurs et doivent comporter un message de mise en garde.
lcen-1|legifrance-api|document|loi|A|droit|4000|LCEN art. 6 III|Mentions légales d'un site internet|Les éditeurs de services en ligne mettent à disposition leur identité, coordonnées et hébergeur.
cnil-n1|cnil-actualites|flux|actualite|A|droit|12||La CNIL publie des recommandations sur les cookies et traceurs|Rappel : consentement préalable pour les traceurs publicitaires, refus aussi simple que l'acceptation.
cnil-n2|cnil-actualites|flux|actualite|A|droit|25||Sanction pour défaut de sécurité des mots de passe|La CNIL sanctionne une société qui stockait des mots de passe en clair.
cnil-n3|cnil-actualites|flux|actualite|A|droit|6||Intelligence artificielle : la CNIL publie de nouvelles fiches pratiques|Fiches sur l'intérêt légitime et la collecte par moissonnage pour le développement de systèmes d'IA.
edpb-1|edpb-news|flux|actualite|A|droit|20||EDPB adopts guidelines on processors|Guidelines clarifying the obligations of processors and sub-processors under Article 28 GDPR.
ce-1|ce-jurisprudence|flux|jurisprudence|A|droit|90||Conseil d'État : contrat de sous-traitance et responsabilité|Analyse d'une décision sur la répartition des responsabilités entre responsable et sous-traitant.
arpp-1|arpp|flux|guide|B|marketing_communication|300||Recommandation ARPP Communication publicitaire numérique|Identification de la publicité, influenceurs, transparence des collaborations commerciales.
dgccrf-1|dgccrf-rss|flux|actualite|A|droit|15||Influenceurs : la DGCCRF contrôle les pratiques commerciales|Contrôles des placements de produits non signalés, y compris pour les jeux d'argent.
cert-1|certfr-avis|flux|actualite|A|cybersecurite|1||Multiples vulnérabilités dans Caddy|Une vulnérabilité permet un contournement de la politique de sécurité ; appliquer le correctif.
cert-2|certfr-alertes|flux|actualite|A|cybersecurite|3||Vulnérabilité critique dans n8n|Exécution de code à distance dans n8n ; mise à jour urgente recommandée.
cert-3|certfr-avis|flux|actualite|A|cybersecurite|2||Multiples vulnérabilités dans Docker Engine|Élévation de privilèges et contournement d'isolation ; correctifs disponibles.
cert-4|certfr-avis|flux|actualite|A|cybersecurite|200||Vulnérabilité dans Caddy (ancienne)|Ancien avis corrigé depuis longtemps.
cert-5|certfr-actualites|flux|actualite|A|cybersecurite|8||Bulletin d'actualité : campagne d'hameçonnage ciblant les mots de passe|Des campagnes volent des mots de passe ; activer l'authentification multifacteur.
cisa-1|cisa-kev|flux|donnees|A|cybersecurite|1||CVE-2026-1111 — Ollama path traversal (Ollama)|Vulnérabilité exploitée activement ; appliquer le correctif.
gh-1|gh-caddy|flux|release|A|tech|2||Caddy v2.11.8|Correctif de sécurité pour reverse_proxy.
gh-2|gh-n8n|flux|release|A|tech|3||n8n 2.4.1|Security fix for code node sandbox.
gh-3|gh-ollama|flux|release|A|tech|5||Ollama v0.13.2|Fixes path handling issue and improves memory usage.
pypi-1|pypi-fastapi|flux|release|A|tech|9||fastapi 0.163.0|New release of FastAPI.
bleep-1|bleepingcomputer|media|actualite|C|cybersecurite|1||Massive password leak exposes 16 billion credentials|Researchers found a huge dataset of stolen passwords; change your passwords.
bleep-2|bleepingcomputer|media|actualite|C|cybersecurite|4||Hackers exploit n8n flaw to breach automation servers|Attackers actively exploit the n8n remote code execution vulnerability.
krebs-1|krebs|media|actualite|C|cybersecurite|7||Password managers and the new phishing wave|Opinion on why password managers matter after recent phishing campaigns.
sans-1|sans-isc|flux|actualite|B|cybersecurite|3||Scanning for exposed Ollama instances|Honeypots observe scans for unauthenticated Ollama APIs on port 11434.
hn-1|hn-api|flux|discussion|C|forums_experts|2||Show HN: password strength meter in 2kB|A tiny JavaScript library to estimate password strength.
hn-2|hn-api|flux|discussion|C|forums_experts|6||Ask HN: How do you rank results with SQLite FTS5?|Discussion about bm25 tuning and column weights in SQLite full-text search.
so-1|stackexchange-api-python|flux|discussion|C|forums_experts|30||How to make SQLite FTS5 ignore accents?|Use the unicode61 tokenizer with remove_diacritics 2.
so-2|stackexchange-api-security|flux|discussion|C|forums_experts|60||Is bcrypt still OK for password hashing in 2026?|Answers recommend Argon2id but bcrypt remains acceptable with a proper cost.
so-3|stackexchange-api-ux|flux|discussion|C|forums_experts|80||Should form labels be placeholders?|Placeholders are not a substitute for labels; accessibility concerns.
lobsters-1|lobsters|flux|discussion|C|forums_experts|5||Caddy as a reverse proxy for self-hosted AI|Experience report on Caddy in front of Ollama with authentication.
nng-1|nngroup|flux|guide|B|design_ux|300||Form design: placeholders in form fields are harmful|Usability research on labels versus placeholders in forms.
smash-1|smashing|media|actualite|C|design_ux|20||Designing accessible login forms|Practical patterns for accessible authentication forms and error messages.
webaim-1|webaim-blog|flux|guide|B|design_ux|150||Contrast and color accessibility|Understanding WCAG contrast requirements with examples.
dsfr-1|gh-dsfr|flux|release|A|design_ux|10||DSFR 1.15 — composants formulaires|Nouvelle version du système de design de l'État : composants de formulaire accessibles.
eea-1|eea-publications|flux|actualite|A|environnement|40||Digital technologies and the environment|EEA briefing on the energy footprint of data centres and digital services.
arcep-1|arcep-press-en|flux|actualite|A|environnement|25||Arcep publishes its study on the environmental footprint of digital services|Network and terminal impacts; recommendations for sobriety.
shift-1|shift-project|flux|guide|B|environnement|500||Rapport : pour une sobriété numérique|Recommandations sur la sobriété des usages et l'écoconception.
greenit-1|greenit-fr|flux|actualite|B|environnement|12||Écoconception web : les bonnes pratiques 2026|Réduire le poids des pages et le nombre de requêtes.
insee-1|insee-rss|flux|donnees|A|entreprise|10||Créations d'entreprises en octobre 2026|Les créations de micro-entreprises progressent.
sp-1|service-public-pro|flux|guide|A|entreprise|20||Micro-entrepreneur : plafonds de chiffre d'affaires 2026|Seuils de chiffre d'affaires et franchise de TVA pour les micro-entreprises.
sp-2|service-public-pro|flux|guide|A|entreprise|200||Choisir le statut de sa société : SASU ou EURL|Comparatif des statuts juridiques pour un entrepreneur seul.
urssaf-1|urssaf|flux|guide|A|entreprise|90||Cotisations des micro-entrepreneurs : taux 2026|Taux de cotisations sociales pour les activités de prestations de services.
bofip-1|bofip-actualites|flux|loi|A|entreprise|60||Franchise en base de TVA : commentaires BOFiP|Seuils et conditions d'application de la franchise en base.
bpi-1|bpifrance-big-media|media|actualite|C|entreprise|15||Créer son entreprise dans l'IA : les aides|Panorama des aides à l'innovation pour les startups IA.
stripe-1|stripe-blog|flux|actualite|B|entreprise|30||Stripe launches new invoicing features|Recurring invoices and payment links for freelancers.
hubspot-1|hubspot-sales|flux|guide|B|entreprise|100||How to write a winning sales proposal|Structure of a commercial proposal: context, solution, pricing, timeline.
gsc-1|google-search-central|flux|guide|A|marketing_communication|30||Google Search Central: helpful content guidance|Creating helpful, reliable, people-first content for search.
gsc-2|google-search-docs|flux|documentation|A|marketing_communication|10||Search documentation update: structured data for videos|Video structured data requirements updated.
sej-1|search-engine-journal|media|actualite|C|marketing_communication|2||Google core update rolling out|Volatility in rankings during the November core update.
yt-1|youtube-data-api|social|social|D|medias|3||Vidéo : stratégie GTO au poker pour débutants|Vidéo récente sur la stratégie GTO, nombreux commentaires positifs.
gtow-1|gtowizard-blog|flux|actualite|B|poker|20||Range construction on the river|Theory article on polarized river ranges and bluff frequencies.
gtow-2|gtowizard-blog|flux|actualite|B|poker|200||ICM and final table strategy|How ICM pressure changes calling ranges.
upswing-1|upswing-blog|flux|actualite|B|poker|40||Preflop ranges for 6-max cash games|Opening ranges by position.
pnews-1|pokernews|media|actualite|C|poker|1||WSOP Paradise: day 2 results|Tournament report from the WSOP Paradise event.
pnews-2|pokernews|media|actualite|C|poker|6||Online poker traffic rises in Europe|Shared liquidity drives growth in France, Spain and Italy.
arxiv-gt-1|arxiv-cs-gt|flux|recherche|B|ia|30||Counterfactual regret minimization for large imperfect-information games|New CFR variant reduces computation for poker-like games.
arxiv-ai-1|arxiv-cs-ai|flux|recherche|B|ia|5||Evaluating LLM agents on multi-step tasks|Benchmark of autonomous agents with tool use.
arxiv-ai-2|arxiv-cs-cl|flux|recherche|B|ia|8||Retrieval-augmented generation with calibrated rankers|Learning-to-rank improves RAG answer quality.
hf-1|huggingface-blog|flux|actualite|A|ia|10||Open-weight models for local inference|Running small open models locally with quantization.
deepmind-1|deepmind-blog|flux|actualite|A|ia|1||New research on AI agents|DeepMind presents results on agent planning.
actuabd-1|actuabd|media|actualite|C|bd_edition|2||Angoulême 2027 : la sélection officielle dévoilée|Les albums sélectionnés pour le festival.
actuabd-2|actuabd|media|actualite|C|bd_edition|9||Le marché de la BD recule en 2026|Ventes de bandes dessinées en baisse, le manga résiste.
cnl-1|cnl|flux|guide|A|bd_edition|120||Aides du CNL aux auteurs de bande dessinée|Bourses de création et conditions d'éligibilité pour les auteurs.
sne-1|sne|flux|guide|B|bd_edition|300||Contrat d'édition : les clauses essentielles|Cession des droits, rémunération proportionnelle, reddition des comptes.
bnf-1|bnf-actualites|flux|guide|A|bd_edition|900||Dépôt légal des livres et ISBN|Obligation de dépôt légal et attribution d'un ISBN par l'AFNIL.
lemonde-1|lemonde-pixels|media|actualite|C|medias|1||L'IA générative divise les créateurs de contenus|Enquête sur l'usage de l'IA par les créateurs, entre enthousiasme et inquiétude.
lemonde-2|lemonde-economie|media|actualite|C|medias|3||Les jeux d'argent en ligne battent des records|Hausse des mises en ligne, inquiétudes sur l'addiction.
fi-1|francetvinfo|media|actualite|C|medias|2||Poker en ligne : les jeunes joueurs de plus en plus nombreux|Reportage sur l'engouement pour le poker chez les 18-25 ans.
rf-1|radiofrance-culture|media|podcast|C|medias|5||Podcast : la bande dessinée face au manga|Débat sur l'évolution du marché de la BD.
rf-2|radiofrance-ecologie|media|actualite|C|medias|10||Numérique : quelle empreinte carbone ?|Émission sur la sobriété numérique.
gdelt-1|gdelt-doc|media|actualite|C|medias|1||Cybersécurité : vague d'attaques contre les PME|Article repéré par GDELT dans la presse régionale.
gdelt-2|gdelt-doc|media|actualite|C|medias|1||Intelligence artificielle : nouvelles règles européennes pour les chatbots|Article repéré par GDELT sur l'AI Act.
igb-1|igaming-business|media|actualite|C|medias|4||French regulator tightens gambling advertising rules|ANJ guidelines on advertising by betting and poker operators.
masto-1|mastodon-hashtags|social|social|D|reseaux_sociaux|1||Post public #poker|Super tournoi hier soir, très content de ma stratégie GTO, merci aux coachs !
masto-2|mastodon-hashtags|social|social|D|reseaux_sociaux|1||Post public #poker|Encore une arnaque sur un site de poker en ligne, très déçu, attention.
masto-3|mastodon-hashtags|social|social|D|reseaux_sociaux|2||Post public #poker|Nouveau solver de poker gratuit, génial pour progresser.
masto-4|mastodon-hashtags-ia|social|social|D|reseaux_sociaux|1||Post public #IA|L'IA générative pour écrire une BD ? Inquiétant pour les auteurs.
masto-5|mastodon-hashtags-ia|social|social|D|reseaux_sociaux|2||Post public #IA|Les agents IA open source progressent vite, excellent pour les indépendants.
masto-6|mastodon-hashtags-ia|social|social|D|reseaux_sociaux|3||Post public #IA|Panne d'un assistant IA ce matin, problème de fiabilité.
bsky-1|bluesky-public-api|social|social|D|reseaux_sociaux|2||Post public — compte institutionnel|Annonce : nouvelles fonctionnalités de modération des fils.
bsky-2|bluesky-public-api|social|social|D|reseaux_sociaux|4||Post public #BD|La sélection d'Angoulême fait débat, beaucoup d'avis positifs sur les nouveaux auteurs.
yt-2|youtube-data-api|social|social|D|reseaux_sociaux|2||Vidéo : comment créer une chaîne YouTube poker|Conseils pour lancer une chaîne éducative sur le poker.
yt-3|youtube-data-api|social|social|D|reseaux_sociaux|5||Vidéo : boxe éducative, entraînement pour débutants|Tendance des vidéos de boxe loisir.
web-1|web-searxng|web|actualite|D|tech|1||Comparatif des hébergeurs VPS 2026|Article de blog comparant des offres VPS.
web-2|web-wikipedia|web|guide|C|tech|500||Argon2 — Wikipédia|Fonction de dérivation de clé, lauréate du Password Hashing Competition.
leurre-1|bleepingcomputer|media|actualite|C|cybersecurite|0||Password spraying attack hits universities|Attackers try common passwords against student accounts.
leurre-2|lemondeinformatique|media|actualite|C|tech|1||Le marché des gestionnaires de mots de passe en hausse|Étude de marché des gestionnaires de mots de passe.
leurre-3|pokernews|media|actualite|C|poker|0||Poker players react to new advertising campaign|Players comment on a controversial poker ad campaign.
leurre-4|techcrunch-startups|media|actualite|C|entreprise|1||Startup raises funds for AI website builder|A startup that builds websites with AI raises a seed round.
leurre-5|the-decoder|media|actualite|C|ia|0||New AI model tops leaderboards|Another model claims state-of-the-art results.
leurre-6|zdnet-fr|media|actualite|C|tech|1||Accessibilité : un grand site condamné|Un site de e-commerce condamné pour défaut d'accessibilité.
leurre-7|bleepingcomputer|media|actualite|C|cybersecurite|2||Data breach notification delays criticized|Companies criticized for late breach notifications.
leurre-8|maddyness|media|actualite|C|entreprise|3||Freelances : la fin de la micro-entreprise ?|Tribune sur l'évolution des statuts d'indépendants.
leurre-9|numerama|media|actualite|C|tech|1||Docker Desktop change sa licence|Nouvelle politique tarifaire pour les entreprises.
leurre-10|01net|media|actualite|C|tech|0||Les cahiers des charges des sites e-commerce se compliquent|Article d'opinion sur les exigences des clients.
"""

COLONNES = ["id", "source_id", "canal", "type_doc", "confiance", "domaine", "age", "ref", "titre", "resume"]
AUTORITE = {"A": 1.0, "B": 0.7, "C": 0.4, "D": 0.1}


def items() -> list[dict]:
    out = []
    for l in LIGNES.strip().splitlines():
        v = [x.strip() for x in l.split("|")]
        assert len(v) == len(COLONNES), l
        d = dict(zip(COLONNES, v))
        d["age"] = int(d["age"])
        d["autorite"] = AUTORITE[d["confiance"]] if d["canal"] != "media" else 0.5
        out.append(d)
    return out
