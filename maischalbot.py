#!/usr/bin/env python3

'''
 Dependencies:
 - python3
 - mechanicalsoup (pip3 install mechanicalsoup)
 - imagemagick & webp
'''

import configparser, json, requests, urllib, os
import mechanicalsoup, pprint
from time import gmtime, strftime, sleep

CONFIGFILE = "./config.ini"
URL = "https://api.telegram.org/bot"
SAVED_POSTS_FILE = "./saved_posts.json"

'''
 Questions
 - Est-ce que je ferais pas mieux de mettre les options de config dans ce
 fichier directement? Plutôt que de ce faire chier avec un .ini…
    → J'suis obligée de garder un fichier externe de toutes façons: pour
    sauvegarder les posts et l'offset…
 - Est-ce qu'avoir des variables globales c'est une mauvaise pratique?
 Ça me simplifierait la vie, parce qu'envoyer tous les trucs nécessaires
 dans les arguments de fonctions qui s'en servent pas mais appellent
 d'autres fonctions qui s'en servent c'est moche.

TODO:
    - catcher les erreurs !!! Y'en a encore plein qui peuvent tuer le script.
        - tous les requests.get() par exemple (bin ouais, si telegram est down
            ou si mon serveur n'a plus de réseau…)
    - Faire que le bot reposte dans le groupe les messages postés dans le topic
        sur maischal
    - QUID de si y'a aucune update dans l'appel de l'API? huuu
    - Dans notre list de posts avoir deux champs: time et content, histoire
        de pouvoir la trier pour poster dans l'ordre de tout temps.
        (parce que pour l'instant si poster fail, on enregistre la suite et on ferme.)
'''



''' 
 Fonctions pour afficher les erreurs 
'''

# afficher un message d'erreur (sans sortir)
def gueule(message):
    print(strftime("%Y-%m-%d %H:%M:%S", gmtime()), ": ", message, sep="")

# Message d'erreur pour expliquer le fichier de config
def print_configfile_error_and_exit(err):
    print('"', CONFIGFILE,'" malformé.', sep='')
    print('Celui-ci doit être de la forme :')
    print('[telegram]')
    print('token="<telegram bot API token>"')
    print('authorized_channel=<id du chan telegram>')
    print('[maischal]')
    print('username=<username>')
    print('password=<password>')
    print('[common]')
    print('files_dir=<directory to store files from telegram>/')
    print('files_url=<URL d\'accès aux fichiers (photos…)>/')
    print()
    print("Message d'erreur:", err)
    exit(1)


'''
 Gestion du fichier de config
'''

# Récupération de la config depuis le fichier
def get_config():
    cp = configparser.ConfigParser()

    # essayons d'ouvrir le fichier de config
    try:
        # read_file() pour réagir si le fichier n'existe pas
        cp.read_file(open(CONFIGFILE))
    except FileNotFoundError:
        print("Fichier '", CONFIGFILE, "' manquant.", sep='')
        exit(1)
    except configparser.Error as err:
        print_configfile_error_and_exit(err)

    # essayons de lire son contenu
    config = {}
    try:
        config['telegram_token'] = cp.get('telegram', 'token')
        config['authorized_channel'] = int(cp.get('telegram', 'authorized_channel'))
        config['files_dir'] = cp.get('common', 'files_dir')
        config['files_url'] = cp.get('common', 'files_url')
        config['maischal_user'] = cp.get('maischal','username')
        config['maischal_pass'] = cp.get('maischal','password')
    except configparser.Error as err:
        print_configfile_error_and_exit(err)
    # Le dossier de stockage des fichiers existe-t-il ?
    if not os.path.isdir(config['files_dir']):
        gueule("Le dossier '" + config['files_dir'] + "' n'existe pas!")
        exit(1)
    # Check qu'elle fini par un slash?
    if config['files_dir'][-1] != "/":
        gueule("files_dir doit terminer par un slash")
        exit(1)
    # l'url fini-t-elle bien par un slash?
    if config['files_url'][-1] != "/":
        gueule("files_url doit terminer par un slash")
        exit(1)
    # y'a-t-il un offset pour les updates telegram?
    config['telegram_offset'] = cp.get('telegram', 'offset', fallback=None)
    return config

def update_offset_in_configfile(offset):
    offset = str(offset)
    cp = configparser.ConfigParser()
    # le fichier existe forcément puisqu'on a pu lire la config jusqu'à maintenant
    # donc nik l'error handling
    cp.read(CONFIGFILE)
    cp.set('telegram', 'offset', offset)
    # Python ferme tout seule fichier à la fin du with. Stylé.
    with open(CONFIGFILE, 'w') as f: cp.write(f)


