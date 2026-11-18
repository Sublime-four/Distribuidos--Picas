"""API REST de Picas y Fijas. Solo usa la biblioteca estándar de Python.

    python server.py        # escucha en el puerto 8080 (variable PUERTO)

Rutas:
    POST /login               registra el nombre del jugador
    POST /juego               crea un juego
    GET  /juego               lista los juegos (?estado=por_iniciar|en_juego|terminado)
    GET  /juego/{id}          estado de un juego
    PUT  /juego/{id}          unirse a un juego
    POST /juego/{id}/jugar    enviar un intento
    GET  /                    front básico para probar
    GET  /healthz             sonda de salud para Kubernetes
"""

import json
import os
import re
import signal
import socket
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from juego import ErrorJuego, Partidas

PUERTO = int(os.environ.get("PUERTO", "8080"))
DIRECTORIO = os.path.dirname(os.path.abspath(__file__))
MAX_CUERPO = 10_000  # bytes; las peticiones del juego son muy pequeñas

partidas = Partidas()  # todo el estado del servicio


# ------------------------------------------------------------ endpoints
# Cada función recibe los datos de la petición (el JSON del cuerpo en POST
# y PUT, los parámetros de la URL en GET) y devuelve (código HTTP, respuesta).

def login(datos):
    nombre, es_nuevo = partidas.registrar(datos.get("nombre"))
    if es_nuevo:
        return 201, {"nombre": nombre, "mensaje": "Jugador registrado."}
    return 200, {"nombre": nombre, "mensaje": "El jugador ya estaba registrado."}


def crear_juego(datos):
    return 201, partidas.crear(datos.get("nombre"), datos.get("numero"))


def listar_juegos(datos):
    return 200, partidas.listar(datos.get("estado"))


def ver_juego(datos, id_juego):
    return 200, partidas.ver(id_juego)


def unirse(datos, id_juego):
    return 200, partidas.unirse(id_juego, datos.get("nombre"), datos.get("numero"))


def jugar(datos, id_juego):
    return 200, partidas.jugar(id_juego, datos.get("nombre"), datos.get("numero"))


RUTAS = [
    ("POST", re.compile(r"/login"), login),
    ("POST", re.compile(r"/juego"), crear_juego),
    ("GET", re.compile(r"/juego"), listar_juegos),
    ("GET", re.compile(r"/juego/(\d{1,9})"), ver_juego),
    ("PUT", re.compile(r"/juego/(\d{1,9})"), unirse),
    ("POST", re.compile(r"/juego/(\d{1,9})/jugar"), jugar),
]


# ------------------------------------------------------------ capa HTTP

class Manejador(BaseHTTPRequestHandler):
    server_version = "PicasFijas/1.0"
    timeout = 15  # segundos; corta conexiones que se quedan sin enviar nada

    def atender(self):
        try:
            url = urlsplit(self.path)
            ruta = url.path.rstrip("/") or "/"
            metodo = self.command
            cuerpo = self.leer_cuerpo()

            if metodo == "GET" and ruta in ("/", "/index.html"):
                with open(os.path.join(DIRECTORIO, "index.html"), "rb") as archivo:
                    return self.enviar(200, "text/html; charset=utf-8", archivo.read())
            if metodo == "GET" and ruta == "/healthz":
                return self.enviar_json(200, {"estado": "ok", "pod": socket.gethostname()})

            otros_metodos = []
            for metodo_ruta, patron, funcion in RUTAS:
                coincide = patron.fullmatch(ruta)
                if not coincide:
                    continue
                if metodo_ruta != metodo:
                    otros_metodos.append(metodo_ruta)
                    continue
                datos = self.a_json(cuerpo) if metodo in ("POST", "PUT") else dict(parse_qsl(url.query))
                codigo, respuesta = funcion(datos, *map(int, coincide.groups()))
                cabeceras = {}
                if codigo == 201 and "id" in respuesta:
                    cabeceras["Location"] = f"/juego/{respuesta['id']}"
                return self.enviar_json(codigo, respuesta, cabeceras)

            if otros_metodos:
                return self.enviar_json(
                    405,
                    {"error": f"El método {metodo} no está permitido en {ruta}."},
                    {"Allow": ", ".join(otros_metodos)},
                )
            self.enviar_json(404, {"error": f"No existe la ruta {ruta}."})
        except ErrorJuego as error:
            self.enviar_json(error.codigo, {"error": error.mensaje})
        except (ConnectionError, socket.timeout):
            pass  # el cliente cerró la conexión o dejó de enviar: no hay a quién responder
        except Exception:
            traceback.print_exc()
            self.enviar_json(500, {"error": "Error interno del servidor."})

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = atender

    def leer_cuerpo(self):
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ErrorJuego(400, "La cabecera Content-Length no es válida.")
        if largo > MAX_CUERPO:
            self.rfile.read(min(largo, 1_000_000))  # se descarta, para poder responder limpio
            raise ErrorJuego(413, "El cuerpo de la petición es demasiado grande.")
        return self.rfile.read(largo) if largo > 0 else b""

    @staticmethod
    def a_json(cuerpo):
        if not cuerpo:
            return {}
        try:
            datos = json.loads(cuerpo)
        except (ValueError, RecursionError):
            raise ErrorJuego(400, "El cuerpo de la petición debe ser JSON válido.")
        if not isinstance(datos, dict):
            raise ErrorJuego(400, 'El cuerpo debe ser un objeto JSON, por ejemplo {"nombre": "ana"}.')
        return datos

    def enviar_json(self, codigo, datos, cabeceras=None):
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.enviar(codigo, "application/json; charset=utf-8", cuerpo, cabeceras)

    def enviar(self, codigo, tipo, cuerpo, cabeceras=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for nombre, valor in (cabeceras or {}).items():
            self.send_header(nombre, valor)
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, formato, *args):
        # Las sondas de Kubernetes llegan cada pocos segundos: no las registramos.
        if "/healthz" not in getattr(self, "path", ""):
            super().log_message(formato, *args)


class Servidor(ThreadingHTTPServer):
    """Un hilo por petición."""

    daemon_threads = True
    request_queue_size = 64


def crear_servidor(puerto=PUERTO):
    return Servidor(("", puerto), Manejador)


def main():
    # Kubernetes detiene el pod con SIGTERM: salimos de inmediato y sin error.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with crear_servidor() as servidor:
        print(f"Picas y Fijas escuchando en http://localhost:{PUERTO}", flush=True)
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
