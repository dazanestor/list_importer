from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from marshmallow import Schema, fields, ValidationError
import json
import requests
from tasks import run_sync_movies, run_sync_series
import redis
import logging

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Definición de schemas para validación
class ConfigSchema(Schema):
    movies_min_year = fields.Int(required=True)
    movies_max_year = fields.Int(required=True)
    movies_min_rating = fields.Float(required=True)
    series_min_year = fields.Int(required=True)
    series_max_year = fields.Int(required=True)
    series_min_rating = fields.Float(required=True)
    radarr_quality_profile_id = fields.Int(required=True)
    radarr_root_folder_path = fields.Str(required=True)
    sonarr_quality_profile_id = fields.Int(required=True)
    sonarr_root_folder_path = fields.Str(required=True)

def read_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def write_config(data):
    config = read_config()
    config.update(data)
    with open('config.json', 'w') as f:
        json.dump(config, f, indent=4)

def get_radarr_profiles_and_paths():
    config = read_config()
    headers = {"X-Api-Key": config['radarr_api_key']}
    profiles = requests.get(f"{config['radarr_url']}/api/v3/qualityProfile", headers=headers).json()
    paths = requests.get(f"{config['radarr_url']}/api/v3/rootFolder", headers=headers).json()
    return profiles, paths

def get_sonarr_profiles_and_paths():
    config = read_config()
    headers = {"X-Api-Key": config['sonarr_api_key']}
    profiles = requests.get(f"{config['sonarr_url']}/api/v3/qualityProfile", headers=headers).json()
    paths = requests.get(f"{config['sonarr_url']}/api/v3/rootFolder", headers=headers).json()
    return profiles, paths

def get_existing_titles(url, api_key, media_type):
    headers = {"X-Api-Key": api_key}
    endpoint = f"{url}/api/v3/{'movie' if media_type == 'movie' else 'series'}"
    response = requests.get(endpoint, headers=headers)
    if response.status_code == 200:
        return [item['title'] for item in response.json()]
    return []

def get_excluded_titles(url, api_key, media_type):
    headers = {"X-Api-Key": api_key}
    endpoint = f"{url}/api/v3/{'movie' if media_type == 'movie' else 'series'}/lookup?term=all"
    response = requests.get(endpoint, headers=headers)
    if response.status_code == 200:
        return [item['title'] for item in response.json() if item['monitored'] == False]
    return []

config = read_config()
r = redis.Redis(host=config['redis_ip'], port=6379, db=0)

@app.route('/', methods=['GET', 'POST'])
def index():
    config = read_config()
    radarr_profiles, radarr_paths = [], []
    sonarr_profiles, sonarr_paths = [], []
    
    try:
        radarr_profiles, radarr_paths = get_radarr_profiles_and_paths()
    except requests.exceptions.RequestException as e:
        flash(f"Error al obtener perfiles y rutas de Radarr: {str(e)}")
    
    try:
        sonarr_profiles, sonarr_paths = get_sonarr_profiles_and_paths()
    except requests.exceptions.RequestException as e:
        flash(f"Error al obtener perfiles y rutas de Sonarr: {str(e)}")
    
    imported_movies = json.loads(r.get('imported_movies') or '[]')
    imported_series = json.loads(r.get('imported_series') or '[]')

    existing_movies = get_existing_titles(config['radarr_url'], config['radarr_api_key'], 'movie')
    existing_series = get_existing_titles(config['sonarr_url'], config['sonarr_api_key'], 'tv')

    excluded_movies = get_excluded_titles(config['radarr_url'], config['radarr_api_key'], 'movie')
    excluded_series = get_excluded_titles(config['sonarr_url'], config['sonarr_api_key'], 'tv')

    filtered_movies = [movie for movie in imported_movies if movie not in existing_movies and movie not in excluded_movies]
    filtered_series = [series for series in imported_series if series not in existing_series and series not in excluded_series]

    if request.method == 'POST':
        form_data = {
            "movies_min_year": int(request.form['movies_min_year']),
            "movies_max_year": int(request.form['movies_max_year']),
            "movies_min_rating": float(request.form['movies_min_rating']),
            "series_min_year": int(request.form['series_min_year']),
            "series_max_year": int(request.form['series_max_year']),
            "series_min_rating": float(request.form['series_min_rating']),
            "radarr_quality_profile_id": int(request.form['radarr_quality_profile_id']),
            "radarr_root_folder_path": request.form['radarr_root_folder_path'],
            "sonarr_quality_profile_id": int(request.form['sonarr_quality_profile_id']),
            "sonarr_root_folder_path": request.form['sonarr_root_folder_path'],
        }
        schema = ConfigSchema()
        try:
            config = schema.load(form_data)
            write_config(config)
            flash('Configuración guardada exitosamente!')
            return redirect(url_for('index'))
        except ValidationError as err:
            flash(f"Errores de validación: {err.messages}")
    
    return render_template('index.html', config=config, radarr_profiles=radarr_profiles, radarr_paths=radarr_paths, sonarr_profiles=sonarr_profiles, sonarr_paths=sonarr_paths, imported_movies=filtered_movies, imported_series=filtered_series)

@app.route('/run-sync-movies', methods=['POST'])
def run_sync_movies_now():
    logger.info("Iniciando sincronización de películas...")
    run_sync_movies.delay()
    flash('Sincronización de películas iniciada!')
    return redirect(url_for('index'))

@app.route('/run-sync-series', methods=['POST'])
def run_sync_series_now():
    logger.info("Iniciando sincronización de series...")
    run_sync_series.delay()
    flash('Sincronización de series iniciada!')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