'''
 Fonctions pour traiter l'API telegram
'''

# Récupérer la listes des nouveaux messages
def get_updates(token, offset):
    url = URL + token + "/getUpdates"
    if offset:
        url += "?offset={}".format(offset)
    ok = False
    while not ok:
        response = requests.get(url)
        content = response.content.decode("utf8")
        content = json.loads(content)
        ok = content['ok']
        # Si l'API nous a dit que ça n'allait pas
        if not ok:
            gueule("Echec de getUpdates: " + content['description'])
            # Avec un peu de chance elle nous a dit combien de temps attendre
            try:
                sleep(int(content['parameters']['retry_after']) + 10)
            # Sinon on attend juste 10 secondes et on réessaie.
            except:
                sleep(10)
                pass
    # on renvoie que la partie "result"
    return content['result']

# Télécharger un fichier présent dans un message
def get_file(token, file_id, files_dir):
    url = URL + token + "/getFile?file_id=" + file_id
    r = requests.get(url)
    content = r.content.decode("utf8")
    js = json.loads(content)
    # L'API met true dans 'ok' si tout s'est bien passé
    if not js['ok']:
        gueule("getFile a échoué: " + str(js['description']))
        return False
    fpath= js['result']['file_path']
    url = "https://api.telegram.org/file/bot" + token + "/" + fpath
    r = requests.get(url)
    directory = os.path.dirname(fpath)
    # l'API nous donne un nom comme "photo/file_1.jpg", créons alors le
    # dossier "photo" s'il n'existe pas.
    if not os.path.exists(files_dir + directory):
        try:
            os.makedirs(files_dir + directory)
        except OSError(errno, strerror):
            gueule("Impossible de créer le dossier " + files_dir + directory +
                    ", le système a retourné: Erreur " + errno + ", " + strerror)
    # ajoutons l'heure au nom du fichier histoire de s'assurer que y'en aura
    # pas deux pareil
    file_name = strftime("%Y-%m-%d--%H%M%S-", gmtime()) + os.path.basename(fpath)
    # mais quand même si jamais un fichier du même nom existe déjà, on attend une
    # seconde et on recommence (TODO: ça se simplifie ça, merde!)
    while os.path.exists(file_name):
        sleep(1)
        file_name = strftime("%Y-%m-%d--%H%M%S-", gmtime()) + os.path.basename(fpath)
    try:
        open(files_dir + directory + "/" + file_name, 'wb').write(r.content)
        # on renvoie un truc genre "photos/file-nanani.jpg"
        return directory + "/" + file_name
    except OSError(errno, strerror):
        gueule("Impossible d'enregistrer le fichier " + files_dir + directory + file_name +
                ", le système a retourné: Erreur " + errno + ", " + strerror)
        return False

# Pour envoyer un message dans un chan (genre si le bot est invité dans un autre groupe ou
# si un·e random lui parle)
def send_message(text, chat_id, token):
    text = urllib.parse.quote_plus(text)
    url = URL + token + "/sendMessage?text={}&chat_id={}".format(text, chat_id)
    try:
        requests.get(url)
    except:
        gueule("Impossible d'envoyer un message au chat d'id " + chat_id +
                ", le message étant: " + text)


'''
 Fonctions pour fabriquer les posts
'''

