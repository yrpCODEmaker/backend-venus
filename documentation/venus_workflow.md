# Flujo de Trabajo del Sistema Venus MVP

Este diagrama detalla cómo fluye la información dentro del MVP de la fábrica de muebles Venus. Cubre desde la creación de las entidades base (Clientes, Catálogo, Stock, Imágenes), pasando por el proceso de Facturación (con validaciones de Stock, Gestión de Pagos y Cola de Trabajos), hasta llegar a los tableros Kanban de Producción (Módulo de Trabajos) y Logística (Envíos).

```mermaid
flowchart TD
    classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px;
    classDef db fill:#f0f8ff,stroke:#0066cc,stroke-width:2px;
    classDef process fill:#e6f3ff,stroke:#0066cc,stroke-width:1px;
    classDef decision fill:#fff3e6,stroke:#ff9900,stroke-width:2px;
    classDef kanban fill:#e6ffe6,stroke:#009933,stroke-width:1px;
    classDef error fill:#ffcccc,stroke:#cc0000,stroke-width:2px;

    %% 1. Creación de Entidades Base
    subgraph Fase1 [Fase 1: Configuración Inicial]
        direction TB
        C[Crear Nuevo Cliente\n- Nombre, Apellido\n- Teléfono, Domicilio] --> DB_C[(Tabla: clientes)]:::db
        
        IMG[Subir Imagen Física\n- Genera ID, Guarda path\n- Relación de aspecto] --> DB_IMG[(Tabla: images)]:::db
        
        Cat[Crear Plantilla Genérica en Catálogo\n- Nombre, Tipo, Área, Precio Base] --> DB_Cat[(Tabla: catalogo)]:::db
        DB_IMG -.->|Asigna image_id obligatoria| Cat
        
        Cat -.->|Sirve de base\nHereda: Nombre, Tipo, Área\n(y image_id por defecto)| S[Crear Variantes en Stock\n- Color, Material, Descripción]
        DB_IMG -.->|Opcional: Asigna nueva image_id| S
        
        S --> DB_S[(Tabla: stock)]:::db
    end

    %% 2. Proceso de Facturación y Pagos
    subgraph Fase2 [Fase 2: Creación de Factura y Pagos]
        direction TB
        F1[Iniciar Factura] --> F2{¿Asignar Cliente?}:::decision
        
        F2 -->|Cliente Registrado| F2A[Seleccionar Cliente\nde Base de Datos]
        F2 -->|Venta Rápida| F2B[Factura Rápida:\nIngresar Nombre, Apellido\n(Teléfono opcional)]
        
        F2A --> F3{¿Tipo de Ítem?}:::decision
        F2B --> F3
        
        %% Rama Encargo
        F3 -->|Encargo Personalizado| F4A[Seleccionar Plantilla de Catálogo\ncomo base]
        F4A -->|Item hereda:\nNombre, Tipo, Área\ne imagen genérica| F5A_Foto{¿Subir foto\npersonalizada?}:::decision
        
        F5A_Foto -->|Sí| F5A_Sube[Asignar nueva imagen\nSobrescribe la del catálogo]
        F5A_Foto -->|No| F5A_Mantiene[Mantiene imagen\ndel catálogo]
        
        F5A_Sube --> F5A
        F5A_Mantiene --> F5A
        
        F5A[Ingresar Detalles Obligatorios:\n- Descripción\n- Material, Tela, Color\n- Precio] --> F6A[Item: Encargo\nEstado Inicial: Pendiente]
        
        %% Rama Stock
        F3 -->|Venta de Mostrador| F4B[Seleccionar Item del Stock]
        F4B --> F4C{¿Stock\nDisponible?}:::decision
        F4C -->|No| F4D{¿Convertir\na Encargo?}:::decision
        F4D -->|No| F4E[Cancelar Ítem]:::error
        F4D -->|Sí| F4F[Crear Encargo\nrescatando parámetros\ndesde la RAM]
        F4F --> F6A
        
        F4C -->|Sí| F6B[Item: Stock\nEstado Inicial: Procesado]
        F6B -.->|Asigna stock_id| DB_S
        
        F6A --> F7{¿Requiere Envío\na Domicilio?}:::decision
        F6B --> F7
        
        F7 -->|Sí| F7_A{¿Usar domicilio\ndel cliente?}:::decision
        F7_A -->|Sí, automático| F8A1[Autocompletar Dirección]
        F7_A -->|No, otro lugar\no Venta Rápida| F8A2[Ingresar Dirección Manualmente]
        
        F8A1 --> F8A[Marcar: entrega_domicilio = 1]
        F8A2 --> F8A
        
        F7 -->|No| F8B[Marcar: entrega_domicilio = 0\nRetiro en Tienda]
        
        F8A --> F8C[Asignar Garantía\n(Ej. 1 mes, 6 meses o Null)]
        F8B --> F8C
        
        F8C --> F9_Pago[Registrar Pago Inicial\nCalcula saldo_pendiente]
        
        F9_Pago --> DB_Pagos[(Tabla: pagos)]:::db
        F9_Pago --> F9[Guardar Factura]
        
        F9 --> DB_F[(Tabla: facturas y items)]:::db
        
        F9 --> F10{¿Tiene Encargos o\nlleva Envío a Domicilio?}:::decision
        F10 -->|Sí| F11[Crear fila con factura_id en\ncola_trabajos]
        F11 --> DB_Cola[(Tabla: cola_trabajos)]:::db
        
        F10 -->|Sí, lleva Envío| F12[Crear fila en tabla envios]
        F12 --> DB_Envios[(Tabla: envios)]:::db
    end

    %% 3. Módulo de Trabajos (Producción)
    subgraph Fase3 [Fase 3: Módulo de Trabajos Kanban]
        direction TB
        W1[El Módulo lee facturas\nde cola_trabajos y\nextrae sus ítems pendientes] --> W3[Columna: Pendiente]:::kanban
        
        W3 -->|Operario inicia\nGenera fecha_procesando| W4[Columna: Procesando]:::kanban
        W4 -->|Operario finaliza\nGenera fecha_procesado| W5[Columna: Procesado]:::kanban
        
        W5 --> W6{¿Requiere Envío\na Domicilio?}:::decision
        W6 -->|No| W6A[Pasa directo a\nCompletado]:::kanban
        W6 -->|Sí| W7{¿Factura 100% Procesada\ny Entregada?}:::decision
        
        W6A --> W7
        W7 -->|Sí| W8[Eliminar fila de\ncola_trabajos]
    end

    %% 4. Módulo de Envíos
    subgraph Fase4 [Fase 4: Despacho y Envíos]
        direction TB
        E1[El Módulo lee tabla envios] --> E4[Tablero de Enrutamiento]
        
        E4 --> E5[Pendiente de Envío]:::kanban
        E5 -->|Asignar transporte\nGenera fecha_enviado| E6[En Ruta]:::kanban
        E6 -->|Cliente recibe\nGenera fecha_entregado\n(Dispara update_at en factura)| E7[Entregado]:::kanban
        
        E7 --> E8{¿Factura 100% Procesada\ne Ítems Completados?}:::decision
        E8 -->|Sí| E9[Eliminar fila de\ncola_trabajos]
    end

    %% Conexiones de la Cola
    DB_Cola -.-> W1
    DB_Envios -.-> E1
    W8 -.-> DB_Cola
    E9 -.-> DB_Cola
```

