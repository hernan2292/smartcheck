/**
 * OWASP Smart Contract Security Top 10 (2025) — copia estatica.
 *
 * Alimenta el modo "explorar" (UC3) sin pegarle a la API: alguien puede leer
 * la taxonomia completa aunque el backend este caido.
 *
 * ESPEJO de app/taxonomy.py en el branch `back`. Si cambia alla, cambia aca.
 */

export const OWASP_SCS_VERSION = "2025";

export const CATEGORIES = [
  {
    id: "SC01",
    name: "Fallas de control de acceso",
    name_en: "Access Control Vulnerabilities",
    summary:
      "Funciones que deberian estar restringidas a un owner o rol quedan abiertas a cualquiera.",
    plain:
      "Alguien que no sos vos puede llamar funciones criticas: retirar fondos, cambiar el owner, pausar el contrato o actualizar la implementacion. Es la causa numero uno de fondos robados.",
    fix: "Poné un modifier de autorizacion (onlyOwner, AccessControl de OpenZeppelin) en toda funcion que mueva fondos o cambie estado critico. Nunca uses tx.origin para autorizar: usa msg.sender.",
  },
  {
    id: "SC02",
    name: "Manipulacion de oraculos de precio",
    name_en: "Price Oracle Manipulation",
    summary: "El contrato confia en una fuente de precio que se puede mover a voluntad.",
    plain:
      "Si tomas el precio del reserve de un pool de DEX o de block.timestamp, un atacante puede moverlo en la misma transaccion y hacer que tu contrato calcule mal.",
    fix: "Usa un oraculo con TWAP o Chainlink price feeds, validá la antiguedad del dato (updatedAt) y nunca uses el spot price de un solo pool como verdad.",
  },
  {
    id: "SC03",
    name: "Errores de logica",
    name_en: "Logic Errors",
    summary: "La implementacion no hace lo que la intencion del negocio dice.",
    plain:
      "Comparaciones estrictas que nunca se cumplen, condiciones siempre true o false, variables sin inicializar, estado que se sobreescribe. El contrato compila y deploya pero se comporta distinto a lo que esperabas.",
    fix: "Cubrí los invariantes con tests (Foundry fuzzing ayuda mucho aca) y revisá manualmente toda comparacion de igualdad sobre balances o timestamps.",
  },
  {
    id: "SC04",
    name: "Falta de validacion de entrada",
    name_en: "Lack of Input Validation",
    summary: "Parametros que entran sin chequear rango, cero o pertenencia.",
    plain:
      "Direcciones en cero, montos en cero, arrays de largo controlado por el usuario. Sin validar, terminas mandando fondos al vacio o dejando que alguien infle una estructura hasta romperla.",
    fix: "require() al inicio de cada funcion publica: address != address(0), amount > 0, longitudes de array acotadas, e indices dentro de rango.",
  },
  {
    id: "SC05",
    name: "Reentrancy",
    name_en: "Reentrancy Attacks",
    summary:
      "Una llamada externa vuelve a entrar al contrato antes de que cierre su estado.",
    plain:
      "Mandas ETH o llamas a un contrato externo ANTES de actualizar tus balances. Ese contrato te vuelve a llamar y repite el retiro con el balance viejo. Asi se vacio The DAO.",
    fix: "Patron checks-effects-interactions: validá, actualizá tu estado, y recien despues hacé la llamada externa. Sumá ReentrancyGuard de OpenZeppelin en las funciones que mueven valor.",
  },
  {
    id: "SC06",
    name: "Llamadas externas sin verificar",
    name_en: "Unchecked External Calls",
    summary: "El valor de retorno de una llamada externa se ignora.",
    plain:
      "call(), send() y algunos transfer() de ERC20 no revierten cuando fallan: devuelven false. Si no chequeas ese false, tu contrato sigue como si la transferencia hubiera salido bien.",
    fix: "Chequeá el bool de retorno de todo low-level call, o usá SafeERC20 de OpenZeppelin que revierte por vos.",
  },
  {
    id: "SC07",
    name: "Ataques con flash loans",
    name_en: "Flash Loan Attacks",
    summary: "Logica que asume que nadie puede tener mucho capital por un instante.",
    plain:
      "Un atacante pide prestados millones sin colateral, los usa para torcer una votacion o un precio dentro de una sola transaccion, y devuelve el prestamo. Todo atomico, sin riesgo para el.",
    fix: "No tomes decisiones criticas con datos de una sola transaccion: usá snapshots de balance por bloque, TWAP, o timelocks en governance.",
    static_analysis_blind: true,
  },
  {
    id: "SC08",
    name: "Overflow y underflow de enteros",
    name_en: "Integer Overflow and Underflow",
    summary: "Aritmetica que se desborda silenciosamente.",
    plain:
      "En Solidity < 0.8.0 restar 1 a un uint en cero te devuelve el numero mas grande posible, sin revertir. Tambien dividir antes de multiplicar te come precision.",
    fix: "Compilá con Solidity >= 0.8.0 (trae checked arithmetic nativo). Si estas en una version vieja, usá SafeMath. Multiplicá siempre antes de dividir.",
  },
  {
    id: "SC09",
    name: "Aleatoriedad insegura",
    name_en: "Insecure Randomness",
    summary: "Se usa informacion de la blockchain como fuente de azar.",
    plain:
      "block.timestamp, blockhash y block.prevrandao son publicos y en parte influenciables por validadores. Si tu loteria o mint aleatorio depende de eso, se puede predecir.",
    fix: "Usá Chainlink VRF o un esquema commit-reveal. Nunca derives azar de valores del bloque.",
  },
  {
    id: "SC10",
    name: "Denegacion de servicio",
    name_en: "Denial of Service (DoS) Attacks",
    summary: "Alguien puede dejar el contrato inutilizable o inalcanzable por gas.",
    plain:
      "Loops sobre arrays que crecen sin limite, llamadas externas dentro de un for, o ETH que queda encerrado sin funcion de retiro. El contrato se vuelve imposible de usar.",
    fix: "Evitá llamadas externas dentro de loops, usá el patron pull en vez de push para pagos, y acotá el tamaño de toda estructura iterable.",
  },
];