# Transformer les updates en posts compréhensibles par les-forums.com
def create_single_post(message, files_dir, files_url, token):
    # TODO: changer le sender (kubanto→zecho, viroulep→mr0, …)
    #       avec un dict {"kubanto":"zecho", "viroulep":"mr0}
    #       puis un try: sender=dict[sender] et hop
    
    sender = message['from']['first_name']
    date = strftime("%d/%m/%Y", gmtime(message['date']))
    t = strftime("%H:%M:%S", gmtime(message['date']))
    # Construction du message
    msg = "[quote De " + sender + ", le " + date + " à " + t
    # Si on est dans un message transféré
    if 'forward_date' in message:
        # On prend le nom original s'il existe, sinon le nom affiché, sinon give up
        if 'forward_from' in message:
            msg += ", message original de " + message['forward_from']['first_name']
        elif 'forward_sender_name' in message:
            msg += ", message original de " + message['forward_sender_name']
        else:
            msg += ", message transféré"
        t = strftime("%H:%M:%S", gmtime(message['forward_date']))
        date = strftime("%d/%m/%Y", gmtime(message['forward_date']))
        msg += ", posté le " + date + " à " + t
    # Fermons le [quote]
    msg += "]"
    # On devra vérifier s'il y a bien du contenu qu'on sait gérer
    has_known_content = False
    # si c'est une réponse, on refabrique un message complet depuis ce reply
    if 'reply_to_message' in message:
        has_known_content = True
        reply = create_single_post( message['reply_to_message'], files_dir, files_url, token )
        msg += reply
    # Si y'a du texte
    if 'text' in message:
        has_known_content = True
        msg += "\n" + message['text']
    # peut-être y'a une photo
    if 'photo' in message:
        has_known_content = True
        size = 0
        # Allons chercher la plus grande, sauf si elle fait plus de 20M
        # (interdit par telegram, donc ça donnera une erreur sur get_file())
        for (key, value) in enumerate(message['photo']):
            if (value['file_size'] > size) and (value['file_size'] <= 20971520):
                fsize = value['file_size']
                fid = value['file_id']
        # Si get_file() foire, on remplace par un texte
        f = get_file(token=token, file_id=fid, files_dir=files_dir)
        if not f:
            msg += "\n(Le fichier n'a pas pu être téléchargé, regardez les logs du bot.)"
        # Mais s'il a marché, insérons l'image dans le message
        else:
            msg += "[img " + files_url + f + "]"
            # et la caption de l'image
            if 'caption' in message:
                msg += "\n[i]" + message['caption'] + "[/i]"
    # Peut-être y'a un sticker
    if 'sticker' in message:
        has_known_content = True
        fid = message['sticker']['file_id']
        # Si get_file() foire, on remplace par un texte
        f = get_file(token=token, file_id=fid, files_dir=files_dir)
        if not f:
            msg += "\n(Le fichier n'a pas pu être téléchargé, regardez les logs du bot.)"
        # Mais s'il a marché, insérons l'image dans le message
        else:
            # les navigateurs lisent pas le webp alors on converti
            if os.path.splitext(f)[1] == ".webp":
                conv = os.system("convert " + files_dir + f + " " + files_dir + os.path.splitext(f)[0] + ".gif 1>/dev/null 2>&1")
                if conv == 0:
                    # Supprime le fichier
                    try:
                        os.remove(files_dir + f)
                    except:
                        gueule("Pas réussi à supprimer " + files_dir + f)
                    f = os.path.splitext(f)[0] + ".gif"
            msg += "[img " + files_url + f + "]"
    # TODO: Gérer "animation"
    # Si on a pas eu de contenu qu'on sait gérer
    if not has_known_content:
        msg += "\nMaischalbot est incapable de gérer ce contenu:\n"
        msg += pprint.pformat(message)
    msg += "[/quote]"
    return msg

# Contruisons notre array de posts
def create_posts_and_get_offset(messages, authorized_channel, files_dir, files_url, token):
    # initialisons la liste des posts
    posts = []
    for message in messages:
        # si c'est bien le groupe maischal
        if message['message']['chat']['id'] == authorized_channel:
            # on ajoute le contenu du message au dict
            posts.append( create_single_post(message['message'], files_dir, files_url, token) )
        # sinon on gueule dans le chan (ranafout')
        '''
	else:
            send_message(
                    "This bot is useless for you. Fuck capitalism, racism, sexism, " +
                    "transphobia, ableism, and all oppressions. Bye.",
                    message['message']['chat']['id'],
                    token)
	'''
    # enregistrons enfin le update_id+1 qui servira d'offset pour le prochain appel de l'API
    offset = messages[len(messages)-1]['update_id']+1
    return offset, posts


'''
 Fonctions pour sauvegarder des posts en local,
 et publier ces posts plus tard
'''

# Enregistrer les posts localement
def save_posts(posts):
    # ouvrons le fichier kivabien
    try:
        f = open(SAVED_POSTS_FILE, "w")
    except OSError(errno, strerror, filename):
        gueule("Impossible de sauvegarder les posts, erreur " + errno + " lors de l'ouverture de " +
                filename + ". open() a retourné: " + strerror)
        return False
    else:
        try:
            # Écrivons le json dans le fichier
            json.dump(posts, f)
            # Et sortons, ravie.
            return True
        except json.JSONDecodeError(msg):
            # Ou râlons et sortons.
            gueule("Erreur d'encodage lors de la sauvegarde des posts. " +
                    "JSON a retourné: " + msg)
            return False
        finally:
            # Mais dans tous les cas, fermons le fichier.
            f.close()

# Récupérer les posts sauvegardés
def load_saved_posts():
    ### TODO: s'assurer qu'il retourne bien une list, pas autre chose
    # on essaie d'ouvrir le fichier
    try:
        f = open(SAVED_POSTS_FILE, "r")
    # S'il existe pas
    except OSError:
        # on renvoie une list vide
        return []
    # Si on a réussi à ouvrir le fichier
    # Contient-il du JSON valide ?
    try:
        old_posts = json.load(f)
    # si non, on gueule un coup et on renvoie une liste vide
    except json.JSONDecodeError as err:
        gueule("Erreur de décodage lors de la restauration des posts." +
                "JSON a retourné: " + err.msg)
        return []
    # Si ça a marché, on retourne le contenu
    else:
        return old_posts
    # et dans tous les cas on ferme le file pointer
    finally:
        f.close()