### Detalles del Flujo:

1. **Gestión de Imágenes:** Existe una tabla `images` que guarda la ubicación de los archivos físicos en disco y su relación de aspecto. A cada imagen se le asigna un ID único.
2. **Catálogo como Plantilla Genérica:** Al crearse un catálogo, este recibe obligatoriamente un `image_id`. El catálogo representa la "idea" base (ej: Nombre: Sofá 3 Plazas, Tipo: Sofá, Área: Ebanistería), definiendo un precio base.
3. **Stock como Variante Derivada:** El "Stock" de mostrador se crea usando un catálogo como molde. Hereda Nombre, Tipo, Área e `image_id` por defecto. El usuario especifica Color, Material y Descripción.
4. **Inicio de Factura (Rápida vs Registrada):** Al iniciar una factura, se puede elegir a un cliente de la BD o hacer una **"Factura Rápida"**, requiriendo el Nombre y Apellido (dejando el Teléfono como opcional). Esto se refleja en la base de datos marcando la columna `facturacion_rapida` (INTEGER) y guardando al cliente como JSON.
5. **Diferenciación de Ítems (Stock vs Encargo):**
   - **Encargo:** Usa la imagen genérica de la plantilla del catálogo por defecto, **pero si el usuario sube una foto específica para el encargo, esta sobrescribe a la imagen genérica**. El ítem hereda explícitamente el **Nombre, Tipo y Área** del catálogo. Obliga a rellenar detalles (Material, Tela, Color, Precio y Descripción). Estado inicial `Pendiente`.
   - **Stock:** Al agregarlo, el sistema **verifica que quede stock disponible**. Si no hay (por ejemplo, porque el elemento físico acaba de ser vendido o borrado de la base de datos), el sistema pregunta si se desea **convertir a Encargo**. Si el usuario acepta, los parámetros que el ítem tenía son rescatados desde la memoria RAM de la aplicación y se transforma en un ítem de tipo Encargo con estado `Pendiente`. Si el usuario rechaza, se cancela la operación. Si hay stock disponible, se le asigna su `stock_id` e inicia como `Procesado`.
