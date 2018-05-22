import requests
import pandas as pd
import numpy as np
import os
import time
import pickle
import json
import xml.etree.ElementTree as ET


CFG = os.path.join(os.path.expanduser('~'), '.config', 'movescount-sync')
SESSION_PATH = os.path.join(CFG, 'session.pickle')

class Urls:
    overview = 'http://www.movescount.com/overview'
    login = 'https://servicegate.suunto.com/UserAuthorityService/'
    token = 'https://www.movescount.com/services/UserAuthenticated'
    login_referer = 'https://www.movescount.com/auth?redirect_uri=%2foverview'
    export = 'http://www.movescount.com/move/export'

def login(session, email, password):

    ts = int(time.time() * 1000)
    response = session.get(Urls.login, params={
        'callback': f'jQuery18104619530053417804_{ts}',
        'service': 'Movescount',
        'emailAddress': email,
        'password': password,
        '_': ts + 27314,
    }, headers={'Referer': Urls.login_referer})
    response.raise_for_status()
    token = response.text.split('"')[1]
    response = session.post(Urls.token, json={'token': token,
                                              'utcOffset': '60',
                                              'redirectUri': '/overview'})
    response.raise_for_status()

def get_session():
    if not os.path.exists(SESSION_PATH):
        return requests.Session()
    with open(SESSION_PATH, 'rb') as f:
        return pickle.load(f)

def get_overview(session):
    response = session.get(Urls.overview)

    data = response.text.split(
        'mc.OverviewPage.default.main(')[1].split(');')[0]
    config = json.loads(data)['activityFeed']

    url = config['feeds']['me']['id']

    empty = False
    token = config['token']
    moves = []
    recurse = False
    while not empty:
        feed_url = '{}/{}'.format(config['url'], url)
        response = session.get(feed_url, params={'token': token})
        data = response.json()
        moves.extend(data['objects'][1:-1])
        empty = len(data['objects']) == 2 or not recurse
        url = data['objects'][-1]['url']

    df_moves = pd.DataFrame(moves)
    df_moves['LocalStartTime'] = pd.to_datetime(df_moves['LocalStartTime'])
    df_moves['UTCStartTime'] = pd.to_datetime(df_moves['UTCStartTime'])

    return df_moves

def get_move(session,move = None,event_id = None):

    if move is None:
        if event_id is None:
            raise ValueError('Please pass a move or event_id as argument')

    else:
        event_id = move['eventObjectId']

    format = 'kml'
    resp = session.get(Urls.export, params={'id': event_id,
                                            'format': format})

    content = resp.content.decode('utf8')

    namespaces = {'kml': 'http://www.opengis.net/kml/2.2',
                  'ext': 'http://www.google.com/kml/ext/2.2'}
    root = ET.fromstring(content)

    coordinates2 = root.find('kml:Document/kml:Folder/kml:Placemark[2]/ext:Track', namespaces=namespaces)

    whens = coordinates2.findall('kml:when', namespaces=namespaces)
    coords = coordinates2.findall('ext:coord', namespaces=namespaces)

    df_coordinates = pd.DataFrame()

    for when, coord in zip(whens, coords):
        s = pd.Series()
        s.name = when.text
        sub_coords = coord.text.split(' ')
        s['longitude'] = sub_coords[0]
        s['latitude'] = sub_coords[1]
        s['height'] = sub_coords[2]
        df_coordinates = df_coordinates.append(s)

    df_coordinates.index = pd.to_datetime(df_coordinates.index)

    extended_data = coordinates2.find('kml:ExtendedData', namespaces=namespaces)
    schema_data = extended_data.find('kml:SchemaData', namespaces=namespaces)

    for array_data in schema_data:

        values = array_data.findall('ext:value', namespaces=namespaces)
        data = []
        for value in values:
            data.append(float(value.text))

        s = pd.Series(data)
        s.name = array_data.attrib['name']

        df_coordinates[s.name] = np.array(s)

    return df_coordinates