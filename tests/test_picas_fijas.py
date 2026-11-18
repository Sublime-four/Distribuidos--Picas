import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import server
from juego import ErrorJuego, Partidas, contar, validar_numero


class ValidarNumero(unittest.TestCase):
    def test_acepta_cuatro_digitos_distintos(self):
        self.assertEqual(validar_numero("1234"), "1234")
        self.assertEqual(validar_numero("0123"), "0123")
        self.assertEqual(validar_numero(" 4271 "), "4271")
        self.assertEqual(validar_numero(9876), "9876")

    def test_rechaza_entradas_invalidas(self):
        casos = [
            ("123", "exactamente 4"),
            ("12345", "exactamente 4"),
            (123, "exactamente 4"),
            ("1123", "repetidos"),
            ("12a4", "solo puede tener dígitos"),
            ("abcd", "solo puede tener dígitos"),
            ("12 4", "solo puede tener dígitos"),
            ("-123", "solo puede tener dígitos"),
            ("12.4", "solo puede tener dígitos"),
            ("１２３４", "solo puede tener dígitos"),
            ("", "vacío"),
            ("   ", "vacío"),
            (None, "Falta"),
            (12.5, "como texto"),
            (True, "como texto"),
            ([1, 2, 3, 4], "como texto"),
        ]
        for valor, fragmento in casos:
            with self.subTest(valor=valor):
                with self.assertRaises(ErrorJuego) as contexto:
                    validar_numero(valor)
                self.assertEqual(contexto.exception.codigo, 400)
                self.assertIn(fragmento, contexto.exception.mensaje)


class Contar(unittest.TestCase):
    def test_ejemplo_del_enunciado(self):
        self.assertEqual(contar("4271", "1234"), (1, 2))

    def test_otros_casos(self):
        self.assertEqual(contar("1234", "1234"), (4, 0))
        self.assertEqual(contar("1234", "5678"), (0, 0))
        self.assertEqual(contar("1234", "4321"), (0, 4))
        self.assertEqual(contar("1234", "1243"), (2, 2))
        self.assertEqual(contar("0593", "0123"), (2, 0))


