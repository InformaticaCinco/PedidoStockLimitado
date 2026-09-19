export interface ApiEnvelope<T> { code:number; statusCode:string; message:string; data:T; }
export type EstadoPedido='RECIBIDO'|'EN_PROCESO'|'DESPACHADO'|'ANULADO'|'COMPENSANDO'|'REQUIERE_REVISION';
export interface LineaPedido { sku:string; vendedorId:string; cantidad:number; precioUnitario:number; pesoUnitario:number; subtotal:number; }
export interface PedidoAdmin { pedidoId:string; estado:EstadoPedido; almacenId:string; subtotal:number; envio:number|null; total:number|null; pesoTotal:number; anulacionSolicitada:boolean; correlationId?:string; zonaEntrega?:string; items:LineaPedido[]; }
export interface PedidoProceso { paso:string; estado:string; intentos:number; ms:number|null; }
export interface PedidoDetalleAdmin extends PedidoAdmin { guia:{id:string;estado:string}|null; pasos:PedidoProceso[]; compensaciones:PedidoProceso[]; }
export interface ReintentoResponse { pedidoId:string; reintentoSolicitado:boolean; }
export interface AnulacionResponse { pedidoId:string; estado:EstadoPedido; solicitudId:string; estadoReserva:string; anulacionSolicitada:boolean; }
export interface CargaTotales { filas:number; aceptadas:number; rechazadas:number; duplicadas:number; }
export interface Carga { cargaId:string; estado:'PROCESANDO'|'PROCESADA'|'ERROR'; totales:CargaTotales; reporte:string|null; }
export interface PedidoSnapshot { pedidos:PedidoAdmin[]; limited:boolean; pages:number; }
