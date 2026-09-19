export type Role = 'COMPRADOR' | 'VENDEDOR' | 'ADMIN';
export interface Envelope<T> { code: number; statusCode: string; message: string; data: T; errores?: Record<string, string>; }
export interface User { id: string; nombre: string; rol: Role; }
export interface AuthResponse { accessToken: string; refreshToken: string; expiraEn: number; usuario: User; }
export interface Session extends AuthResponse { expiresAt: number; }
export interface Product { sku: string; vendedorId: string; almacenId: string | null; nombre: string; precio: number; peso: number; }
export interface ProductInput { sku: string; nombre: string; precio: number; peso: number; }
export interface Stock { sku: string; almacenId: string; disponible: number; reservado: number; total: number; }
export type OrderState = 'RECIBIDO' | 'EN_PROCESO' | 'DESPACHADO' | 'COMPENSANDO' | 'ANULADO' | 'REQUIERE_REVISION';
export type DeliveryZone = 'LIMA_METROPOLITANA' | 'LIMA_PROVINCIA' | 'PROVINCIA';
export interface OrderInput { solicitudId: string; almacenId: string; zonaEntrega: DeliveryZone; items: { sku: string; cantidad: number }[]; }
export interface OrderSummary { pedidoId: string; estado: OrderState; solicitudId: string; estadoReserva: string; anulacionSolicitada: boolean; }
export interface OrderLine { sku: string; vendedorId: string; cantidad: number; precioUnitario: number; pesoUnitario: number; subtotal: number; }
export interface ProcessStep { paso: string; estado: string; intentos: number; ms: number | null; }
export interface Guide { id: string; estado: string; }
export interface Order { pedidoId: string; estado: OrderState; almacenId: string; solicitudId?: string; zonaEntrega?: DeliveryZone; correlationId?: string; subtotal: number; envio: number | null; total: number | null; pesoTotal: number; anulacionSolicitada: boolean; items: OrderLine[]; }
export interface OrderDetail extends Order { guia: Guide | null; pasos: ProcessStep[]; compensaciones: ProcessStep[]; }
