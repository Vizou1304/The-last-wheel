# Installer The Last Wheel sur le Raspberry Pi — pas à pas

> **Adapte les noms :** dans ce guide, `pi` est ton nom d'utilisateur et `thelastwheel` le nom de ton Pi sur le réseau.
> et `/home/pi/the-last-wheel`). Dans le fichier de service, `User=` et `WorkingDirectory=` doivent aussi porter ton nom.

Ce guide part de zéro : une carte SD vide, un Raspberry Pi, ton PC Windows. Compte 45 minutes la première fois.
Les écrans des logiciels peuvent changer légèrement d'une version à l'autre ; l'idée reste la même.

Rien ne devient public avant l'étape 9 (le tunnel), et seulement quand tu le décides.

## Ce qu'il te faut

- Un **Raspberry Pi 4** (ou 5), 2 Go de mémoire ou plus.
- Une **carte microSD de 16 Go minimum** (32 Go de préférence, d'une marque connue) et un lecteur de carte pour ton PC.
- L'**alimentation officielle** du Pi (une mauvaise alimentation cause des plantages bizarres).
- Un **câble réseau** (Ethernet) du Pi vers ta box : plus fiable que le Wi-Fi pour un serveur qui tourne 24 h/24.
- Ton PC Windows 10 ou 11.

## Étape 1 — Préparer la carte SD (sur ton PC)

⚠ Cette étape **efface tout** ce qui est sur la carte. Vérifie bien que tu choisis la carte, pas un autre disque.

1. Télécharge **Raspberry Pi Imager** sur raspberrypi.com/software et installe-le.
2. Branche la carte SD dans ton PC, lance Raspberry Pi Imager.
3. **Device** : choisis ton modèle (Raspberry Pi 4 ou 5).
4. **Operating System** : *Raspberry Pi OS (other)* puis **Raspberry Pi OS Lite (64-bit)**. « Lite » veut dire sans bureau
   graphique : c'est ce qu'on veut pour un serveur.
5. **Storage** : choisis ta carte SD (regarde la taille pour ne pas te tromper).
6. Quand il propose de **personnaliser** (réglages / « Edit settings »), remplis :
   - **Nom de l'appareil (hostname)** : `thelastwheel`
   - **Nom d'utilisateur** : `pi` (les commandes de ce guide l'utilisent)
   - **Mot de passe** : un vrai mot de passe, long. Note-le. C'est la seule protection du Pi.
   - **Wi-Fi** : seulement si tu n'utilises pas de câble.
   - **Fuseau horaire** : `Europe/Paris`, **clavier** : `fr`
   - **Services** : active **SSH** avec l'authentification par mot de passe.
7. Lance l'écriture et attends le message de fin. Retire la carte.

## Étape 2 — Premier démarrage

1. Mets la carte dans le Pi, branche le câble réseau, puis l'alimentation en dernier.
2. Attends 2 à 3 minutes (la première fois, il s'installe tout seul).
3. Sur ton PC, ouvre **PowerShell** (touche Windows, tape `powershell`, Entrée) et tape :

```
ssh pi@thelastwheel.local
```

- À la question « Are you sure you want to continue connecting », tape `yes`.
- Tape ton mot de passe (rien ne s'affiche pendant la saisie, c'est normal), puis Entrée.
- Tu es connecté quand tu vois `pi@thelastwheel:~ $`.

Si `thelastwheel.local` n'est pas trouvé : cherche l'adresse du Pi dans l'interface de ta box (liste des appareils,
nom `thelastwheel`), puis `ssh pi@<cette adresse>`.

**Toutes les commandes des étapes 3, 5, 6, 7, 8 se tapent dans cette fenêtre, sur le Pi.**

## Étape 3 — Mettre le Pi à jour

