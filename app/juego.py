import random
import threading

DIGITOS = 4
MAX_NOMBRE = 20

POR_INICIAR = "por_iniciar"
EN_JUEGO = "en_juego"
TERMINADO = "terminado"
ESTADOS = (POR_INICIAR, EN_JUEGO, TERMINADO)


class ErrorJuego(Exception):
    def __init__(self, codigo, mensaje):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


def validar_nombre(valor):
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorJuego(400, "Falta el campo 'nombre' (texto no vacío).")
    nombre = " ".join(valor.split())
    if len(nombre) > MAX_NOMBRE:
        raise ErrorJuego(400, f"El nombre no puede tener más de {MAX_NOMBRE} caracteres.")
    if not nombre.isprintable():
        raise ErrorJuego(400, "El nombre tiene caracteres no permitidos.")
    return nombre


def validar_numero(valor):
    if valor is None:
        raise ErrorJuego(400, "Falta el campo 'numero'.")
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        raise ErrorJuego(400, 'El número debe enviarse como texto, por ejemplo "0123".')
    texto = str(valor).strip()
    if not texto:
        raise ErrorJuego(400, "El número no puede estar vacío.")
    if any(caracter not in "0123456789" for caracter in texto):
        raise ErrorJuego(400, "El número solo puede tener dígitos del 0 al 9, sin letras, espacios ni símbolos.")
    if len(texto) != DIGITOS:
        raise ErrorJuego(400, f"El número debe tener exactamente {DIGITOS} dígitos y tiene {len(texto)}.")
    if len(set(texto)) != DIGITOS:
        raise ErrorJuego(400, "El número no puede tener dígitos repetidos.")
    return texto


def contar(secreto, intento):
    fijas = sum(1 for s, i in zip(secreto, intento) if s == i)
    en_comun = len(set(secreto) & set(intento))
    return fijas, en_comun - fijas


def describir(fijas, picas):
    texto_fijas = "1 fija" if fijas == 1 else f"{fijas} fijas"
    texto_picas = "1 pica" if picas == 1 else f"{picas} picas"
    return f"{texto_fijas} y {texto_picas}"


class Partidas:

    def __init__(self):
        self._candado = threading.Lock()
        self._jugadores = set()
        self._juegos = {}
        self._siguiente_id = 1


    def registrar(self, nombre):
        nombre = validar_nombre(nombre)
        with self._candado:
            es_nuevo = nombre not in self._jugadores
            self._jugadores.add(nombre)
        return nombre, es_nuevo

    def crear(self, nombre, numero):
        nombre = validar_nombre(nombre)
        with self._candado:
            self._exigir_registrado(nombre)
            numero = validar_numero(numero)
            juego = {
                "id": self._siguiente_id,
                "estado": POR_INICIAR,
                "creador": nombre,
                "jugadores": [nombre],
                "numeros": {nombre: numero},
                "turno": None,
                "ganador": None,
                "intentos": [],
            }
            self._juegos[juego["id"]] = juego
            self._siguiente_id += 1
            return self._vista(juego)

    def unirse(self, id_juego, nombre, numero):
        nombre = validar_nombre(nombre)
        with self._candado:
            self._exigir_registrado(nombre)
            juego = self._buscar(id_juego)
            numero = validar_numero(numero)
            if nombre in juego["jugadores"]:
                raise ErrorJuego(409, "Ya estás en este juego.")
            if juego["estado"] != POR_INICIAR:
                raise ErrorJuego(409, "Este juego ya tiene sus dos jugadores.")
            juego["jugadores"].append(nombre)
            juego["numeros"][nombre] = numero
            juego["estado"] = EN_JUEGO
            juego["turno"] = random.choice(juego["jugadores"])
            return self._vista(juego)

    def jugar(self, id_juego, nombre, numero):
        nombre = validar_nombre(nombre)
        with self._candado:
            self._exigir_registrado(nombre)
            juego = self._buscar(id_juego)
            if nombre not in juego["jugadores"]:
                raise ErrorJuego(403, "No participas en este juego.")
            intento = validar_numero(numero)
            if juego["estado"] == POR_INICIAR:
                raise ErrorJuego(409, "El juego no ha iniciado: falta el segundo jugador.")
            if juego["estado"] == TERMINADO:
                raise ErrorJuego(409, f"El juego ya terminó: ganó {juego['ganador']}.")
            if juego["turno"] != nombre:
                raise ErrorJuego(409, f"No es tu turno: le toca a {juego['turno']}.")

            rival = next(j for j in juego["jugadores"] if j != nombre)
            fijas, picas = contar(juego["numeros"][rival], intento)
            juego["intentos"].append(
                {"jugador": nombre, "numero": intento, "fijas": fijas, "picas": picas}
            )

            gano = fijas == DIGITOS
            if gano:
                juego["estado"] = TERMINADO
                juego["ganador"] = nombre
                juego["turno"] = None
            else:
                juego["turno"] = rival

            return {
                "jugador": nombre,
                "numero": intento,
                "fijas": fijas,
                "picas": picas,
                "gano": gano,
                "mensaje": "Adivinaste el número: ganaste." if gano else describir(fijas, picas),
                "estado": juego["estado"],
                "turno": juego["turno"],
            }

    def ver(self, id_juego):
        with self._candado:
            return self._vista(self._buscar(id_juego))

    def listar(self, estado=None):
        if estado is not None and estado not in ESTADOS:
            raise ErrorJuego(400, "El filtro 'estado' debe ser uno de: " + ", ".join(ESTADOS) + ".")
        with self._candado:
            return [
                self._vista(juego, detalle=False)
                for juego in self._juegos.values()
                if estado in (None, juego["estado"])
            ]


    def _exigir_registrado(self, nombre):
        if nombre not in self._jugadores:
            raise ErrorJuego(401, f"El jugador '{nombre}' no está registrado: primero haz POST /login.")

    def _buscar(self, id_juego):
        if id_juego not in self._juegos:
            raise ErrorJuego(404, f"No existe el juego {id_juego}.")
        return self._juegos[id_juego]

    def _vista(self, juego, detalle=True):
        vista = {
            "id": juego["id"],
            "estado": juego["estado"],
            "creador": juego["creador"],
            "jugadores": list(juego["jugadores"]),
            "turno": juego["turno"],
            "ganador": juego["ganador"],
        }
        if detalle:
            vista["intentos"] = [dict(intento) for intento in juego["intentos"]]
            if juego["estado"] == TERMINADO:
                vista["numeros"] = dict(juego["numeros"])
        return vista