class Partida(unittest.TestCase):
    def setUp(self):
        self.partidas = Partidas()
        self.partidas.registrar("ana")
        self.partidas.registrar("luis")

    def error(self, codigo, funcion, *args):
        with self.assertRaises(ErrorJuego) as contexto:
            funcion(*args)
        self.assertEqual(contexto.exception.codigo, codigo, contexto.exception.mensaje)
        return contexto.exception.mensaje

    def test_login(self):
        self.assertEqual(self.partidas.registrar("  maria  "), ("maria", True))
        self.assertEqual(self.partidas.registrar("maria"), ("maria", False))
        self.error(400, self.partidas.registrar, "")
        self.error(400, self.partidas.registrar, None)
        self.error(400, self.partidas.registrar, 42)
        self.error(400, self.partidas.registrar, "x" * 21)

    def test_partida_completa(self):
        juego = self.partidas.crear("ana", "4271")
        self.assertEqual(juego["estado"], "por_iniciar")
        self.assertEqual(juego["creador"], "ana")
        self.assertIsNone(juego["turno"])

        juego = self.partidas.unirse(juego["id"], "luis", "0593")
        self.assertEqual(juego["estado"], "en_juego")
        self.assertEqual(juego["jugadores"], ["ana", "luis"])
        primero = juego["turno"]
        segundo = "luis" if primero == "ana" else "ana"
        secreto = {"ana": "4271", "luis": "0593"}

        self.assertIn(primero, self.error(409, self.partidas.jugar, 1, segundo, "1234"))

        respuesta = self.partidas.jugar(1, primero, "1234")
        self.assertEqual((respuesta["fijas"], respuesta["picas"]), contar(secreto[segundo], "1234"))
        self.assertFalse(respuesta["gano"])
        self.assertEqual(respuesta["turno"], segundo)

        self.error(409, self.partidas.jugar, 1, primero, "5678")

        self.assertNotIn("numeros", self.partidas.ver(1))

        respuesta = self.partidas.jugar(1, segundo, secreto[primero])
        self.assertTrue(respuesta["gano"])
        self.assertEqual(respuesta["fijas"], 4)
        self.assertEqual(respuesta["estado"], "terminado")

        final = self.partidas.ver(1)
        self.assertEqual(final["estado"], "terminado")
        self.assertEqual(final["ganador"], segundo)
        self.assertIsNone(final["turno"])
        self.assertEqual(final["numeros"], secreto)
        self.assertEqual(len(final["intentos"]), 2)

        self.error(409, self.partidas.jugar, 1, primero, "5678")

    def test_reglas_de_acceso(self):
        self.error(401, self.partidas.crear, "nadie", "1234")
        self.error(400, self.partidas.crear, "ana", "1123")
        self.partidas.crear("ana", "1234")
        self.error(404, self.partidas.ver, 99)
        self.error(404, self.partidas.unirse, 99, "luis", "5678")
        self.error(409, self.partidas.jugar, 1, "ana", "5678")
        self.error(409, self.partidas.unirse, 1, "ana", "5678")
        self.error(400, self.partidas.unirse, 1, "luis", "56x8")
        self.partidas.unirse(1, "luis", "5678")
        self.partidas.registrar("maria")
        self.error(409, self.partidas.unirse, 1, "maria", "9012")
        self.error(403, self.partidas.jugar, 1, "maria", "9012")
        turno = self.partidas.ver(1)["turno"]
        self.error(400, self.partidas.jugar, 1, turno, "99")
        self.assertEqual(self.partidas.ver(1)["turno"], turno)

    def test_el_primer_turno_es_aleatorio(self):
        primeros = set()
        for _ in range(200):
            juego = self.partidas.crear("ana", "1234")
            primeros.add(self.partidas.unirse(juego["id"], "luis", "5678")["turno"])
        self.assertEqual(primeros, {"ana", "luis"})

    def test_listar(self):
        self.partidas.crear("ana", "1234")
        self.partidas.crear("luis", "5678")
        self.partidas.unirse(2, "ana", "1234")
        lista = self.partidas.listar()
        self.assertEqual([(j["id"], j["estado"], j["creador"]) for j in lista],
                         [(1, "por_iniciar", "ana"), (2, "en_juego", "luis")])
        self.assertNotIn("numeros", lista[0])
        self.assertEqual([j["id"] for j in self.partidas.listar("por_iniciar")], [1])
        self.assertEqual(self.partidas.listar("terminado"), [])
        self.error(400, self.partidas.listar, "otro")


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.Manejador.log_message = lambda *args: None
        cls.servidor = server.crear_servidor(0)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()

    def setUp(self):
        server.partidas = Partidas()

    def pedir(self, metodo, ruta, cuerpo=None, crudo=None):
        datos = crudo if crudo is not None else (json.dumps(cuerpo).encode() if cuerpo is not None else None)
        peticion = urllib.request.Request(self.base + ruta, data=datos, method=metodo,
                                          headers={"Content-Type": "application/json"})
        try:
            respuesta = urllib.request.urlopen(peticion, timeout=5)
        except urllib.error.HTTPError as error:
            respuesta = error
        with respuesta:
            texto = respuesta.read().decode("utf-8")
            es_json = respuesta.headers.get("Content-Type", "").startswith("application/json")
            return respuesta.status, (json.loads(texto) if es_json else texto), respuesta.headers

    def test_partida_por_http(self):
        self.assertEqual(self.pedir("POST", "/login", {"nombre": "ana"})[0], 201)
        self.assertEqual(self.pedir("POST", "/login", {"nombre": "luis"})[0], 201)
        self.assertEqual(self.pedir("POST", "/login", {"nombre": "ana"})[0], 200)

        codigo, juego, cabeceras = self.pedir("POST", "/juego", {"nombre": "ana", "numero": "4271"})
        self.assertEqual(codigo, 201)
        self.assertEqual(cabeceras["Location"], "/juego/1")
        self.assertEqual(juego["estado"], "por_iniciar")

        codigo, lista, _ = self.pedir("GET", "/juego?estado=por_iniciar")
        self.assertEqual((codigo, [j["id"] for j in lista]), (200, [1]))

        codigo, juego, _ = self.pedir("PUT", "/juego/1", {"nombre": "luis", "numero": "0593"})
        self.assertEqual((codigo, juego["estado"]), (200, "en_juego"))
        primero = juego["turno"]
        segundo = "luis" if primero == "ana" else "ana"
        secreto = {"ana": "4271", "luis": "0593"}

        codigo, error, _ = self.pedir("POST", "/juego/1/jugar", {"nombre": segundo, "numero": "1234"})
        self.assertEqual(codigo, 409)
        self.assertIn("No es tu turno", error["error"])

        codigo, respuesta, _ = self.pedir("POST", "/juego/1/jugar", {"nombre": primero, "numero": "1234"})
        self.assertEqual(codigo, 200)
        self.assertEqual((respuesta["fijas"], respuesta["picas"]), contar(secreto[segundo], "1234"))

        codigo, respuesta, _ = self.pedir("POST", "/juego/1/jugar",
                                          {"nombre": segundo, "numero": secreto[primero]})
        self.assertEqual((codigo, respuesta["gano"]), (200, True))

        codigo, juego, _ = self.pedir("GET", "/juego/1")
        self.assertEqual((codigo, juego["estado"], juego["ganador"]), (200, "terminado", segundo))

        codigo, lista, _ = self.pedir("GET", "/juego/")
        self.assertEqual((codigo, lista[0]["ganador"]), (200, segundo))

    def test_errores_http(self):
        self.pedir("POST", "/login", {"nombre": "ana"})
        casos = [
            (400, "POST", "/login", None, b"esto no es json"),
            (400, "POST", "/login", None, b"[1, 2]"),
            (400, "POST", "/login", {}, None),
            (400, "POST", "/juego", {"nombre": "ana", "numero": "12a4"}, None),
            (400, "POST", "/juego", {"nombre": "ana"}, None),
            (400, "GET", "/juego?estado=raro", None, None),
            (401, "POST", "/juego", {"nombre": "nadie", "numero": "1234"}, None),
            (404, "GET", "/juego/7", None, None),
            (404, "GET", "/juego/abc", None, None),
            (404, "GET", "/otra", None, None),
            (405, "DELETE", "/juego/1", None, None),
            (405, "GET", "/login", None, None),
            (413, "POST", "/login", None, b"x" * 20_000),
        ]
        for esperado, metodo, ruta, cuerpo, crudo in casos:
            with self.subTest(metodo=metodo, ruta=ruta, cuerpo=cuerpo or crudo):
                codigo, respuesta, cabeceras = self.pedir(metodo, ruta, cuerpo, crudo)
                self.assertEqual(codigo, esperado)
                self.assertIn("error", respuesta)
                if codigo == 405:
                    self.assertTrue(cabeceras["Allow"])

    def test_front_y_salud(self):
        codigo, html, cabeceras = self.pedir("GET", "/")
        self.assertEqual(codigo, 200)
        self.assertTrue(cabeceras["Content-Type"].startswith("text/html"))
        self.assertIn("Picas y Fijas", html)
        codigo, salud, _ = self.pedir("GET", "/healthz")
        self.assertEqual((codigo, salud["estado"]), (200, "ok"))


if __name__ == "__main__":
    unittest.main()