```
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Le Pi redémarre et la connexion se coupe. Attends 1 minute, reconnecte-toi avec `ssh pi@thelastwheel.local`.
Vérifie l'heure : `date` doit donner l'heure de Paris. Sinon : `sudo timedatectl set-timezone Europe/Paris`.

## Étape 4 — Copier le jeu sur le Pi (depuis ton PC)

Ouvre une **deuxième** fenêtre PowerShell (pas celle du Pi) :

```
cd C:\the-last-wheel
ssh pi@thelastwheel.local "mkdir -p /home/pi/the-last-wheel"
scp -r server content web tools README.md pi@thelastwheel.local:/home/pi/the-last-wheel/
```

On ne copie **pas** `data` : la vraie ville naîtra sur le Pi et vivra là-bas. Ne lance jamais la vraie ville
(`python server/main.py` sans `--sim`) sur deux machines à la fois : elles auraient deux mémoires différentes.

## Étape 5 — Premier essai à la main (sur le Pi)

```
cd /home/pi/the-last-wheel
python3 tools/check_balance.py
python3 server/main.py
```

`check_balance.py` doit finir par « OK — toutes les vérifications passent ». Puis le jeu démarre et affiche une ligne
de statut. Sur ton PC, ouvre `http://thelastwheel.local:8080` : tu dois voir la ville. Regarde la fin de la ligne de
statut dans la fenêtre du Pi, du type `api=online/ACTIVE` quand le hamster court et `api=online/IDLE` quand il dort.
Arrête avec **Ctrl+C**.

## Étape 6 — Le faire tourner tout seul, 24 h/24 (sur le Pi)

Crée le fichier de service :

```
sudo nano /etc/systemd/system/the-last-wheel.service
```

Colle ce texte (clic droit dans PowerShell colle), puis **Ctrl+O**, **Entrée**, **Ctrl+X** pour enregistrer et quitter :

```ini
[Unit]
Description=The Last Wheel
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/the-last-wheel
ExecStart=/usr/bin/python3 server/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Puis :

```
sudo systemctl enable --now the-last-wheel
systemctl status the-last-wheel
journalctl -u the-last-wheel -f
```

`status` doit afficher **active (running)** en vert. `journalctl -f` montre la chronique en direct (Ctrl+C pour sortir).
Le jeu redémarre seul si le Pi redémarre ou si le programme plante.

## Étape 7 — Vérifier que tout est bon

- La page s'ouvre sur `http://thelastwheel.local:8080` depuis ton PC et ton téléphone (même Wi-Fi).
- Dans le journal (bouton « Colony log »), la section « On Ethereum · Sepolia testnet » se remplit au bout d'une minute.
- Le hamster est affiché « running » quand la roue tourne vraiment.
- Après un redémarrage (`sudo reboot`), la ville reprend toute seule, avec la même histoire.

## Étape 8 — Sauvegarder la mémoire de la ville

Les cartes SD finissent par mourir. Une fois par semaine, depuis PowerShell sur ton PC :

```
scp -r pi@thelastwheel.local:/home/pi/the-last-wheel/data C:\sauvegarde-the-last-wheel
```

Le dossier `data` contient l'histoire de la vraie ville. S'il est perdu, la ville repart de zéro.

## Étape 8 bis — Sécuriser le Pi (avant de publier)

Le jeu lui-même est en lecture seule : les visiteurs ne peuvent rien modifier, aucun fichier hors du dossier `web/`
n'est accessible, et il n'y a ni mot de passe ni clé secrète dans le programme. Le risque vient surtout du Pi lui-même,
qui est sur ton réseau de maison. Ces cinq réglages le réduisent beaucoup.

**1. Pare-feu : seul ton réseau de maison peut parler au Pi.** Ton PC joint souvent le Pi en **IPv6** (c'est le cas si
`ping thelastwheel.local` répond avec une adresse qui commence par `2a01:`), donc les règles doivent couvrir l'IPv4 **et** l'IPv6,
sinon le pare-feu te coupe l'accès à toi-même.

*a)* Regarde les adresses du Pi : `hostname -I`. Tu y vois une adresse IPv4 (`192.168.x.x`) et une IPv6
(`2a01:...:...:...:...`). L'IPv6 de ton réseau est ses **4 premiers blocs** (par exemple `2a01:cb1c:1259:2700`).

*b)* Tape ces lignes **dans cet ordre**, en remplaçant `2a01:cb1c:1259:2700` par les 4 premiers blocs de TON adresse :

```
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.0.0/16 to any port 22 proto tcp
sudo ufw allow from 192.168.0.0/16 to any port 8080 proto tcp
sudo ufw allow from fe80::/10 to any port 22 proto tcp
sudo ufw allow from fe80::/10 to any port 8080 proto tcp
sudo ufw allow from 2a01:cb1c:1259:2700::/64 to any port 22 proto tcp
sudo ufw allow from 2a01:cb1c:1259:2700::/64 to any port 8080 proto tcp
```

