# Partner Data Hygiene

Normaliza teléfonos y correos de los contactos al guardarlos, sin intervención
manual y sin llamar a ningún modelo de IA: es una transformación determinista.

## Qué hace

- `phone` y `mobile`: deja solo dígitos y un `+` inicial, convierte `0034...` en
  `+34...` y guarda el número en formato internacional legible reutilizando la
  normalización de `phone_validation`, que conoce los planes por país.
- `email`: recorta espacios y pasa a minúsculas.
- Un número con menos de seis dígitos (una extensión, un identificador interno)
  no se toca. Un correo que no encaja en el patrón no se modifica ni se borra:
  se deja como llegó y se anota un aviso en el log.

Se aplica en `create` y en `write`, así que cubre tanto la creación manual como
la importación y la API.

## Qué NO hace

- No valida contra servicios externos ni comprueba que el número exista.
- No inventa datos que faltan. Para completar un contacto a partir de su nombre
  o su web hace falta otro módulo (el puente de IA, en asíncrono).