'''
 Fonctions pour poster sur maischal
'''

# Pour se connecter au forum
def maischal_login(br, user, password):
    # on ouvre la page maischal
    try:
        br.open("http://maischal.les-forums.com/")
    # Si ça marche pas (on sait comment maischal plante)
    except:
        # On gueule et on sort
        gueule("Impossible d'ouvrir maischal, :sad:")
        return False
    # On a du être redigirée à la page de connexion
    try:
        # Auquel cas on selectionne le formulaire qui va bien
        # (car il y en a plusieurs dans la page)
        br.select_form('form[action="/account/login/post/"]')
    # Si non, ou s'il a changé, ciao.
    except:
        gueule("Le formulaire de maischal a du changer, impossible de se connecter.")
        return False
    # On remplit le formulaire
    br["pseudo"] = user
    br["pwd"] = password
    # Et on l'envoie
    resp = br.submit_selected()
    formulaire = resp.soup.find("input", id="champ_pseudo")
    if formulaire:
        gueule("Echec de la connexion à maischal (lors de l'envoi du formulaire)…")
        return False
    else:
        return True

def post_message(br, message):
    # on ouvre le bon topic
    br.open("http://maischal.les-forums.com/topic/1004/")
    # on cherche le formulaire
    try:
        form = br.select_form('form[action="/topic/1004/message/add/"]')
    except:
        gueule("Impossible de trouver le formulaire pour poster un message…")
        return False
    # Vu que mechanicalSoup ne fait que de l'UTF-8 et que jean-connard de les-forums.com
    # fait du cp1252, on doit se faire un peu chier:
    payload = {}
    for fi in form.form.findAll("input"):
        try:
            payload[fi['name']] = fi['value'].encode("cp1252")
        except:
            # On ne réagit à aucune erreur car OSEF si y'a un input sans name= ou sans value=
            # Et si y'a une erreur d'encodage OSEF aussi? À voir.
            pass
    # TODO: changer l'icone et le texte du post envoyé?
    payload["msg"] = message.encode("cp1252")
    # les-forums.com fait chier, mais si on sleep 3 secondes ici ça passe.
    sleep(3)
    #osef: payload["voir_resultat"] = True
    resp = br.session.post("http://maischal.les-forums.com/topic/1004/message/add/", data = payload)
    br.add_soup(resp, br.soup_config)
    if not resp.soup.findAll("div", text="Le message a bien été enregistré."):
        gueule("Impossible d'enregistrer le message (lors de la soumission du formulaire)")
        return False
    return True


'''
 Tout commence ici.
'''

def main():
    ### TODO: utiliser les arguments nommés plutôt que les positionnal args
    # récupérons la config
    config = get_config()
    # Allons chercher les updates via l'API
    updates = get_updates(
            config['telegram_token'],
            config['telegram_offset'])
    # Si pas d'updates, on quitte directos
    ## TODO: essayer de poster les messages sauvegardés s'il y'en a?
    if updates == []:
        exit(0)
    # Fabriquons les posts et récupérons l'offset
    offset, new_posts = create_posts_and_get_offset(
            messages = updates, 
            files_dir = config['files_dir'],
            files_url = config['files_url'],
            token = config['telegram_token'],
            authorized_channel = config['authorized_channel'])

    # Récupérons les posts sauvegardés
    posts = load_saved_posts()

    # Fusionnons-les avec les posts récupérés de télégram
    posts.extend(new_posts)

    ## Ok, maintenant on a une list avec tous les posts.

    # Lançons un navigateur
    browser = mechanicalsoup.StatefulBrowser()
    # Peut-être y'aura-t-il des posts à sauvegarder
    posts_to_save = []
    # Connectons-nous à maischal dans ce navigateur
    if maischal_login(browser, config['maischal_user'], config['maischal_pass']):
        # Postons les messages
        for (key, post) in enumerate(posts):
            if not post_message(browser, post):
                gueule("Pas réussi à poster le message.")
                # si ça marche pas, on enregiste le post loupé et tous les
                # suivants, et on sort de la boucle.
                posts_to_save = posts[key:]
                break
    # S'il y'a des posts à sauvegarder (et si y'en a pas ça vide le fichier)
    save_posts(posts_to_save)
    # Mettons à jour l'offset
    update_offset_in_configfile(offset)

# si c'est bien ce fichier qui est lancé directement, let's do the work
if __name__ == '__main__':
    main()