*c)* **Filet de sécurité** : ce réglage désactive le pare-feu tout seul dans 5 minutes, au cas où tu te serais coupé l'accès :

```
sudo systemd-run --on-active=5m --unit=ufw-filet /usr/sbin/ufw disable
sudo ufw enable
```

*d)* **Sans fermer la fenêtre actuelle**, ouvre une **deuxième** fenêtre PowerShell et connecte-toi (`ssh pi@thelastwheel.local`),
puis ouvre la page `http://thelastwheel.local:8080`. Si les deux marchent, annule le filet dans la première fenêtre :

```
sudo systemctl stop ufw-filet.timer
sudo ufw status
```

Si ça ne marche pas, attends simplement 5 minutes : le pare-feu se coupe seul et tu reprends la main.

*Si ton adresse IPv6 change un jour* (ça peut arriver avec certains opérateurs), la connexion par `thelastwheel.local` peut
être refusée : connecte-toi alors avec l'adresse IPv4 du Pi (`ssh pi@192.168.x.x`), qui marche toujours.

**2. Mises à jour de sécurité automatiques :**

```
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

Réponds « Yes ».

**3. Durcir le service.** Crée d'abord le dossier de la mémoire, puis ajoute ces quatre lignes dans la partie `[Service]` du
fichier `/etc/systemd/system/the-last-wheel.service` (`sudo nano ...`) :

```
mkdir -p /home/pi/the-last-wheel/data
```

```ini
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/home/pi/the-last-wheel/data
```

Elles interdisent au programme d'écrire ailleurs que dans `data` et de prendre plus de droits. Puis
`sudo systemctl daemon-reload && sudo systemctl restart the-last-wheel && systemctl status the-last-wheel`.
Si le statut n'est plus « active (running) », retire ces quatre lignes et dis-moi ce qu'affiche
`journalctl -u the-last-wheel -n 30`.

**4. Une fois le tunnel installé (étape 9), ne laisse le jeu écouter qu'en interne** : ajoute dans `[Service]` la ligne
`Environment=TLW_HOST=127.0.0.1`. Le tunnel parle au jeu depuis le Pi lui-même, donc plus personne d'autre n'y accède.
(Garde 0.0.0.0, le réglage par défaut, tant que tu testes depuis ton PC ou ton téléphone.)

**5. Hors du Pi :**
- **N'ouvre aucun port sur ta box** (pas de « redirection de ports », pas d'UPnP). Le tunnel Cloudflare se connecte de
  l'intérieur vers l'extérieur : rien n'entre chez toi.
- Active la **double authentification** sur ton compte Cloudflare : s'il était piraté, quelqu'un pourrait rediriger ton
  adresse.
- Mot de passe du Pi long et unique. Plus tard, une clé SSH à la place du mot de passe est encore mieux : dis-le-moi et
  je te guide.

## Étape 9 — Publier (seulement quand tu le décides)

Ne fais cette étape qu'après avoir validé le jeu sur le Pi pendant au moins une journée.

Le lien rapide `trycloudflare` est **réservé aux tests** (200 requêtes simultanées au maximum, aucune garantie, adresse
qui change). Pour un post ouvert à tous : un nom de domaine, un tunnel Cloudflare nommé et les règles de cache décrites
dans `README.md` (section « Partager la page avec tout le monde »). Dis-moi où tu en es, on le fait ensemble.

## Si ça ne marche pas

| Problème | Que faire |
|---|---|
| `ssh` : « Could not resolve hostname » | utilise l'adresse de la box à la place de `thelastwheel.local` |
| `ssh` : « Connection refused » | SSH n'a pas été activé à l'étape 1 : refais l'étape 1 avec SSH coché |
| La page ne s'ouvre pas | `systemctl status the-last-wheel` ; vérifie que le PC est sur le même réseau que le Pi |
| `status` affiche « failed » | `journalctl -u the-last-wheel -n 50` et envoie-moi les dernières lignes |
| Le Pi redémarre tout seul, plante | change d'alimentation (la cause la plus fréquente) |
| Mot de passe oublié | refais l'étape 1 (la carte est effacée, pense à sauvegarder `data` avant) |
