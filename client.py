# Importamos Enum para poder crear un tipo con valores fijos, como OK, ERROR, etc.
from enum import Enum

# Importamos argparse para leer los argumentos que se pasan al ejecutar el programa.
import argparse

# Importamos socket para poder hacer conexiones de red entre cliente y servidor.
import socket

# Importamos threading para poder trabajar con hilos.
# En este cliente hace falta un hilo principal y otro para escuchar mensajes.
import threading

# Importamos sys para acceder a sys.argv, que son los argumentos de la línea de comandos.
import sys


# Definimos la clase principal del cliente.
class client:

    # ******************** TYPES *********************
    # Aquí definimos un pequeño conjunto de códigos de retorno.
    # Nos sirve para devolver resultados más claros desde las funciones.
    class RC(Enum):
        # Todo ha ido bien.
        OK = 0

        # Ha habido un error general.
        ERROR = 1

        # Ha habido un error relacionado con el usuario.
        USER_ERROR = 2

    # ****************** ATTRIBUTES ******************

    # Aquí guardaremos la IP o nombre del servidor al que nos conectamos.
    _server = None

    # Aquí guardaremos el puerto del servidor.
    _port = -1

    # Aquí guardamos qué usuario está conectado ahora mismo en este cliente.
    _current_user = None

    # Este socket será el que use el cliente para escuchar mensajes que le mande el servidor.
    _listener_socket = None

    # Aquí guardaremos el hilo que se queda escuchando mensajes entrantes.
    _listener_thread = None

    # Este evento sirve para decirle al hilo de escucha cuándo debe parar.
    _listener_stop_event = threading.Event()

    # Este candado sirve para que no se mezclen mensajes en pantalla
    # si imprimen a la vez el hilo principal y el hilo receptor.
    _print_lock = threading.Lock()

    # ******************** INTERNAL UTILS *********************

    # Método auxiliar para imprimir de forma segura.
    @staticmethod
    def _safe_print(message):
        # Cogemos el candado antes de imprimir.
        # Así evitamos que dos hilos escriban a la vez en la consola.
        with client._print_lock:
            # Imprimimos el mensaje y forzamos el vaciado con flush=True.
            print(message, flush=True)

    # Método auxiliar para abrir una conexión TCP con el servidor.
    @staticmethod
    def _connect_to_server():
        # Creamos un socket IPv4 de tipo TCP.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Nos conectamos al servidor usando la IP y el puerto guardados en la clase.
        sock.connect((client._server, client._port))

        # Devolvemos el socket ya conectado.
        return sock

    # Método auxiliar para enviar una cadena siguiendo el protocolo.
    @staticmethod
    def _send_string(sock, value):
        # Si el valor es None, lo convertimos en cadena vacía.
        if value is None:
            value = ""

        # Si el valor no es string, lo convertimos a string.
        # Esto viene bien, por ejemplo, con los puertos o con otros números.
        if not isinstance(value, str):
            value = str(value)

        # Enviamos la cadena en UTF-8 y añadimos '\0' al final,
        # porque el protocolo dice que las cadenas terminan con byte nulo.
        sock.sendall(value.encode("utf-8") + b"\0")

    # Método auxiliar para recibir exactamente un número concreto de bytes.
    @staticmethod
    def _recv_exact(sock, size):
        # Creamos un bytearray vacío para ir acumulando los datos.
        data = bytearray()

        # Seguimos recibiendo hasta tener justo la cantidad pedida.
        while len(data) < size:
            # Pedimos lo que todavía falta.
            chunk = sock.recv(size - len(data))

            # Si no llega nada, significa que el socket se ha cerrado antes de tiempo.
            if not chunk:
                raise ConnectionError("Socket closed unexpectedly")

            # Añadimos al buffer lo que acabamos de recibir.
            data.extend(chunk)

        # Devolvemos los datos convertidos a bytes normales.
        return bytes(data)

    # Método auxiliar para recibir una cadena terminada en '\0'.
    @staticmethod
    def _recv_string(sock, max_size=65536):
        # Creamos un bytearray vacío para ir guardando la cadena.
        data = bytearray()

        # Vamos leyendo byte a byte hasta encontrar el byte nulo.
        while True:
            # Recibimos un solo byte.
            chunk = sock.recv(1)

            # Si no llega nada, el socket se ha cerrado cuando no debía.
            if not chunk:
                raise ConnectionError("Socket closed unexpectedly")

            # Si el byte recibido es '\0', significa que la cadena ha terminado.
            if chunk == b"\0":
                # Decodificamos la cadena a texto y la devolvemos.
                return data.decode("utf-8", errors="replace")

            # Si no era el byte final, lo añadimos al buffer.
            data.extend(chunk)

            # Por seguridad, comprobamos que la cadena no se haga gigantesca.
            if len(data) > max_size:
                raise ValueError("Received string is too large")

    # Método auxiliar para recibir el código de retorno del servidor.
    @staticmethod
    def _recv_code(sock):
        # Leemos exactamente 1 byte y nos quedamos con su valor numérico.
        return client._recv_exact(sock, 1)[0]

    # Método auxiliar para comprobar si el mensaje cabe en el protocolo.
    @staticmethod
    def _message_fits_protocol(message):
        # El enunciado dice que el mensaje, contando también el '\0', debe ocupar como mucho 256 bytes.
        return len(message.encode("utf-8") + b"\0") <= 256

    # Este método es el que ejecuta el hilo de escucha.
    @staticmethod
    def _listener_loop():
        # El hilo seguirá funcionando mientras no le digamos que se pare.
        while not client._listener_stop_event.is_set():
            try:
                # Esperamos a que alguien se conecte al socket de escucha del cliente.
                conn, _ = client._listener_socket.accept()

            # Si salta timeout, no pasa nada: seguimos el bucle y volvemos a esperar.
            except socket.timeout:
                continue

            # Si hay un error con el socket...
            except OSError:
                # ...y además nos han pedido parar, salimos del bucle.
                if client._listener_stop_event.is_set():
                    break

                # Si no era por parar, seguimos esperando nuevas conexiones.
                continue

            # with conn asegura que la conexión se cierre sola al terminar este bloque.
            with conn:
                try:
                    # Le ponemos timeout a esta conexión concreta para no quedarnos bloqueados.
                    conn.settimeout(3.0)

                    # Leemos la operación que nos manda el servidor.
                    operation = client._recv_string(conn)

                    # Si la operación es un mensaje normal de otro usuario...
                    if operation == "SEND MESSAGE":
                        # Leemos el nombre del remitente.
                        sender = client._recv_string(conn)

                        # Leemos el identificador del mensaje.
                        message_id = client._recv_string(conn)

                        # Leemos el contenido del mensaje.
                        message = client._recv_string(conn, max_size=4096)

                        # Mostramos la cabecera con el formato que pide el enunciado.
                        client._safe_print(f"s> MESSAGE {message_id} FROM {sender}")

                        # Mostramos el texto del mensaje.
                        client._safe_print(message)

                        # Mostramos END para cerrar la visualización del mensaje.
                        client._safe_print("END")

                    # Si la operación es un acuse de recibo de entrega...
                    elif operation == "SEND MESS ACK":
                        # Leemos el identificador del mensaje entregado.
                        message_id = client._recv_string(conn)

                        # Mostramos por pantalla que ese mensaje se ha entregado correctamente.
                        client._safe_print(f"c> SEND MESSAGE {message_id} OK")

                # Si llega una notificación mal formada o da cualquier error...
                except Exception:
                    # ...la ignoramos para que el hilo siga vivo y pueda seguir recibiendo lo siguiente.
                    continue

    # Método para arrancar el hilo de escucha del cliente.
    @staticmethod
    def _start_listener():
        # Si ya existe un hilo de escucha y sigue vivo, no lo volvemos a crear.
        if client._listener_thread is not None and client._listener_thread.is_alive():
            # En ese caso devolvemos el puerto en el que ya está escuchando.
            return client._listener_socket.getsockname()[1]

        # Creamos un nuevo socket TCP IPv4 para escuchar conexiones del servidor.
        listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # Permitimos reutilizar la dirección si hiciera falta.
        listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Lo enlazamos a "" y puerto 0.
        # Eso significa: escucha en cualquier interfaz local y deja que el sistema elija un puerto libre.
        listen_socket.bind(("", 0))

        # Ponemos el socket en modo escucha.
        listen_socket.listen()

        # Le ponemos timeout para que accept no se quede bloqueado para siempre.
        listen_socket.settimeout(0.5)

        # Guardamos el socket en el atributo de la clase.
        client._listener_socket = listen_socket

        # Reiniciamos el evento de parada.
        client._listener_stop_event = threading.Event()

        # Creamos el hilo que ejecutará el método _listener_loop.
        # daemon=True hace que no bloquee el cierre del programa.
        client._listener_thread = threading.Thread(target=client._listener_loop, daemon=True)

        # Arrancamos el hilo.
        client._listener_thread.start()

        # Devolvemos el puerto que el sistema ha asignado al socket.
        return listen_socket.getsockname()[1]

    # Método para detener el hilo y el socket de escucha.
    @staticmethod
    def _stop_listener():
        # Marcamos el evento para avisar al hilo de que debe parar.
        client._listener_stop_event.set()

        # Si existe el socket de escucha...
        if client._listener_socket is not None:
            try:
                # ...intentamos cerrarlo.
                client._listener_socket.close()
            except OSError:
                # Si da error al cerrar, no pasa nada grave.
                pass

        # Si existe el hilo, sigue vivo y además no somos nosotros mismos ese hilo...
        if (
            client._listener_thread is not None
            and client._listener_thread.is_alive()
            and threading.current_thread() is not client._listener_thread
        ):
            # ...esperamos un poco a que termine.
            client._listener_thread.join(timeout=1.0)

        # Dejamos estas referencias a None porque ya no hay escucha activa.
        client._listener_socket = None
        client._listener_thread = None

    # Método auxiliar para hacer peticiones sencillas al servidor.
    @staticmethod
    def _perform_simple_request(operation, *fields):
        # Abrimos una conexión al servidor.
        with client._connect_to_server() as sock:
            # Enviamos primero el nombre de la operación.
            client._send_string(sock, operation)

            # Enviamos después todos los campos adicionales que nos hayan pasado.
            for field in fields:
                client._send_string(sock, field)

            # Recibimos el código de respuesta y devolvemos tanto el código como el socket.
            return client._recv_code(sock), sock

    # ******************** METHODS *******************

    # Método para registrar un usuario.
    @staticmethod
    def register(user):
        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación REGISTER.
                client._send_string(sock, "REGISTER")

                # Enviamos el nombre del usuario que queremos registrar.
                client._send_string(sock, user)

                # Recibimos el código de respuesta del servidor.
                code = client._recv_code(sock)

        # Si ocurre cualquier problema de conexión o protocolo...
        except Exception:
            # ...mostramos fallo.
            client._safe_print("c> REGISTER FAIL")

            # Y devolvemos código de error general.
            return client.RC.ERROR

        # Si el servidor ha respondido 0, todo ha ido bien.
        if code == 0:
            client._safe_print("c> REGISTER OK")
            return client.RC.OK

        # Si responde 1, el nombre ya estaba en uso.
        if code == 1:
            client._safe_print("c> USERNAME IN USE")
            return client.RC.USER_ERROR

        # Cualquier otro caso lo tratamos como error.
        client._safe_print("c> REGISTER FAIL")
        return client.RC.ERROR

    # Método para borrar un usuario del sistema.
    @staticmethod
    def unregister(user):
        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación UNREGISTER.
                client._send_string(sock, "UNREGISTER")

                # Enviamos el nombre del usuario que queremos borrar.
                client._send_string(sock, user)

                # Leemos el código que devuelve el servidor.
                code = client._recv_code(sock)

        # Si algo falla...
        except Exception:
            # ...lo indicamos por pantalla.
            client._safe_print("c> UNREGISTER FAIL")

            # Y devolvemos error general.
            return client.RC.ERROR

        # Si ha ido bien...
        if code == 0:
            # ...y justo ese era el usuario actualmente conectado en este cliente...
            if client._current_user == user:
                # ...paramos el hilo de escucha...
                client._stop_listener()

                # ...y borramos el usuario actual.
                client._current_user = None

            # Mostramos éxito.
            client._safe_print("c> UNREGISTER OK")

            # Devolvemos OK.
            return client.RC.OK

        # Si el servidor responde 1, el usuario no existía.
        if code == 1:
            client._safe_print("c> USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        # Cualquier otro caso es error.
        client._safe_print("c> UNREGISTER FAIL")
        return client.RC.ERROR

    # Método para conectar un usuario al sistema.
    @staticmethod
    def connect(user):
        # Si ya hay un usuario conectado en este cliente, no permitimos otro.
        if client._current_user is not None:
            client._safe_print("c> USER ALREADY CONNECTED")
            return client.RC.USER_ERROR

        try:
            # Arrancamos el hilo de escucha antes de avisar al servidor,
            # porque el servidor podría intentar mandar mensajes en cuanto conectemos.
            listen_port = client._start_listener()

        # Si no se puede arrancar la escucha, fallamos.
        except Exception:
            client._safe_print("c> CONNECT FAIL")
            return client.RC.ERROR

        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación CONNECT.
                client._send_string(sock, "CONNECT")

                # Enviamos el nombre del usuario.
                client._send_string(sock, user)

                # Enviamos el puerto donde este cliente va a escuchar mensajes.
                client._send_string(sock, str(listen_port))

                # Leemos el código de respuesta.
                code = client._recv_code(sock)

        # Si algo falla al hablar con el servidor...
        except Exception:
            # ...paramos la escucha...
            client._stop_listener()

            # ...avisamos del fallo...
            client._safe_print("c> CONNECT FAIL")

            # ...y devolvemos error.
            return client.RC.ERROR

        # Si el código es 0, conexión correcta.
        if code == 0:
            # Guardamos qué usuario está conectado.
            client._current_user = user

            # Mostramos mensaje de éxito.
            client._safe_print("c> CONNECT OK")

            # Devolvemos OK.
            return client.RC.OK

        # Si el código es 1, el usuario no existe.
        if code == 1:
            # Como no se ha conectado de verdad, paramos la escucha.
            client._stop_listener()

            # Mostramos el mensaje que pide el enunciado.
            client._safe_print("c> CONNECT FAIL, USER DOES NOT EXIST")

            # Devolvemos error de usuario.
            return client.RC.USER_ERROR

        # Si el código es 2, ya estaba conectado.
        if code == 2:
            # Cerramos la escucha porque no va a hacer falta.
            client._stop_listener()

            # Mostramos el mensaje correspondiente.
            client._safe_print("c> USER ALREADY CONNECTED")

            # Devolvemos error de usuario.
            return client.RC.USER_ERROR

        # Para cualquier otro código, lo tratamos como error general.
        client._stop_listener()
        client._safe_print("c> CONNECT FAIL")
        return client.RC.ERROR

    # Método para pedir al servidor la lista de usuarios conectados.
    @staticmethod
    def users():
        # Si no hay usuario conectado en este cliente, no tiene sentido pedir la lista.
        if client._current_user is None:
            client._safe_print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR

        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación USERS.
                client._send_string(sock, "USERS")

                # Leemos el código de respuesta.
                code = client._recv_code(sock)

                # Si ha ido bien...
                if code == 0:
                    # ...recibimos primero cuántos usuarios conectados hay.
                    count_text = client._recv_string(sock)

                    # Convertimos ese número de texto a entero.
                    count = int(count_text)

                    # Recibimos exactamente ese número de nombres de usuario.
                    users = [client._recv_string(sock) for _ in range(count)]

                # Si no ha ido bien...
                else:
                    # ...dejamos la lista vacía...
                    users = []

                    # ...y el contador a 0.
                    count = 0

        # Si algo falla en la comunicación...
        except Exception:
            # ...mostramos error general.
            client._safe_print("c> CONNECTED USERS FAIL")
            return client.RC.ERROR

        # Si el código era 0, mostramos la lista.
        if code == 0:
            client._safe_print(f"c> CONNECTED USERS ({count} users connected) OK")

            # Mostramos cada usuario en una línea.
            for user_name in users:
                client._safe_print(user_name)

            # Devolvemos OK.
            return client.RC.OK

        # Si el código es 1, el servidor dice que el usuario no está conectado.
        if code == 1:
            client._safe_print("c> CONNECTED USERS FAIL, USER IS NOT CONNECTED")
            return client.RC.USER_ERROR

        # Cualquier otro caso es error general.
        client._safe_print("c> CONNECTED USERS FAIL")
        return client.RC.ERROR

    # Método para desconectar un usuario.
    @staticmethod
    def disconnect(user):
        # Si el usuario que quieren desconectar no coincide con el que está conectado,
        # devolvemos error directamente.
        if client._current_user != user:
            client._safe_print("c> DISCONNECT FAIL, USER NOT CONNECTED")
            return client.RC.USER_ERROR

        # Inicializamos la variable code.
        code = None

        try:
            # Abrimos conexión al servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación DISCONNECT.
                client._send_string(sock, "DISCONNECT")

                # Enviamos el nombre del usuario.
                client._send_string(sock, user)

                # Recibimos el código de respuesta.
                code = client._recv_code(sock)

        # Si hay error al comunicarnos con el servidor...
        except Exception:
            # ...dejamos code a None.
            code = None

        # Este bloque se ejecuta siempre, haya ido bien o mal.
        finally:
            # El enunciado dice que el hilo de escucha debe pararse incluso si falla la desconexión.
            client._stop_listener()

            # También dejamos de considerar que hay usuario conectado en este cliente.
            client._current_user = None

        # Si el servidor ha respondido 0, todo correcto.
        if code == 0:
            client._safe_print("c> DISCONNECT OK")
            return client.RC.OK

        # Si responde 1, el usuario no existe.
        if code == 1:
            client._safe_print("c> DISCONNECT FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        # Si responde 2, el usuario no estaba conectado.
        if code == 2:
            client._safe_print("c> DISCONNECT FAIL, USER NOT CONNECTED")
            return client.RC.USER_ERROR

        # Cualquier otro caso lo tratamos como error general.
        client._safe_print("c> DISCONNECT FAIL")
        return client.RC.ERROR

    # Método para enviar un mensaje a otro usuario.
    @staticmethod
    def send(user, message):
        # Si no hay ningún usuario conectado en este cliente, no se puede enviar nada.
        if client._current_user is None:
            client._safe_print("c> SEND FAIL")
            return client.RC.ERROR

        # Comprobamos que el mensaje cumple el límite de tamaño del protocolo.
        if not client._message_fits_protocol(message):
            client._safe_print("c> SEND FAIL")
            return client.RC.ERROR

        try:
            # Abrimos conexión con el servidor.
            with client._connect_to_server() as sock:
                # Enviamos la operación SEND.
                client._send_string(sock, "SEND")

                # Enviamos el usuario remitente, que es el usuario conectado en este cliente.
                client._send_string(sock, client._current_user)

                # Enviamos el usuario destinatario.
                client._send_string(sock, user)

                # Enviamos el contenido del mensaje.
                client._send_string(sock, message)

                # Leemos el código de respuesta del servidor.
                code = client._recv_code(sock)

                # Si ha ido bien, el servidor también nos manda el identificador del mensaje.
                message_id = client._recv_string(sock) if code == 0 else None

        # Si algo falla al enviar o recibir...
        except Exception:
            # ...mostramos error.
            client._safe_print("c> SEND FAIL")
            return client.RC.ERROR

        # Si el código es 0, el servidor aceptó el mensaje.
        if code == 0:
            client._safe_print(f"c> SEND OK - MESSAGE {message_id}")
            return client.RC.OK

        # Si el código es 1, el usuario destino no existe.
        if code == 1:
            client._safe_print("c> SEND FAIL, USER DOES NOT EXIST")
            return client.RC.USER_ERROR

        # Cualquier otro caso es error general.
        client._safe_print("c> SEND FAIL")
        return client.RC.ERROR

    # Método para enviar adjuntos.
    # En esta primera parte no se implementa de verdad.
    @staticmethod
    def sendAttach(user, file, message):
        # Mostramos fallo porque esta función pertenece a la parte 2.
        client._safe_print("c> SENDATTACH FAIL")

        # Devolvemos error general.
        return client.RC.ERROR

    # Método que interpreta los comandos escritos por el usuario.
    @staticmethod
    def shell():
        # Bucle principal de la consola.
        while True:
            try:
                # Le pedimos al usuario que escriba un comando.
                command = input("c> ")

                # Partimos la línea por espacios.
                line = command.split(" ")

                # Si hay al menos algo escrito...
                if len(line) > 0:
                    # Convertimos el comando principal a mayúsculas para aceptar register, Register, REGISTER, etc.
                    line[0] = line[0].upper()

                    # Si el comando es REGISTER...
                    if line[0] == "REGISTER":
                        # ...comprobamos que tenga exactamente 2 partes.
                        if len(line) == 2:
                            # Llamamos al método register con el nombre de usuario.
                            client.register(line[1])
                        else:
                            # Si la sintaxis es incorrecta, lo indicamos.
                            print("Syntax error. Usage: REGISTER <userName>")

                    # Si el comando es UNREGISTER...
                    elif line[0] == "UNREGISTER":
                        # ...comprobamos el número de partes.
                        if len(line) == 2:
                            # Llamamos al método unregister.
                            client.unregister(line[1])
                        else:
                            # Si está mal escrito, mostramos ayuda.
                            print("Syntax error. Usage: UNREGISTER <userName>")

                    # Si el comando es CONNECT...
                    elif line[0] == "CONNECT":
                        # ...debe llevar justo un nombre de usuario.
                        if len(line) == 2:
                            # Llamamos al método connect.
                            client.connect(line[1])
                        else:
                            # Si no, mostramos el uso correcto.
                            print("Syntax error. Usage: CONNECT <userName>")

                    # Si el comando es DISCONNECT...
                    elif line[0] == "DISCONNECT":
                        # ...también debe llevar un nombre.
                        if len(line) == 2:
                            # Llamamos al método disconnect.
                            client.disconnect(line[1])
                        else:
                            # Si no, mostramos ayuda.
                            print("Syntax error. Usage: DISCONNECT <userName>")

                    # Si el comando es USERS...
                    elif line[0] == "USERS":
                        # ...no debe llevar nada más.
                        if len(line) == 1:
                            # Pedimos la lista de usuarios conectados.
                            client.users()
                        else:
                            # Si han puesto más cosas, damos el formato correcto.
                            print("Syntax error. Usage: USERS")

                    # Si el comando es SEND...
                    elif line[0] == "SEND":
                        # ...debe haber al menos destinatario y mensaje.
                        if len(line) >= 3:
                            # Reconstruimos el mensaje uniendo todo lo que va desde la tercera palabra hasta el final.
                            message = " ".join(line[2:])

                            # Llamamos al método send.
                            client.send(line[1], message)
                        else:
                            # Si falta algo, mostramos el formato correcto.
                            print("Syntax error. Usage: SEND <userName> <message>")

                    # Si el comando es SENDATTACH...
                    elif line[0] == "SENDATTACH":
                        # ...debe llevar usuario, fichero y mensaje.
                        if len(line) >= 4:
                            # Reconstruimos el mensaje desde la cuarta palabra.
                            message = " ".join(line[3:])

                            # Llamamos al método sendAttach.
                            client.sendAttach(line[1], line[2], message)
                        else:
                            # Si la sintaxis no es correcta, lo indicamos.
                            print("Syntax error. Usage: SENDATTACH <userName> <filename> <message>")

                    # Si el comando es QUIT...
                    elif line[0] == "QUIT":
                        # ...no debe llevar nada más.
                        if len(line) == 1:
                            # Salimos del bucle y terminamos la shell.
                            break
                        else:
                            # Si no, mostramos la forma correcta.
                            print("Syntax error. Use: QUIT")

                    # Si el comando no es ninguno de los conocidos...
                    else:
                        # ...avisamos de que no es válido.
                        print("Error: command " + line[0] + " not valid.")

            # Si el usuario manda EOF, por ejemplo con Ctrl+D, salimos.
            except EOFError:
                break

            # Si el usuario pulsa Ctrl+C, hacemos salto de línea y salimos.
            except KeyboardInterrupt:
                print()
                break

            # Para cualquier otro error inesperado, lo mostramos.
            except Exception as e:
                print("Exception: " + str(e))

    # Método para mostrar cómo se ejecuta el programa.
    @staticmethod
    def usage():
        # Imprimimos la forma correcta de lanzar el cliente.
        print("Usage: python3 client.py -s <server> -p <port>")

    # Método para leer y validar los argumentos de entrada.
    @staticmethod
    def parseArguments(argv):
        # Creamos el parser de argumentos.
        parser = argparse.ArgumentParser()

        # Añadimos el argumento -s para indicar la IP o nombre del servidor.
        parser.add_argument("-s", type=str, required=True, help="Server IP")

        # Añadimos el argumento -p para indicar el puerto del servidor.
        parser.add_argument("-p", type=int, required=True, help="Server Port")

        # Parseamos los argumentos recibidos.
        args = parser.parse_args(argv)

        # Si por alguna razón la IP no está...
        if args.s is None:
            # ...mostramos error.
            parser.error("Usage: python3 client.py -s <server> -p <port>")

            # Y devolvemos False.
            return False

        # Comprobamos que el puerto esté dentro del rango permitido.
        if args.p < 1024 or args.p > 65535:
            # Si no lo está, mostramos el error.
            parser.error("Error: Port must be in the range 1024 <= port <= 65535")

            # Y devolvemos False.
            return False

        # Guardamos la IP del servidor en el atributo de la clase.
        client._server = args.s

        # Guardamos el puerto del servidor en el atributo de la clase.
        client._port = args.p

        # Si todo ha ido bien, devolvemos True.
        return True

    # ******************** MAIN *********************

    # Método principal del programa.
    @staticmethod
    def main(argv):
        # Primero intentamos leer y validar los argumentos.
        if not client.parseArguments(argv):
            # Si no son válidos, mostramos la ayuda.
            client.usage()

            # Y terminamos.
            return

        try:
            # Si los argumentos son correctos, arrancamos la consola del cliente.
            client.shell()

        finally:
            # Al salir, por seguridad, paramos el hilo de escucha si sigue activo.
            client._stop_listener()

            # Y dejamos claro que ya no hay usuario conectado.
            client._current_user = None

        # Mostramos este mensaje al terminar el programa.
        print("+++ FINISHED +++")


# Este bloque hace que el programa solo se ejecute automáticamente
# cuando se lanza este archivo directamente.
if __name__ == "__main__":
    # Llamamos al método main pasándole los argumentos de la línea de comandos,
    # excepto el nombre del propio archivo.
    client.main(sys.argv[1:])