6. **Estructura de la Tabla `facturas` y Pagos:**
   - `id`: Identificador único de la factura.
   - `cliente_id` y `cliente` (JSON si fue rápida).
   - `fecha`, `total`, `monto_pagado`, `saldo_pendiente`.
   - `entrega_domicilio`, `direccion_entrega`, `status_entrega`.
   - `garantia_hasta`, `update_at` (desde donde arranca la garantía si se envió), `venc_garantia`.
   - `items_id`: Lista de identificadores que conectan con los productos.
   - Existe una tabla secundaria `pagos` (`id`, `factura_id`, `monto`, `fecha`, `nota`) que registra el historial de abonos para una factura.
7. **Estructura de la Tabla `cola_trabajos`:**
   - Cada factura activa tiene **su propia fila** en esta tabla (`id`, `factura_id`, `created_at`).
   - Cuando una factura cumple al menos una de estas condiciones: **(A) Contiene ítems de Encargo** o **(B) Tiene Envío a Domicilio**, se inserta una nueva fila con su ID.
   - Si fue una venta solo de Stock que el cliente retiró en tienda (ni encargo ni envío), **no entra** a la cola.
   - Los módulos de Trabajo y Envío leen activamente de esta tabla y de la tabla `envios` para saber qué facturas procesar.
   - Cuando una factura en la cola cumple la doble condición de tener: "Todos sus ítems en estado Procesado/Completado" Y "Estado de entrega Entregado (si aplicaba)", **su fila se elimina** por completo de la tabla.
8. **Estructura de la Tabla `items`:**
   - `id`, `factura_id`, `stock_id`, `catalogo_id`, `image_id`, `nombre` (heredado), `cantidad`, `tipo` (Encargo/Stock), `subtotal`.
   - `color`, `material`, `descripcion`, `area`, `tipo_mueble`.
   - `status` (Pendiente, Procesando, Procesado, Completado). El sistema aplica un "bypass" automático de Procesado a Completado si el ítem no requiere envío a domicilio.
   - Trazabilidad en Producción: `created_at`, `fecha_procesando` y `fecha_procesado`.
9. **Estructura de la Tabla `envios`:**
   - `id`, `factura_id`, `estado` (Pendiente de Envío, En Ruta, Entregado), `direccion_entrega`.
   - `fecha_programada`, `fecha_enviado`, `fecha_entregado`, `notas`. Esta tabla gestiona el ciclo de vida logístico independientemente del ciclo de producción.
