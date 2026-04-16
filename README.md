# Importador ONVIO – MVP web

Prototipo web para Ortega & Asociados.

## Qué resuelve
- **Ventas Excel → PRE002 ONVIO**
- **F931 PDF o carga manual → asiento ONVIO**
- **Resumen Banco Macro PDF → movimientos clasificados + asiento resumido**

## Cómo correrlo en local
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Qué necesitás subir
### Ventas
- Excel o CSV con columnas similares a: `FECHA, TIPO_COMPR, TIPO_FACTU, CLIENTE, CUIT, IMPORTE_NE, IMPORTE_IV, IMPORTE_TO, NUMERO`

### F931
- PDF con texto legible, o bien completar los importes manualmente en pantalla.

### Banco Macro
- PDF del resumen.

## Qué entrega
### Ventas
- Excel listo para importación PRE002.

### F931
- Excel de asiento de importación ONVIO.

### Banco
- Excel con dos hojas:
  - `MOVIMIENTOS`
  - `ASIENTO`

## Alcance del MVP
- No incluye OCR avanzado.
- No incluye login ni base de datos.
- No incluye automatización por mail.
- Las cuentas contables se editan desde la barra lateral.

## Próximo sprint recomendado
1. Aprender reglas por cliente.
2. Mejorar parser Banco Macro.
3. Incorporar PDF escaneados con OCR.
4. Agregar compras, clientes y proveedores.
